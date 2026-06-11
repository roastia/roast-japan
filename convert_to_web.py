import argparse, json, re, sys
from pathlib import Path
from collections import Counter

SPECIALTY_KEYWORDS = ["スペシャルティ","specialty","シングルオリジン","single origin","ゲイシャ","geisha"]
ROASTERY_KEYWORDS  = ["焙煎","roaster","roastery","ロースター","ロースタリー","焙煎所","焙煎豆"]
CAFE_KEYWORDS      = ["カフェ","cafe","珈琲店","コーヒースタンド","stand","喫茶"]
ONLINE_KEYWORDS    = ["通販","オンライン","online","直売","豆販売","beans shop"]

def extract_coords(url):
    if not url: return None, None
    m = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
    if m: return float(m.group(1)), float(m.group(2))
    m = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', url)
    if m: return float(m.group(1)), float(m.group(2))
    return None, None

def clean_phone(p):
    return re.sub(r'^電話番号?[:： ]+', '', str(p or '')).strip()

def has(keywords, *texts):
    t = " ".join(str(x or "").lower() for x in texts)
    return any(k.lower() in t for k in keywords)

def guess_tags(s):
    name    = s.get("name") or ""
    website = s.get("website") or ""
    address = s.get("address") or s.get("address_raw") or ""
    cat     = s.get("category") or ""
    services= " ".join(s.get("services") or [])
    combined = " ".join([name, website, address, cat])
    tags = []
    if has(SPECIALTY_KEYWORDS, combined): tags.append("specialty")
    if has(ROASTERY_KEYWORDS,  combined): tags.append("specialty")
    if has(CAFE_KEYWORDS,      combined): tags.append("cafe")
    if has(ONLINE_KEYWORDS,    combined + " " + services): tags.append("online")
    if "instagram" in website.lower(): tags.append("cafe")
    seen = set()
    result = [t for t in tags if not (t in seen or seen.add(t))]
    return result or ["cafe"]

def normalize(s, i):
    name = s.get("name") or s.get("shop_name")
    if not name: return None
    lat = s.get("lat") or s.get("latitude")
    lng = s.get("lng") or s.get("lon") or s.get("longitude")
    if not lat or not lng:
        lat, lng = extract_coords(s.get("source_url") or "")
    if not lat or not lng: return None
    try: lat, lng = float(lat), float(lng)
    except: return None
    if not (24 <= lat <= 46 and 122 <= lng <= 154): return None
    pref = (s.get("prefecture") or s.get("pref") or "不明").strip()
    try: rating = round(float(s["rating"]), 1) if s.get("rating") else None
    except: rating = None
    try: reviews = int(s.get("review_count") or s.get("reviews") or 0)
    except: reviews = 0
    return {
        "id":i+1,"name":name.strip(),"pref":pref,
        "city":s.get("city") or "","address":s.get("address_raw") or s.get("address") or "",
        "lat":lat,"lng":lng,"rating":rating,"reviews":reviews,
        "tags":guess_tags(s),"website":s.get("website") or "",
        "phone":clean_phone(s.get("phone")),"instagram":s.get("instagram") or "",
        "category":s.get("category") or "","hours":s.get("hours") or {},
        "photos":(s.get("photos") or [])[:5],
        "payment":s.get("payment_methods") or s.get("payment") or [],
        "services":s.get("services") or [],
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--out", default="shops.json")
    parser.add_argument("--min-rating", type=float, default=None)
    parser.add_argument("--pref", type=str, default=None)
    args = parser.parse_args()
    raw = []
    for pat in args.inputs:
        matches = sorted(Path(".").glob(pat))
        if not matches:
            p = Path(pat)
            if p.exists(): matches = [p]
        for p in matches:
            d = json.load(open(p, encoding="utf-8"))
            d = d if isinstance(d, list) else [d]
            print(f"読み込み: {p} ({len(d)} 件)")
            raw.extend(d)
    if not raw:
        print("データがありません"); sys.exit(1)
    normalized = []
    for i, s in enumerate(raw):
        try:
            r = normalize(s, i)
            if r: normalized.append(r)
        except Exception as e:
            print(f"  スキップ ({s.get('name','?')}): {e}")
    seen = set()
    unique = []
    for s in normalized:
        k = (s["name"], s["pref"])
        if k not in seen:
            seen.add(k); unique.append(s)
    if args.min_rating:
        unique = [s for s in unique if s["rating"] and s["rating"] >= args.min_rating]
    if args.pref:
        unique = [s for s in unique if s["pref"] == args.pref]
    for i, s in enumerate(unique): s["id"] = i + 1
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(unique, open(args.out,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n完了: {len(raw)} 件入力 → {len(unique)} 件出力 → {args.out}")
    print(f"  営業時間あり: {sum(1 for s in unique if s['hours'])} 件")
    print(f"  写真あり:     {sum(1 for s in unique if s['photos'])} 件")
    print(f"  支払情報あり: {sum(1 for s in unique if s['payment'])} 件")
    print(f"  サービスあり: {sum(1 for s in unique if s['services'])} 件")
    for pref, cnt in Counter(s["pref"] for s in unique).most_common(10):
        print(f"  {pref:<8} {cnt} 件")

main()
