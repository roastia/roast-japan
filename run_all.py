#!/usr/bin/env python3
"""
全スクレイパーの統合実行 & データマージスクリプト

実行方法:
  python run_all.py                  # 全ソース収集 → DB保存
  python run_all.py --dry-run        # JSON出力のみ
  python run_all.py --source osm     # OSMのみ
  python run_all.py --source gmaps   # Google Mapsのみ
  python run_all.py --source scaj    # SCAJのみ
  python run_all.py --pref 東京都    # 都道府県絞り込み（gmaps用）

実行後の確認クエリ:
  psql $DATABASE_URL -c "
    SELECT prefecture, COUNT(*) FROM shops
    GROUP BY prefecture ORDER BY count DESC;"
"""

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def run_script(script: str, extra_args: list[str] = []) -> bool:
    cmd = [sys.executable, script] + extra_args
    log.info(f"▶ 実行: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        log.error(f"  ✗ 失敗: {script}")
        return False
    log.info(f"  ✓ 完了: {script}")
    return True


def print_summary():
    """DBの現状サマリーを表示（psql が使える場合）"""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM shops")
        total = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM shops WHERE status = 'ACTIVE'")
        active = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM shops WHERE status = 'UNVERIFIED'")
        unverified = cur.fetchone()[0]

        cur.execute("""
            SELECT source_type, COUNT(DISTINCT shop_id)
            FROM data_sources GROUP BY source_type ORDER BY count DESC
        """)
        sources = cur.fetchall()

        cur.execute("""
            SELECT prefecture, COUNT(*) as cnt FROM shops
            GROUP BY prefecture ORDER BY cnt DESC LIMIT 10
        """)
        top_prefs = cur.fetchall()

        cur.close()
        conn.close()

        print("\n" + "="*50)
        print(f"  📊 収集結果サマリー ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
        print("="*50)
        print(f"  総店舗数:   {total:,} 件")
        print(f"  確認済み:   {active:,} 件")
        print(f"  未確認:     {unverified:,} 件")
        print()
        print("  ソース別件数:")
        for src, cnt in sources:
            print(f"    {src:<15} {cnt:>5} 件")
        print()
        print("  都道府県 TOP10:")
        for pref, cnt in top_prefs:
            bar = "█" * min(cnt // 2, 20)
            print(f"    {pref:<6} {cnt:>4} {bar}")
        print("="*50 + "\n")

    except Exception as e:
        log.warning(f"サマリー取得失敗: {e}")


def main():
    parser = argparse.ArgumentParser(description="全スクレイパー統合実行")
    parser.add_argument("--dry-run", action="store_true", help="DB保存せずJSONのみ出力")
    parser.add_argument("--source", choices=["osm", "gmaps", "scaj", "all"], default="all")
    parser.add_argument("--pref", type=str, default=None, help="対象都道府県（gmaps用）")
    args = parser.parse_args()

    dry_flag = ["--dry-run"] if args.dry_run else []
    pref_flag = ["--pref", args.pref] if args.pref else []

    results = {}

    # ── OSM ──────────────────────────────────────────────────
    if args.source in ("osm", "all"):
        log.info("=== Phase 1: OpenStreetMap 収集 ===")
        ok = run_script("collect_osm.py", dry_flag)
        results["OSM"] = "✓" if ok else "✗"

    # ── SCAJ ─────────────────────────────────────────────────
    if args.source in ("scaj", "all"):
        log.info("=== Phase 2: SCAJ会員リスト収集 ===")
        ok = run_script("scraper_scaj.py", dry_flag)
        results["SCAJ"] = "✓" if ok else "✗"

    # ── Google Maps ───────────────────────────────────────────
    if args.source in ("gmaps", "all"):
        log.info("=== Phase 3: Google Maps 収集 ===")
        ok = run_script("scraper_google_maps.py", dry_flag + pref_flag)
        results["Google Maps"] = "✓" if ok else "✗"

    # ── 結果表示 ──────────────────────────────────────────────
    print("\n実行結果:")
    for src, status in results.items():
        print(f"  {status} {src}")

    if not args.dry_run:
        print_summary()


if __name__ == "__main__":
    main()
