import json
F = "./data/promoters.json"
uid = "7360982123"
d = json.load(open(F, "r", encoding="utf-8"))
print("HAS", uid, "=", uid in d.get("users", {}))
