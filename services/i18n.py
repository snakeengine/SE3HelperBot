# services/i18n.py
import json, os
from pathlib import Path

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
LANG_PATH = DATA_DIR / "user_lang.json"

_STRINGS = {
    "shop_title": {"ar": "🛒 المتجر — اختر اللعبة:", "en": "🛒 Shop — choose a game:"},
    "choose_plan": {"ar": "⏳ اختر المدة:", "en": "⏳ Choose duration:"},
    "choose_qty": {"ar": "🔢 اختر الكمية:", "en": "🔢 Choose quantity:"},
    "back": {"ar": "⬅️ رجوع", "en": "⬅️ Back"},
    "pay_now": {"ar": "✅ ادفع الآن", "en": "✅ Pay now"},
    "i_paid": {"ar": "👀 تم الدفع", "en": "👀 I paid"},
    "order_created": {"ar": "🧾 *تم إنشاء طلبك*", "en": "🧾 *Your order has been created*"},
    "order_no": {"ar": "رقم الطلب", "en": "Order #"},
    "confirm_text": {
        "ar": "📦 تأكيد الطلب:\n- اللعبة: {game}\n- المدة: {days} يوم\n- الكمية: {qty}\n- السعر الإجمالي: ${total}\n\nاضغط (ادفع الآن) لإنشاء طلب الدفع.",
        "en": "📦 Confirm order:\n- Game: {game}\n- Duration: {days} days\n- Quantity: {qty}\n- Total: ${total}\n\nPress (Pay now) to create the payment."
    },
    "paid_wait": {
        "ar": "✅ تم استلام تأكيدك لطلب `{order_id}`.\nسنراجع التحويل سريعًا، وستصلك المفاتيح هنا.",
        "en": "✅ We received your confirmation for `{order_id}`.\nWe’ll verify the transfer shortly; keys will arrive here."
    },
    "howto_keys": {
        "ar": "ℹ️ **طريقة تفعيل المفتاح**\n1) افتح تطبيق محرك الثعبان.\n2) من أعلى التطبيق افتح \"حول التطبيق\".\n3) اضغط **entry Key**.\n4) الصق المفتاح واضغط **Activate**.\n💡 يبدأ العدّ عند التفعيل. المفتاح يُستخدم مرة واحدة.",
        "en": "ℹ️ **How to activate**\n1) Open Snake Engine app.\n2) Open “About app”.\n3) Tap **entry Key**.\n4) Paste the key then **Activate**.\n💡 Time starts at activation. One-time key."
    },
    "profile_empty": {"ar": "لا توجد مفاتيح مشتراة بعد.", "en": "No purchased keys yet."},
    "profile_title": {"ar": "👤 *ملفي* — مفاتيح تم تسليمها:", "en": "👤 *My Profile* — delivered keys:"},
    "lang_set": {"ar": "تم ضبط اللغة: عربي", "en": "Language set: English"},
    "btn_lang_ar": {"ar": "🇸🇦 العربية", "en": "🇸🇦 Arabic"},
    "btn_lang_en": {"ar": "🇬🇧 English", "en": "🇬🇧 English"},
    "choose_lang": {"ar": "اختر لغتك:", "en": "Choose your language:"},
    "pay_instructions_prefix": {
        "ar": "ادفع باستخدام Binance Pay عبر الرابط أدناه:",
        "en": "Pay with Binance Pay using the link below:"
    },
    "admin_new_order": {
        "ar": "🆕 طلب جديد *{oid}*\nالمشتري: `{uid}`\nاللعبة: {game} | المدة: {days} | الكمية: {qty}\nالإجمالي: ${total}",
        "en": "🆕 New order *{oid}*\nBuyer: `{uid}`\nGame: {game} | Days: {days} | Qty: {qty}\nTotal: ${total}"
    },
    "admin_approved": {"ar": "✅ تمت الموافقة وتسليم مفاتيح لطلب {oid}.", "en": "✅ Approved and delivered for {oid}."},
    "admin_rejected": {"ar": "❌ تم رفض الطلب {oid}.", "en": "❌ Order {oid} rejected."},
    "not_enough_stock": {"ar": "المخزون غير كافٍ! أضف مفاتيح أولاً.", "en": "Not enough stock! Add keys first."},
}

def _load_all():
    if not LANG_PATH.exists():
        LANG_PATH.write_text("{}", encoding="utf-8")
        return {}
    try:
        import json
        return json.loads(LANG_PATH.read_text("utf-8"))
    except:
        return {}

def set_lang(user_id: int, lang: str):
    data = _load_all()
    data[str(user_id)] = lang
    LANG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def get_lang(user_id: int, fallback: str = "ar") -> str:
    data = _load_all()
    return data.get(str(user_id)) or fallback

def t(key: str, lang: str, **fmt) -> str:
    pack = _STRINGS.get(key, {})
    base = pack.get(lang) or pack.get("en") or key
    if fmt:
        try:
            return base.format(**fmt)
        except:
            return base
    return base
