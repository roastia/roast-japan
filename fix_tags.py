import json, re
from pathlib import Path
from collections import Counter

SPECIALTY = ["スペシャルティ","specialty","single origin","シングルオリジン","ゲイシャ","geisha","third wave","サードウェーブ"]
ROASTERY  = ["焙煎","roaster","roastery","ロースター","ロースタリー","焙煎所","焙煎豆","self roast"]
CAFE      = ["カフェ","cafe","coffee stand","コーヒースタンド","スタンド","珈琲店","coffee shop","喫茶"]
ONLINE    = ["通販","オンライン","online","直売","豆販売","beans shop","ec shop","store"]

def has(keywords, *texts):
    t = " ".join(str(x or "").lower() for x in texts)
    return any(k.lower() in t for k in keywords)

data = json.load(open("shops.json", encoding="utf-8"))

for s in data:
    name    = s.get("name","")
    website = s.get("website","")
    address = s.get("address","")
    combined = name + " " + website + " " + address

    tags = []
    if has(SPECIALTY, combined):           tags.append("specialty")
    if has(ROASTERY,  combined):           tags.append("specialty")  # 焙煎系はspecialtyとみなす
    if has(CAFE,      combined):           tags.append("cafe")
    if has(ONLINE,    combined):           tags.append("online")
    if "instagram" in website.lower():     tags.append("cafe")
    if not tags:                           tags.append("cafe")

    # 重複除去・順序維持
    seen = set()
    s["tags"] = [t for t in tags if not (t in seen or seen.add(t))]

json.dump(data, open("shops.json","w",encoding="utf-8"), ensure_ascii=False, indent=2)

cnt = Counter(t for s in data for t in s.get("tags",[]))
print("タグ更新完了:")
for tag, n in cnt.most_common():
    print(f"  {tag}: {n}件")
