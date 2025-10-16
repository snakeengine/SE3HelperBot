import json, os, pathlib, sys

UID = (sys.argv[1] if len(sys.argv)>1 else "").strip()
if not UID.isdigit():
    print("Usage: python demote_promoter.py <TELEGRAM_ID>")
    sys.exit(1)

def jload(p, default): 
    try: 
        return json.load(open(p,"r",encoding="utf-8"))
    except: 
        return default

def jsave(p, d):
    pathlib.Path(p).parent.mkdir(parents=True, exist_ok=True)
    open(p,"w",encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=2))

summary=[]

# 1) promoters.json -> احذف المستخدم من users
for path in ("./data/promoters.json", "/data/se3_data/promoters.json"):
    if os.path.exists(path):
        d = jload(path, {"users":{}, "settings":{"daily_limit":5}})
        before = len(d.get("users", {}))
        d.setdefault("users", {}).pop(UID, None)
        jsave(path, d)
        summary.append(f"{path}: removed={before-len(d['users'])}")

# 2) promoter_live.json -> شيل أي أثر له
for path in ("./data/promoter_live.json", "/data/promoter_live.json"):
    if os.path.exists(path):
        x = jload(path, {})
        changed=0
        if isinstance(x, dict) and UID in x:
            x.pop(UID, None); changed=1
        elif isinstance(x, list) and UID in [str(v) for v in x]:
            x = [v for v in x if str(v)!=UID]; changed=1
        jsave(path, x); summary.append(f"{path}: changed={changed}")

# 3) roles.json -> أزل دور promoter لو موجود
for path in ("./data/roles.json", "/data/roles.json"):
    if os.path.exists(path):
        r = jload(path, {})
        row = r.get(UID)
        changed=0
        if isinstance(row, dict):
            roles=row.get("roles")
            if isinstance(roles, list) and "promoter" in roles:
                row["roles"]=[x for x in roles if x!="promoter"]; r[UID]=row; changed=1
        jsave(path, r); summary.append(f"{path}: promoter_role_removed={changed}")

print("DONE demote:", UID)
for line in summary: print(" -", line)
