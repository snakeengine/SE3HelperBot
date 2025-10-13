import pathlib, re

ROOT = pathlib.Path(".")

# 1) handlers/promoter_panel.py   بدّل السطر الذي يضيف روابط القائمة
pp = ROOT/"handlers"/"promoter_panel.py"
if pp.exists():
    txt = pp.read_text(encoding="utf-8", errors="ignore")
    # أصلح الموجيبايك للرصاصة والشرطة الطويلة
    txt = txt.replace("â", "").replace("â", "")
    # صحّح بناء وتهريب الـ <a href="..">..</a>
    txt = re.sub(
        r'f"â <a href=\\\"{s}\\\">{s}</a>"',
        'f\' <a href="{s}">{s}</a>\'',
        txt
    )
    # احتياط: أي href=\"  -> href="  (فقط داخل تاغات <a ...>)
    txt = re.sub(r'(<a href=)\\\"', r'\1"', txt)
    txt = txt.replace('\\">', '">')
    pp.write_text(txt, encoding="utf-8")

# 2) admin/vip_manager.py و vip_manager.backup.py  صيغة صف الـ VIP
for p in [ROOT/"admin"/"vip_manager.py", ROOT/"admin"/"vip_manager.backup.py"]:
    if p.exists():
        t = p.read_text(encoding="utf-8", errors="ignore")
        t = t.replace("â", "").replace("â", "")
        t = t.replace(
            'return f"â <code>{app}</code> â UID <a href=\\"tg://user?id={uid}\\">{uid}</a> ({adder_s}, exp:{exp_s})"',
            "return f' <code>{app}</code>  UID <a href=\"tg://user?id={uid}\">{uid}</a> ({adder_s}, exp:{exp_s})'"
        )
        # احتياط: unescape href
        t = t.replace('href=\\"tg://', 'href="tg://').replace('\\">', '">')
        p.write_text(t, encoding="utf-8")

# 3) rewards_gate.py  احذف U+00AD لو موجودة
rg = ROOT/"handlers"/"rewards_gate.py"
if rg.exists():
    t = rg.read_text(encoding="utf-8", errors="ignore")
    t = t.replace("\u00ad", "")  # SOFT HYPHEN
    rg.write_text(t, encoding="utf-8")

# 4) احذف U+00AD من كل الملفات .py كتنظيف عام
for p in ROOT.rglob("*.py"):
    if any(seg in p.parts for seg in (".venv","venv","__pycache__")):
        continue
    t = p.read_text(encoding="utf-8", errors="ignore")
    nt = t.replace("\u00ad", "")
    if nt != t:
        p.write_text(nt, encoding="utf-8")

print("[patch] done")
