import re
import shutil
from pathlib import Path

# المسار إلى ملف inline.py
file_path = Path("keyboards/inline.py")

# إنشاء نسخة احتياطية
backup_path = file_path.with_suffix(".bak")
shutil.copy2(file_path, backup_path)
print(f"✅ Backup created: {backup_path}")

# قراءة المحتوى
with open(file_path, "r", encoding="utf-8") as f:
    content = f.readlines()

# حذف أي سطر فيه vip (حساسية صغيرة للحروف)
pattern = re.compile(r"vip", re.IGNORECASE)
cleaned_lines = [line for line in content if not pattern.search(line)]

# حفظ الملف بعد التنظيف
with open(file_path, "w", encoding="utf-8") as f:
    f.writelines(cleaned_lines)

print(f"✅ VIP code removed from {file_path}")
