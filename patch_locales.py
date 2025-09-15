import json, io, os

def _read(path):
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def merge(path, patch):
    data = _read(path)
    added = 0
    for k, v in patch.items():
        if not isinstance(data.get(k), str) or not data.get(k).strip() or data.get(k) == k:
            data[k] = v
            added += 1
    _write(path, data)
    print(f"Patched {path} (+{added} keys)")

ar_patch = {
  "btn_sevip_buy": "شراء/تفعيل SEVIP",
  "btn_alerts_inbox": "صندوق الإشعارات",
  "btn_contact": "الدعم"
}

en_patch = {
  "btn_sevip_buy": "SEVIP Store",
  "btn_alerts_inbox": "Alerts Inbox",
  "btn_contact": "Contact"
}

merge("locales/ar.json", ar_patch)
merge("locales/en.json", en_patch)
