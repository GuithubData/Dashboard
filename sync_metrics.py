"""
sync_metrics.py — يجيب مؤشرات الأداء (عائد/تقلب/أقصى تراجع) لكل صندوق
بلائحة ids.txt من justETF عبر justetf_scraping.load_overview()، ويخزنها بملف
metrics.json (نفس مجلد dataset_b.json).

بعكس sync_dataset_b.py (يلي بيجيب صندوق-صندوق بدفعات لأنو get_etf_overview بيسوي طلب
لكل ISIN لحاله)، هون load_overview() بترجع كل صناديق justETF (~4000) بنداء واحد بس —
فما في داعي لتقسيم بالدفعات، وهاد السكربت بيشتغل بمرة وحدة كل أسبوع لكل ids.txt.

الاستخدام: نفس طريقة sync_dataset_b.py — يشتغل من GitHub Action، يقرأ ids.txt،
ويكتب/يحدّث metrics.json بنفس المجلد (commit تلقائي بنفس الـ workflow).
"""
import json
import sys
from pathlib import Path

import justetf_scraping

IDS_FILE = Path("ids.txt")
OUTPUT_FILE = Path("metrics.json")

# أعمدة الأداء يلي بدنا ناخدها من جدول overview الكامل (42 عمود) — أي عمود اسمه فيه
# return أو volatility أو drawdown. باقي الأعمدة (info أساسية متل الاسم/TER) موجودة
# أصلاً بمصادر تانية (etfdb-proxy) فما داعي نكررها هون.
KEEP_SUBSTR = ("return", "volatility", "drawdown", "dividend", "yield")


def main():
    if not IDS_FILE.exists():
        print("ids.txt غير موجود — بوقف.")
        sys.exit(1)

    # ⚠️ إصلاح: كنا ناخد السطر كامل (بما فيه التعليقات inline بـ #) كـISIN — هيك كل
    # ISIN كان عملياً بيفشل يطابق df.index (0 صندوق تحديث دايماً). هلق منتجاهل أي سطر
    # تعليق بالكامل (يبلش بـ#)، ومنقص أي تعليق inline بعد الـISIN، بنفس منطق
    # update_profile.py's load_isins().
    isins = set()
    for line in IDS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        code = line.split("#", 1)[0].strip()  # نحذف أي تعليق inline بعد الـISIN
        if not code:
            continue
        isins.add(code.split()[0].upper())

    if not isins:
        print("ids.txt فاضي — بوقف.")
        sys.exit(1)

    print(f"قرأنا {len(isins)} ISIN من ids.txt")
    print("جاري تحميل overview الكامل من justETF (كل الصناديق، نداء واحد)...")
    df = justetf_scraping.load_overview()
    df.index = df.index.astype(str).str.upper()

    perf_cols = [c for c in df.columns if any(s in c for s in KEEP_SUBSTR)]
    print(f"أعمدة الأداء المكتشفة ({len(perf_cols)}): {perf_cols}")
    if not perf_cols:
        print("⚠️ ما لقيت أي عمود أداء بالجدول — تأكد إنو overview لسا بيرجع نفس الأعمدة الموثقة.")

    existing = {}
    if OUTPUT_FILE.exists():
        try:
            existing = json.loads(OUTPUT_FILE.read_text())
        except Exception:
            existing = {}

    updated, missing = 0, []
    for isin in isins:
        if isin not in df.index:
            missing.append(isin)
            continue
        row = df.loc[isin]
        record = {}
        for c in perf_cols:
            v = row[c]
            try:
                record[c] = None if (v is None or v != v) else float(v)  # v!=v => NaN
            except Exception:
                record[c] = None
        existing[isin] = record
        updated += 1

    OUTPUT_FILE.write_text(json.dumps(existing, ensure_ascii=False))
    print(f"تحديث {updated} صندوق بنجاح.")
    if missing:
        print(f"مفقودين من overview justETF ({len(missing)}): {', '.join(sorted(missing)[:30])}"
              + (" ..." if len(missing) > 30 else ""))


if __name__ == "__main__":
    main()
