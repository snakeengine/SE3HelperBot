import re, pathlib

p = pathlib.Path("handlers/promoter_panel.py")
t = p.read_text(encoding="utf-8", errors="ignore")

# نظّف الموجيبايك والشرطة الطويلة والرصاصة
t = t.replace("â", "").replace("", "").replace("â", "").replace("\u00ad","")

# استبدل السطر المعطوب بالكامل بصيغة سليمة
# نحافظ على المسافة البادئة (indent)
pat = re.compile(r'(\s*)if s\.startswith\(\("http://","https://","tg://"\)\):[^\n]*')
rep = r"\1if s.startswith((\"http://\",\"https://\",\"tg://\")):\n\1    out.append(f' <a href=\"{s}\">{s}</a>')"
t_new = pat.sub(rep, t)

# زيادة: فكّ أي href=\"...\" المتبقية داخل <a ...>
t_new = re.sub(r'(<a href=)\\\"', r'\1\"', t_new)
t_new = t_new.replace('\\">', '">')

if t_new != t:
    p.write_text(t_new, encoding="utf-8", newline="")
    print("[patch] promoter_panel.py fixed")
else:
    print("[patch] nothing changed (already fixed)")
