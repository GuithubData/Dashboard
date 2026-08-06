"""
translate_descriptions.py — يترجم الوصف (description) الإنجليزي الموجود أصلاً
بـ justetf_snapshot.json (يلي scrape_justetf.py بيجيبه أصلاً من overview.get("description"))
للعربي، ويخزن الترجمة بس بملف justetf_descriptions_ar.json — بدون أي جلب جديد من justETF
(ما في داعي، الوصف الإنجليزي موجود أصلاً بالـ snapshot).

⚠️ لازم يشتغل بعد scrape_justetf.py (بنفس الـ workflow، كخطوة تالية له) عشان يلاقي
أحدث نسخة من justetf_snapshot.json.

يترجم بس الصناديق الجديدة (مالها ترجمة محفوظة أصلاً) أو يلي تغيّر وصفهم الإنجليزي —
فما بيعيد ترجمة كل شي من الصفر كل أسبوع (يوفر وقت وطلبات ترجمة).

التثبيت المطلوب (ضيفه لخطوة "Install dependencies" بالـ workflow):
    pip install deep-translator
"""
import json
import time
from pathlib import Path

from deep_translator import GoogleTranslator

SNAPSHOT_FILE = Path("justetf_snapshot.json")
OUTPUT_FILE = Path("justetf_descriptions_ar.json")
REQUEST_DELAY = 0.8


def translate_to_arabic(text):
    if not text or not text.strip():
        return None
    try:
        return GoogleTranslator(source="en", target="ar").translate(text[:4900])
    except Exception as e:
        print(f"  ⚠ فشلت الترجمة: {e}")
        return None


def main():
    if not SNAPSHOT_FILE.exists():
        print("justetf_snapshot.json غير موجود — شغّل scrape_justetf.py الأول.")
        return

    snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    funds = snapshot.get("funds", {}) if isinstance(snapshot, dict) else {}
    print(f"صناديق بالـ snapshot: {len(funds)}")

    existing = {}
    if OUTPUT_FILE.exists():
        try:
            existing = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    translated, skipped, no_desc = 0, 0, 0
    for isin, fund in funds.items():
        desc_en = (fund or {}).get("description")
        if not desc_en:
            no_desc += 1
            continue

        prev = existing.get(isin)
        # ترجم بس لو مافي ترجمة محفوظة أصلاً، أو النص الإنجليزي تغيّر عن آخر مرة ترجمناه
        if prev and prev.get("source_en") == desc_en and prev.get("ar"):
            skipped += 1
            continue

        ar = translate_to_arabic(desc_en)
        existing[isin] = {"source_en": desc_en, "ar": ar}
        if ar:
            translated += 1
            print(f"✓ {isin} → تُرجم")
        else:
            print(f"~ {isin} → فشلت الترجمة، رح تنعاد المحاولة المرة الجاية")

        OUTPUT_FILE.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
        time.sleep(REQUEST_DELAY)

    print("")
    print(f"تُرجم حديثاً: {translated} | محفوظ أصلاً (تُخطّى): {skipped} | بدون وصف إنجليزي أصلاً: {no_desc}")


if __name__ == "__main__":
    main()
