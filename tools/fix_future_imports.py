import os, io, re, sys

TRI = ("\\"\\"\\"", "'''")

def split_header(text: str):
    """يرجع (prefix, rest) حيث prefix يشمل shebang/encoding + docstring لو وُجد."""
    lines = text.splitlines(keepends=True)
    i = 0
    # shebang أو سطر ترميز
    while i < len(lines) and (lines[i].startswith("#!") or re.match(rb"coding[:=]\s*[-\w.]+".decode(), lines[i])):
        i += 1
    # docstring أول الملف
    if i < len(lines):
        line = lines[i].lstrip()
        for q in TRI:
            if line.startswith(q):
                j = i
                # ابحث عن نهاية الdocstring
                i += 1
                while i < len(lines):
                    if q in lines[i]:
                        i += 1
                        break
                    i += 1
                break
    return "".join(lines[:i]), "".join(lines[i:])

FUTURE_RE = re.compile(r"^\s*from\s+__future__\s+import\s+([^\n#]+)", re.M)

def process_file(path):
    with io.open(path, "r", encoding="utf-8") as f:
        src = f.read()

    prefix, rest = split_header(src)

    # استخرج أسطر future من كل الملف
    futures = FUTURE_RE.findall(rest)
    if not futures and not FUTURE_RE.search(prefix):
        return False  # لا شيء نصلّحه

    # اجمع جميع الاستيرادات (بما فيها الموجودة أصلًا في الـprefix)
    all_future = []
    for m in FUTURE_RE.findall(prefix):
        all_future.append(m)
    for m in futures:
        all_future.append(m)

    # وحّدها
    items = []
    for chunk in all_future:
        for name in [x.strip() for x in chunk.split(",")]:
            if name and name not in items:
                items.append(name)

    # احذف كل أسطر future من النص
    new_rest = FUTURE_RE.sub("", rest)
    new_prefix = FUTURE_RE.sub("", prefix)

    # ابني سطر future موحّد
    future_line = ""
    if items:
        future_line = f"from __future__ import {', '.join(items)}\n"

    # تأكد من وجود سطر فارغ بعد الـprefix إذا لزم
    if new_prefix and not new_prefix.endswith("\n"):
        new_prefix += "\n"

    # أدخل future بعد الprefix مباشرة
    new_src = new_prefix + future_line + ("\n" if future_line and not new_rest.startswith("\n") else "") + new_rest

    if new_src != src:
        with io.open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new_src)
        return True
    return False

changed = 0
for root, _, files in os.walk("."):
    if any(p in root.replace("\\","/") for p in ("/.git", "/.venv", "/venv", "/node_modules", "/__pycache__")):
        continue
    for name in files:
        if name.endswith(".py"):
            p = os.path.join(root, name)
            if process_file(p):
                changed += 1

print(f"[fix] moved __future__ imports in {changed} file(s)")
