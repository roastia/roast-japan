# roastia プロジェクト引き継ぎメモ

## プロジェクト概要
**roastia** — 日本最大級の自家焙煎珈琲店データベース
- URL: https://roastia.github.io/roast-japan
- GitHub: https://github.com/roastia/roast-japan
- 作業フォルダ: C:\Users\Youfit\Downloads\roastia

---

## ファイル構成

```
roastia/
├── index.html              ← メインのウェブページ（全機能入り）
├── shops.json              ← 店舗データ（本番データ）
├── convert_to_web.py       ← スクレイパーJSON → shops.json変換
├── scraper_google_maps.py  ← Google Mapsスクレイパー
├── scraper_scaj.py         ← SCAJ会員リストスクレイパー
├── collect_osm.py          ← OpenStreetMapデータ収集
├── merge_shops.py          ← shops.jsonマージ（GitHub Actions用）
├── run_all.py              ← 全スクレイパー一括実行
├── output/                 ← スクレイパーの出力先
└── .github/
    └── workflows/
        └── update.yml      ← 毎週自動更新のGitHub Actions設定
```

---

## 技術スタック

| 用途 | 技術 |
|------|------|
| ホスティング | GitHub Pages（無料） |
| 地図 | Leaflet.js + MarkerCluster |
| ルート表示 | Leaflet Routing Machine（OSRM） |
| 認証・DB | Firebase（Authentication + Firestore） |
| スクレイピング | Python + Playwright |
| 自動更新 | GitHub Actions（毎週月曜AM3時） |

---

## index.htmlの主な機能

### UI
- コーヒーカラー（#6F4E37 など）のデザイン
- Playfair Display（serif）+ Josefin Sans（sans）フォント
- PC: 左リスト・右マップの2カラムレイアウト
- スマホ: マップ上・リスト下の縦積みレイアウト

### 検索・絞り込み
- 現在地（GPS）自動取得 → マップ中心に移動
- 住所・駅名入力 → Nominatim（OSM）でジオコーディング
- マップクリック → その場所を基点に設定
- 徒歩60分圏内の店舗をリストに表示・距離順ソート
- 座席あり / 座席なし の絞り込み（ラジオボタン）

### マップ
- Leaflet.js + OpenStreetMap
- マーカークラスタリング（MarkerCluster）
- コーヒー豆SVGアイコン
- 店舗クリック → ポップアップ表示
- 現在地ピン（青）/ 住所ピン（オレンジ）/ マップクリックピン（緑）
- 徒歩ルート表示（Leaflet Routing Machine）

### 店舗詳細モーダル
- スマホ: 画面上から82%の高さで表示、下部タップで閉じる
- PC: 中央表示
- 情報: 住所・電話・営業時間・支払方法・サービス・タグ
- 下部固定ボタン: ウェブサイト / ルート案内 / 📞電話
- お気に入りボタン（♡）← Firebase要ログイン
- 個人評価（★1〜5）＋メモ ← 自分だけに見える

### ログイン機能（Firebase）
- メール＋パスワード認証
- Googleアカウントログイン
- お気に入り登録（Firestore保存）
- 個人評価・メモ（Firestoreに自分のみ閲覧可で保存）

---

## Firebase設定

```javascript
const firebaseConfig = {
  apiKey: "AIzaSyDsyPuwfAxBsqXO0iVXcM6NoOiXVLcFb7Q",
  authDomain: "roastia-f9907.firebaseapp.com",
  projectId: "roastia-f9907",
  storageBucket: "roastia-f9907.firebasestorage.app",
  messagingSenderId: "860378474766",
  appId: "1:860378474766:web:dc83b21a2f48c6db644f5f"
};
```

**Firestoreのデータ構造**
```
users/{userId}/
  favorites/{shopId}   → { shopId, addedAt }
  reviews/{shopId}     → { rating(1-5), memo, updatedAt }
```

**Firestoreセキュリティルール（要設定）**
```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /users/{userId}/{document=**} {
      allow read, write: if request.auth != null && request.auth.uid == userId;
    }
  }
}
```
設定URL: https://console.firebase.google.com/project/roastia-f9907/firestore/rules

---

## shops.jsonの構造

```json
{
  "id": 1,
  "name": "店舗名",
  "pref": "都道府県",
  "city": "市区町村",
  "address": "住所",
  "lat": 35.669,
  "lng": 139.709,
  "rating": 4.2,
  "reviews": 843,
  "tags": ["specialty", "cafe", "online"],
  "website": "https://...",
  "phone": "03-xxxx-xxxx",
  "instagram": "@username",
  "category": "カフェ・喫茶",
  "hours": { "月曜日": "9:00〜18:00", ... },
  "photos": ["https://..."],
  "payment": ["クレジットカード", "PayPay"],
  "services": ["テイクアウト", "イートイン"],
  "status": "active"
}
```

**tagsの種類**
- `specialty` → スペシャルティ系
- `cafe` → 座席あり
- `online` → 通販あり
- `scaj` → SCAJ会員

---

## スクレイピング運用

### 手動実行
```powershell
cd C:\Users\Youfit\Downloads\roastia

# 特定県のみ（テスト用）
python scraper_google_maps.py --pref 東京都 --dry-run

# 変換
python convert_to_web.py output/shops_*.json --out shops.json
```

### GitHub Actionsによる自動更新
- 毎週月曜 AM3:00 JST に自動実行
- 47都道府県を1県ずつ実行（max-parallel:1）
- 1県完了ごとにshops.jsonにマージ・コミット
- 途中失敗しても完了済み県のデータは保持

### 閉店検出
- Google Mapsの「永久に閉業」を検出してstatus=closedに設定
- convert_to_web.pyでclosedを自動除外

### 座標バリデーション
- 都道府県と座標が一致しない店舗は自動除外（PREF_BOUNDSによるチェック）

---

## 未完了タスク

- [ ] Firestoreセキュリティルールの設定
- [ ] お気に入り一覧ページの本格実装
- [ ] GitHub Actions の全国スクレイピング完走
- [ ] 閉店検出スクリプトのGitHubへのアップロード（scraper_google_maps.py, convert_to_web.py, merge_shops.py）
