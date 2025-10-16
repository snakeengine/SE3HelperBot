import importlib
m = importlib.import_module('handlers.promoter')
UID = 7360982123  # غيّرها لو ودك
print("is_promoter =", m.is_promoter(UID))
print("users_in_store =", list(m._load_store().get("users", {}).keys())[:10])
