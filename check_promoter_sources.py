import json, os

UID = "7360982123"

def jload(p, default=None):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

candidates = [
    "./data/promoters.json",
    "/data/se3_data/promoters.json",
    "./data/promoter_live.json",
    "/data/promoter_live.json",
    "./data/roles.json",
    "/data/roles.json",
    "/data/users.json",
    "/data/alerts/known_users.json",
]

print("== promoter-related sources ==")
for p in candidates:
    if os.path.exists(p):
        x = jload(p, {})
        hit = False; detail = ""
        if isinstance(x, dict):
            if UID in x:
                hit = True; detail = str(x.get(UID))
            elif isinstance(x.get("users"), dict) and UID in x["users"]:
                hit = True; detail = str(x["users"][UID])
        elif isinstance(x, list):
            hit = UID in [str(v) for v in x]; detail = "(list)"
        print(f"{p:35s} -> {hit}  {detail}")
    else:
        print(f"{p:35s} -> not found")
