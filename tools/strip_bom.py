import os, io, sys

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules"}

def should_skip(path):
    parts = set(os.path.normpath(path).split(os.sep))
    return bool(SKIP_DIRS & parts)

def strip_bom_everywhere(text: str) -> str:
    # أزل U+FEFF من البداية وأي مواضع أخرى
    return text.replace("\ufeff", "")

changed = 0
for root, _, files in os.walk("."):
    if should_skip(root):
        continue
    for name in files:
        if not name.endswith(".py"):
            continue
        p = os.path.join(root, name)
        with open(p, "rb") as f:
            raw = f.read()
        new_raw = raw
        # أزل BOM في الرأس (UTF-8)
        if new_raw.startswith(b"\xef\xbb\xbf"):
            new_raw = new_raw[len(b"\xef\xbb\xbf"):]
        try:
            s = new_raw.decode("utf-8")
        except UnicodeDecodeError:
            # خلّيه كما هو لو مو UTF-8
            continue
        s2 = strip_bom_everywhere(s)
        if s2 != s or new_raw != raw:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(s2)
            changed += 1

print(f"[clean] removed BOM/FEFF in {changed} file(s)")
