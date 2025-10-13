import os, io, re, json, pathlib

# مجموعة أحرف الموجيبايك الشائعة
MOJI = set("ØÙÛÜÃÂÊËäâæéèï’œ")

def looks_moji(s: str) -> bool:
    return any(ch in MOJI for ch in s)

def unmoji(s: str) -> str:
    try:
        fixed = bytes(s, "latin-1").decode("utf-8")
        ar = sum(1 for c in fixed if "\u0600" <= c <= "\u06FF")
        return fixed if ar >= max(1, len(fixed)) * 0.2 else s
    except Exception:
        return s

# يلتقط السلاسل النصية في بايثون (بسيط وكافي لحالتنا)
STR = re.compile(r"([rubfRUBF]*)(['\\"])((?:\\.|(?!\2).)*)\2", re.S)

def fix_py(txt: str) -> str:
    def rep(m):
        p, q, body = m.groups()
        new_body = unmoji(body) if looks_moji(body) else body
        # اهرب نفس علامة الاقتباس داخل النص
        escaped = new_body.replace(q, "\\" + q)
        return p + q + escaped + q
    return STR.sub(rep, txt)

def process(p: pathlib.Path) -> bool:
    src = p.read_text(encoding="utf-8", errors="ignore")
    new = src
    if p.suffix == ".py":
        new = fix_py(src)
    elif p.suffix == ".json":
        new = unmoji(src)
    else:
        return False
    if new != src:
        p.write_text(new, encoding="utf-8", newline="")
        return True
    return False

changed = 0
skip = {".git", ".venv", "venv", "__pycache__", "node_modules"}
for r, ds, fs in os.walk("."):
    ds[:] = [d for d in ds if d not in skip]
    for f in fs:
        if f.endswith((".py", ".json")):
            p = pathlib.Path(r) / f
            if process(p):
                changed += 1

print(f"[mojibake-fix] changed {changed} file(s)")
