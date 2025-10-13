import os, io, re, json, pathlib

# حروف الموجيبِيك الشائعة
MOJI_CHARS = set("ØÙÛÜÃÂÊËäâæçéèûï’œœâ")

def looks_mojibake(s: str) -> bool:
    return any(ch in MOJI_CHARS for ch in s)

def de_mojibake(s: str) -> str:
    try:
        # اعتبر النص اتفَسَّر Latin-1 وهو أصلاً UTF-8
        fixed = bytes(s, "latin-1").decode("utf-8")
        # تأكد أن الناتج عربي بمعظمه
        arabic_ratio = sum(1 for ch in fixed if "\u0600" <= ch <= "\u06FF") / max(1, len(fixed))
        return fixed if arabic_ratio >= 0.2 else s
    except Exception:
        return s

STR_RE = re.compile(r"([rubfRUBF]*)(['\"])((?:\\.|(?!\2).)*)\2", re.S)

def fix_text_literals(text: str) -> str:
    def repl(m):
        prefix, quote, body = m.groups()
        new_body = de_mojibake(body) if looks_mojibake(body) else body
        return f"{prefix}{quote}{new_body.replace(quote, '\\\\'+quote)}{quote}"
    return STR_RE.sub(repl, text)

def process_text_file(path: pathlib.Path) -> bool:
    src = path.read_text(encoding="utf-8", errors="ignore")
    new = src
    if path.suffix == ".py":
        new = fix_text_literals(src)
    elif path.suffix == ".json":
        try:
            obj = json.loads(src)
            dumped = json.dumps(json.loads(bytes(json.dumps(obj), "utf-8").decode("utf-8")), ensure_ascii=False)
            # جرّب إصلاح الموجيبيك داخل النص الكامل كحل بسيط
            dumped = de_mojibake(dumped)
            new = json.dumps(json.loads(dumped), ensure_ascii=False, indent=2)
        except Exception:
            # fallback: إصلاح نصّي عام
            new = de_mojibake(src)
    else:
        return False

    if new != src:
        path.write_text(new, encoding="utf-8", newline="")
        return True
    return False

changed = 0
skip_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules"}
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in skip_dirs]
    for name in files:
        p = pathlib.Path(root) / name
        if p.suffix in {".py", ".json"}:
            if process_text_file(p):
                changed += 1

print(f"[mojibake-fix] changed {changed} file(s)")
