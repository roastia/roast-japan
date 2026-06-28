# 自家焙煎珈琲店 Playwright スクレイパー

## ファイル構成

```
coffee_scraper/
├── scraper_google_maps.py  # Google Maps スクレイパー（メイン）
├── scraper_scaj.py         # SCAJ会員リスト スクレイパー
├── run_all.py              # 全ソース一括実行 & サマリー表示
└── README.md               # このファイル
```

---

## セットアップ

```bash
pip install playwright psycopg2-binary python-dotenv tqdm
python -m playwright install chromium
```

`.env` ファイルを作成:
```
DATABASE_URL=postgresql://user:pass@localhost:5432/coffeedb
```

---

## 実行方法

```bash
# ① 全ソース一括（推奨）
python run_all.py

# ② 特定のソースだけ
python run_all.py --source osm
python run_all.py --source gmaps
python run_all.py --source scaj

# ③ 都道府県を絞って素早くテスト
python run_all.py --source gmaps --pref 東京都

# ④ DBに書かず JSON だけ出力（動作確認用）
python run_all.py --dry-run
```

---

## 各スクレイパーの仕様

### scraper_google_maps.py

| 項目 | 内容 |
|------|------|
| 対象 | Google Maps 検索結果 |
| キーワード | 自家焙煎 コーヒー / スペシャルティコーヒー 焙煎 / 珈琲 自家焙煎 / コーヒーロースター |
| 取得項目 | 店舗名・住所・電話・URL・評価・レビュー数・座標 |
| 信頼度スコア | 0.75 |
| 重複防止 | Google Place ID または 座標×名前で判定 |

**Google Maps の注意点:**
- 1つのキーワードで最大約180件（スクロール上限）
- 全国×4キーワード = 最大 約35,000件取得可能
- レート制限に注意。間隔を `SCROLL_PAUSE` / `PAGE_PAUSE` で調整
- `HEADLESS = False` にするとブラウザが見えてデバッグしやすい

### scraper_scaj.py

| 項目 | 内容 |
|------|------|
| 対象 | SCAJ（日本スペシャルティコーヒー協会）会員一覧 |
| 取得項目 | 店舗名・都道府県・電話・URL |
| 信頼度スコア | 0.90（公式リストのため高め） |
| 付加情報 | `certifications` テーブルに `SCAJ_MEMBER` を自動登録 |

---

## 収集フロー

```
OSM Overpass API（無料・自動）
        ↓
SCAJ 会員リスト（公式・高信頼度）
        ↓
Google Maps（最大件数・詳細情報）
        ↓
    shops テーブル（重複マージ済み）
```

---

## 信頼度スコアと status の運用

| confidence | status 更新方針 |
|-----------|----------------|
| 0.9以上（SCAJ） | 手動確認後 ACTIVE へ |
| 0.75（Google Maps） | 複数ソース一致で ACTIVE へ |
| 0.6（OSM） | Google Mapsと一致で信頼度UP |

```sql
-- 複数ソースで確認できた店舗を ACTIVE に更新
UPDATE shops SET status = 'ACTIVE'
WHERE id IN (
  SELECT shop_id FROM data_sources
  GROUP BY shop_id HAVING COUNT(DISTINCT source_type) >= 2
);
```

---

## トラブルシューティング

**Google Maps で結果が取れない場合**
- `HEADLESS = False` にして実際のブラウザで確認
- Google が一時的にブロックしている可能性あり → 数時間待つ
- User-Agent を変更してみる

**セレクタが機能しない場合**
- Google Maps の HTML 構造は頻繁に変更される
- `page.query_selector_all('a[href*="/maps/place/"]')` は比較的安定
- 変更時は `HEADLESS = False` で要素を目視確認

**接続が遅い場合**
- `SCROLL_PAUSE` と `PAGE_PAUSE` を増やす
- 都道府県を分割して並列実行する（複数ターミナルで `--pref` を指定）
