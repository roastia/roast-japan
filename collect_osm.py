#!/usr/bin/env python3
"""
自家焙煎珈琲店 OSM収集スクリプト
OpenStreetMap Overpass API から全国の自家焙煎カフェ情報を収集し
PostgreSQL（Prisma スキーマ準拠）に INSERT する。

必要ライブラリ:
  pip install requests psycopg2-binary python-dotenv tqdm

使い方:
  DATABASE_URL=postgresql://user:pass@localhost:5432/coffeedb python collect_osm.py
"""

import os
import time
import uuid
import json
import logging
import requests
import psycopg2
from datetime import datetime, timezone
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

# ============================================================
# 設定
# ============================================================
OVERPASS_URL   = "https://overpass-api.de/api/interpreter"
DATABASE_URL   = os.environ.get("DATABASE_URL", "")
REQUEST_DELAY  = 2.0   # Overpass API への礼儀（秒）
CONFIDENCE_OSM = 0.6   # OSMソースの信頼度スコア

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ============================================================
# Overpass クエリ定義
# 複数キーワードで幅広くヒットさせる
# ============================================================
OVERPASS_QUERY = """
[out:json][timeout:120];
area["name"="日本"]["admin_level"="2"]->.japan;
(
  node["amenity"="cafe"]["roasting"="yes"](area.japan);
  node["amenity"="cafe"]["name"~"焙煎|自家焙|ロースト|roast|ROAST",i](area.japan);
  node["amenity"="cafe"]["description"~"自家焙煎|スペシャルティ",i](area.japan);
  node["shop"="coffee"]["roasting"="yes"](area.japan);
  node["shop"="coffee"]["name"~"焙煎|ロースト",i](area.japan);
  way["amenity"="cafe"]["name"~"焙煎|自家焙|ロースト",i](area.japan);
  way["shop"="coffee"]["name"~"焙煎|ロースト",i](area.japan);
);
out body center;
"""

# ============================================================
# OSM → 都道府県マッピング（addr:province / addr:city 優先、なければ座標から推定）
# ============================================================
PREF_LAT_RANGES = [
    ("北海道",  41.3,  45.6,  139.3, 145.9),
    ("青森県",  40.2,  41.6,  139.7, 141.7),
    ("岩手県",  38.7,  40.4,  140.5, 142.1),
    ("宮城県",  37.7,  38.9,  140.2, 141.7),
    ("秋田県",  38.8,  40.5,  139.4, 141.0),
    ("山形県",  37.7,  39.2,  139.5, 141.1),
    ("福島県",  36.8,  37.9,  138.9, 141.1),
    ("茨城県",  35.7,  36.9,  139.7, 140.9),
    ("栃木県",  36.2,  37.2,  139.3, 140.3),
    ("群馬県",  36.1,  37.0,  138.3, 139.7),
    ("埼玉県",  35.7,  36.3,  138.9, 139.9),
    ("千葉県",  34.9,  35.9,  139.7, 140.9),
    ("東京都",  35.5,  35.9,  138.9, 139.9),
    ("神奈川県",35.1,  35.7,  139.0, 139.8),
    ("新潟県",  36.8,  38.6,  137.6, 139.6),
    ("富山県",  36.3,  37.0,  136.7, 137.7),
    ("石川県",  36.1,  37.9,  136.3, 137.4),
    ("福井県",  35.4,  36.3,  135.6, 136.8),
    ("山梨県",  35.2,  35.9,  138.3, 139.0),
    ("長野県",  35.2,  37.0,  137.3, 138.9),
    ("岐阜県",  35.1,  36.4,  135.8, 137.7),
    ("静岡県",  34.6,  35.5,  137.5, 139.2),
    ("愛知県",  34.5,  35.4,  136.7, 137.7),
    ("三重県",  33.7,  35.2,  135.8, 136.9),
    ("滋賀県",  34.8,  35.7,  135.8, 136.5),
    ("京都府",  34.7,  35.8,  135.0, 135.9),
    ("大阪府",  34.3,  34.9,  135.2, 135.8),
    ("兵庫県",  34.2,  35.7,  134.2, 135.5),
    ("奈良県",  34.1,  34.8,  135.7, 136.3),
    ("和歌山県",33.4,  34.3,  135.0, 136.1),
    ("鳥取県",  35.0,  35.6,  133.3, 134.6),
    ("島根県",  34.3,  35.6,  131.7, 133.6),
    ("岡山県",  34.4,  35.4,  133.3, 134.5),
    ("広島県",  34.1,  35.3,  132.1, 133.5),
    ("山口県",  33.6,  34.8,  130.6, 132.3),
    ("徳島県",  33.5,  34.3,  133.6, 134.8),
    ("香川県",  34.0,  34.5,  133.5, 134.5),
    ("愛媛県",  32.9,  34.3,  132.1, 133.7),
    ("高知県",  32.7,  34.0,  132.6, 134.3),
    ("福岡県",  33.1,  34.3,  130.0, 131.2),
    ("佐賀県",  33.0,  33.7,  129.7, 130.6),
    ("長崎県",  32.5,  33.9,  128.7, 130.3),
    ("熊本県",  32.0,  33.2,  130.0, 131.4),
    ("大分県",  32.7,  33.7,  130.8, 132.0),
    ("宮崎県",  31.4,  32.8,  130.7, 131.9),
    ("鹿児島県",30.2,  32.3,  129.3, 131.4),
    ("沖縄県",  24.0,  27.1,  122.9, 131.4),
]

def guess_prefecture(lat: float, lng: float) -> str:
    """座標から都道府県を推定（簡易版）"""
    for pref, lat_min, lat_max, lng_min, lng_max in PREF_LAT_RANGES:
        if lat_min <= lat <= lat_max and lng_min <= lng <= lng_max:
            return pref
    return "不明"

# ============================================================
# Overpass API 呼び出し
# ============================================================
def fetch_osm_data() -> list[dict]:
    log.info("Overpass API にリクエスト送信中...")
    try:
        resp = requests.post(
            OVERPASS_URL,
            data={"data": OVERPASS_QUERY},
            timeout=150,
            headers={"User-Agent": "CoffeeRoasterDB/1.0 (research project)"},
        )
        resp.raise_for_status()
        data = resp.json()
        elements = data.get("elements", [])
        log.info(f"  → {len(elements)} 件取得")
        return elements
    except requests.exceptions.RequestException as e:
        log.error(f"Overpass API エラー: {e}")
        raise

# ============================================================
# OSM 要素を正規化
# ============================================================
def normalize_element(elem: dict) -> dict | None:
    tags = elem.get("tags", {})

    # 座標取得（wayの場合はcenterを使う）
    if elem["type"] == "node":
        lat = elem.get("lat")
        lng = elem.get("lon")
    elif elem["type"] == "way":
        center = elem.get("center", {})
        lat = center.get("lat")
        lng = center.get("lon")
    else:
        return None

    if not lat or not lng:
        return None

    name = tags.get("name") or tags.get("name:ja")
    if not name:
        return None

    # 住所組み立て
    addr_pref   = tags.get("addr:province") or tags.get("addr:state") or ""
    addr_city   = tags.get("addr:city") or tags.get("addr:county") or ""
    addr_street = tags.get("addr:street") or ""
    addr_housen = tags.get("addr:housenumber") or ""

    prefecture = addr_pref or guess_prefecture(lat, lng)
    address    = addr_street + addr_housen if addr_street else None

    return {
        "name":       name,
        "name_kana":  tags.get("name:ja-Hira") or tags.get("name:ja-Latn"),
        "prefecture": prefecture,
        "city":       addr_city or None,
        "address":    address,
        "lat":        lat,
        "lng":        lng,
        "phone":      tags.get("phone") or tags.get("contact:phone"),
        "website":    tags.get("website") or tags.get("contact:website"),
        "instagram":  tags.get("contact:instagram"),
        "twitter":    tags.get("contact:twitter"),
        "osm_type":   elem["type"],
        "osm_id":     str(elem["id"]),
    }

# ============================================================
# 重複チェック（座標近傍 + 名前一致）
# ============================================================
def find_duplicate(cur, lat: float, lng: float, name: str) -> str | None:
    """半径50m以内かつ名前が一致する店舗のIDを返す"""
    cur.execute("""
        SELECT id FROM shops
        WHERE name = %s
          AND lat IS NOT NULL AND lng IS NOT NULL
          AND point(lng, lat) <-> point(%s, %s) < 0.0005
        LIMIT 1
    """, (name, lng, lat))
    row = cur.fetchone()
    return row[0] if row else None

# ============================================================
# DB 書き込み
# ============================================================
def upsert_shop(cur, shop: dict) -> str:
    """
    既存レコードがあれば DataSource のみ追加。
    なければ shops / roasting_info / data_sources を INSERT。
    戻り値: shop_id
    """
    dup_id = find_duplicate(cur, shop["lat"], shop["lng"], shop["name"])

    if dup_id:
        log.debug(f"  重複検出 → {shop['name']} (existing id: {dup_id})")
        shop_id = dup_id
    else:
        shop_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO shops (
                id, name, name_kana, prefecture, city, address,
                lat, lng, phone, website, instagram, twitter,
                status, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                'UNVERIFIED', now(), now()
            )
        """, (
            shop_id,
            shop["name"],
            shop.get("name_kana"),
            shop["prefecture"],
            shop.get("city"),
            shop.get("address"),
            shop["lat"],
            shop["lng"],
            shop.get("phone"),
            shop.get("website"),
            shop.get("instagram"),
            shop.get("twitter"),
        ))

        # roasting_info（焙煎関連フラグは後で手動更新）
        cur.execute("""
            INSERT INTO roasting_info (id, shop_id, sourcing_style)
            VALUES (%s, %s, 'UNKNOWN')
            ON CONFLICT (shop_id) DO NOTHING
        """, (str(uuid.uuid4()), shop_id))

    # DataSource を追加（同一 OSM ID は重複 INSERT しない）
    raw_id = f"{shop['osm_type']}/{shop['osm_id']}"
    cur.execute("""
        INSERT INTO data_sources (
            id, shop_id, source_type, source_url, raw_id, fetched_at, confidence
        ) VALUES (%s, %s, 'OSM', %s, %s, now(), %s)
        ON CONFLICT (source_type, raw_id) DO NOTHING
    """, (
        str(uuid.uuid4()),
        shop_id,
        f"https://www.openstreetmap.org/{shop['osm_type']}/{shop['osm_id']}",
        raw_id,
        CONFIDENCE_OSM,
    ))

    return shop_id

# ============================================================
# メイン処理
# ============================================================
def main():
    log.info("=== 自家焙煎珈琲店 OSM 収集スクリプト ===")

    # DB 接続確認
    if not DATABASE_URL:
        log.error("DATABASE_URL が設定されていません。.env ファイルを確認してください。")
        raise SystemExit(1)

    elements = fetch_osm_data()
    time.sleep(REQUEST_DELAY)

    # 正規化
    shops = [r for e in elements if (r := normalize_element(e)) is not None]
    log.info(f"正規化後: {len(shops)} 件（名前・座標なしを除外）")

    if not shops:
        log.warning("有効なデータが0件です。終了します。")
        return

    # DB 書き込み
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    inserted = 0
    duplicates = 0

    try:
        for shop in tqdm(shops, desc="DB 書き込み"):
            try:
                shop_id = upsert_shop(cur, shop)
                # 重複チェックで既存IDが返ったかどうかで集計
                if find_duplicate(cur, shop["lat"], shop["lng"], shop["name"]) == shop_id:
                    duplicates += 1
                else:
                    inserted += 1
            except Exception as e:
                log.warning(f"スキップ ({shop.get('name', '?')}): {e}")
                conn.rollback()
                continue

        conn.commit()
        log.info(f"完了 — 新規: {len(shops) - duplicates} 件 / 重複スキップ: {duplicates} 件")

    except Exception as e:
        conn.rollback()
        log.error(f"DB エラー: {e}")
        raise
    finally:
        cur.close()
        conn.close()

    # 結果サマリーを JSON で保存
    summary = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "osm_elements": len(elements),
        "normalized": len(shops),
        "duplicates_skipped": duplicates,
    }
    with open("collect_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    log.info("collect_summary.json を保存しました。")

if __name__ == "__main__":
    main()
