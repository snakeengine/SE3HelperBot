# constants.py
import os

# المنتج ثابت: SEVIP
PRODUCT_NAME = "SEVIP"

# اللعبة المدعومة حالياً
DEFAULT_GAME_SLUG = "8bp"

# العتبة التي نبدأ عندها بتنبيه انخفاض المخزون
STOCK_THRESHOLD = int(os.getenv("STOCK_THRESHOLD", "3"))

# الأسعار الافتراضية (يمكن تعديلها من env عبر handlers.shop.py)
PRICE_USD_3  = float(os.getenv("PRICE_USD_3",  "5"))
PRICE_USD_10 = float(os.getenv("PRICE_USD_10", "13"))
PRICE_USD_30 = float(os.getenv("PRICE_USD_30", "28"))
