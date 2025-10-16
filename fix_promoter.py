import json, sys, os

F = "./data/promoters.json"
uid = "7360982123"  #  غيّرها لو تبغى

with open(F, "r", encoding="utf-8") as f:
    d = json.load(f)

before = len(d.get("users", {}))
d.setdefault("users", {}).pop(uid, None)

with open(F, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)

print(f"Done. removed={before - len(d.get('users', {}))} uid={uid}")
