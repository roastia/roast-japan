#!/usr/bin/env python3
"""
SCAJ（日本スペシャルティコーヒー協会）会員店舗スクレイパー
https://scaj.org/member/

SCAJサイトの会員一覧ページを Playwright でスクレイピングし、
焙煎業者・カフェカテゴリの店舗情報を取得する。

実行方法:
  python scraper_scaj.py
  python scraper_scaj.py --dry-run
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from tqdm import tqdm

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")
OUTPUT_DIR   = Path("./output")
CONFIDENCE   = 0.90  # SCAJ公式リストは信頼度高め
PAGE_PAUSE   = 1.2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# SCAJ 会員カテゴリ（焙煎関係のみ対象）
TARGET_CATEGORIES = [
    "焙煎業者",
    "小売業者",
    "カフェ",
    "輸入業者",
]

SCAJ_MEMBER_URL = "https://scaj.org/member/"


def scrape_scaj(page) -> list[dict]:
    """
    SCAJ 会員一覧ページをスクレイピング。
    カテゴリタブを切り替えながら全会員情報を収集。
    """
    shops = []

    try:
        page.goto(SCAJ_MEMBER_URL, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_load_state("networkidle", timeout=10000)
    except PWTimeout:
        log.error("SCAJサイトへの接続がタイムアウトしました")
        return []

    log.info("SCAJトップページ読み込み完了")

    # ── パターン1: カテゴリ別タブがある場合 ──────────────────
    tabs = page.query_selector_all('.member-category, [class*="category"] a, .tab a')
    if tabs:
        log.info(f"  タブ発見: {len(tabs)} 個")
        for tab in tabs:
            tab_text = tab.inner_text().strip()
            if not any(cat in tab_text for cat in TARGET_CATEGORIES):
                continue
            log.info(f"  カテゴリ処理中: {tab_text}")
            tab.click()
            time.sleep(PAGE_PAUSE)
            members = extract_member_list(page, tab_text)
            shops.extend(members)
    else:
        # ── パターン2: ページネーションありの一覧 ──────────────
        log.info("  タブなし: ページネーション形式を試みます")
        page_num = 1
        while True:
            members = extract_member_list(page, "SCAJ")
            if not members:
                break
            shops.extend(members)

            # 次ページへ
            next_btn = page.query_selector('a[rel="next"], .next a, a:has-text("次へ")')
            if not next_btn:
                break
            next_btn.click()
            time.sleep(PAGE_PAUSE)
            page_num += 1
            log.info(f"  ページ {page_num} へ移動")

    log.info(f"SCAJ: {len(shops)} 件収集")
    return shops


def extract_member_list(page, category: str) -> list[dict]:
    """
    現在表示されているページの会員リストを抽出。
    SCAJサイトの実際のHTML構造に合わせたセレクタを複数用意。
    """
    members = []

    # セレクタ候補（SCAJのHTML構造変更に備えて複数用意）
    row_selectors = [
        "table.member-table tbody tr",
        ".member-list li",
        ".member-item",
        "article.member",
        "tr[class*='member']",
    ]

    rows = []
    for sel in row_selectors:
        rows = page.query_selector_all(sel)
        if rows:
            log.debug(f"  セレクタ '{sel}' で {len(rows)} 行ヒット")
            break

    if not rows:
        # フォールバック: テーブル全行を解析
        rows = page.query_selector_all("table tr")
        log.debug(f"  フォールバック: table tr で {len(rows)} 行")

    for row in rows:
        text = row.inner_text().strip()
        if not text or len(text) < 3:
            continue

        member = parse_member_row(row, text, category)
        if member and member.get("name"):
            members.append(member)

    return members


def parse_member_row(row, text: str, category: str) -> dict:
    """
    1行のHTML要素から会員情報を抽出。
    列構成が不明なため、テキストパターンと属性から推定する。
    """
    import re

    cells = row.query_selector_all("td, dd, .field")
    cell_texts = [c.inner_text().strip() for c in cells]

    # リンク（ウェブサイト）を抽出
    links = row.query_selector_all("a[href]")
    website = None
    for link in links:
        href = link.get_attribute("href") or ""
        if href.startswith("http") and "scaj.org" not in href:
            website = href
            break

    # 名前: 最初の非空セル or 最初のリンクテキスト
    name = None
    if cell_texts:
        name = next((t for t in cell_texts if t and len(t) > 1), None)
    if not name and links:
        name = links[0].inner_text().strip()
    if not name:
        # 1行テキスト全体から最初の単語
        name = text.split("\n")[0].strip()[:50]

    # 都道府県パターン
    pref_pattern = r'(北海道|(?:東京|京都|大阪)都?府?|.{2,3}[都道府県])'
    pref_match = re.search(pref_pattern, text)
    prefecture = pref_match.group(1) if pref_match else None

    # 電話番号パターン
    phone_match = re.search(r'0\d{1,4}[-\s]\d{2,4}[-\s]\d{4}', text)
    phone = phone_match.group(0) if phone_match else None

    return {
        "name":        name,
        "prefecture":  prefecture,
        "phone":       phone,
        "website":     website,
        "category":    category,
        "raw_text":    text[:200],
    }


def save_scaj_to_db(conn, shop: dict) -> str:
    cur = conn.cursor()

    # 重複チェック（名前 + 都道府県）
    cur.execute("""
        SELECT id FROM shops WHERE name = %s AND prefecture = %s LIMIT 1
    """, (shop["name"], shop.get("prefecture")))
    row = cur.fetchone()

    if row:
        shop_id = row[0]
    else:
        shop_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO shops (
                id, name, prefecture, phone, website,
                status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, 'UNVERIFIED', now(), now())
        """, (
            shop_id, shop["name"], shop.get("prefecture"),
            shop.get("phone"), shop.get("website"),
        ))
        cur.execute("""
            INSERT INTO roasting_info (id, shop_id, sourcing_style)
            VALUES (%s, %s, 'SPECIALTY')
            ON CONFLICT (shop_id) DO NOTHING
        """, (str(uuid.uuid4()), shop_id))

        # SCAJ会員 → 認定レコード追加
        cur.execute("""
            INSERT INTO certifications (id, shop_id, cert_type, issuer)
            VALUES (%s, %s, 'SCAJ_MEMBER', 'SCAJ')
            ON CONFLICT DO NOTHING
        """, (str(uuid.uuid4()), shop_id))

    # DataSource
    cur.execute("""
        INSERT INTO data_sources (
            id, shop_id, source_type, source_url, raw_id, fetched_at, confidence
        ) VALUES (%s, %s, 'SCAJ', %s, %s, now(), %s)
        ON CONFLICT (source_type, raw_id) DO NOTHING
    """, (
        str(uuid.uuid4()), shop_id,
        SCAJ_MEMBER_URL,
        f"scaj_{shop['name']}",
        CONFIDENCE,
    ))

    conn.commit()
    cur.close()
    return shop_id


def main():
    import argparse
    parser = argparse.ArgumentParser(description="SCAJ会員スクレイパー")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)

    conn = None
    if not args.dry_run:
        if not DATABASE_URL:
            log.error("DATABASE_URL 未設定。--dry-run で試してください。")
            raise SystemExit(1)
        conn = psycopg2.connect(DATABASE_URL)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            locale="ja-JP",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()

        try:
            shops = scrape_scaj(page)
        finally:
            browser.close()

    # 出力
    out_file = OUTPUT_DIR / f"scaj_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(shops, f, ensure_ascii=False, indent=2)
    log.info(f"JSON保存: {out_file} ({len(shops)} 件)")

    if conn:
        for shop in tqdm(shops, desc="DB保存"):
            try:
                save_scaj_to_db(conn, shop)
            except Exception as e:
                log.warning(f"DB保存失敗 ({shop.get('name','?')}): {e}")
                conn.rollback()
        conn.close()

    log.info("完了")


if __name__ == "__main__":
    main()
