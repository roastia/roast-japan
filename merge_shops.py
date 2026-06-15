"""
merge_shops.py
GitHub Actionsから呼ばれるマージスクリプト
使い方: python merge_shops.py <都道府県名>
"""
import json
import sys
import subprocess
from pathlib import Path

pref = sys.argv[1] if len(sys.argv) > 1 else ""

# output/shops_*.json を変換
json_files = list(Path("output").glob("shops_*.json"))
if not json_files:
    print("取得データなし。スキップ")
    sys.exit(0)

args = ["python", "convert_to_web.py"] + [str(p) for p in json_files] + ["--out", "shops_new.json"]
subprocess.run(args, check=True)

new_data = json.load(open("shops_new.json", encoding="utf-8"))
print(f"新規取得: {len(new_data)}件 ({pref})")

# 既存データとマージ
existing = []
if Path("shops.json").exists():
    existing = json.load(open("shops.json", encoding="utf-8"))
    print(f"既存: {len(existing)}件")

seen = set()
merged = []
for s in existing + new_data:
    key = (s.get("name", ""), s.get("pref", ""))
    if key not in seen:
        seen.add(key)
        merged.append(s)

for i, s in enumerate(merged):
    s["id"] = i + 1

json.dump(merged, open("shops.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"マージ後: {len(merged)}件")
