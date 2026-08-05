"""
scrape_justetf.py — Layer 2 (بعد albertored/etfdb) لداشبورد estismar.de

بيقرأ قائمة ISINs من isins.txt (سطر لكل صندوق — موسّعة يدوياً من أول 6
صفحات فلتر أسهم justETF + eu-us-mapping.json الأصلي)، وبيسحب لكل واحد
get_etf_overview() الكامل من مكتبة druzsan/justetf-scraping، وبيحفظ
النتيجة بملف واحد justetf_snapshot.json — هاد الملف يلي بيقراه
etfdb-proxy.php (خام عبر raw.githubusercontent.com) كطبقة احتياط
تانية بعد albertored/etfdb.

يشتغل شهرياً عبر GitHub Actions (.github/workflows/scrape-justetf.yml)
— مش على استضافة estismar.de نفسها، لأنو هاي مكتبة Python والاستضافة
PHP بس.

⚠️ إضافة صندوق جديد للتغطية: زيد سطر ISIN جديد بـ isins.txt وادفع
(commit) — أول تشغيل جاي رح يضيفه تلقائياً.
"""
import dataclasses
import datetime
import json
import sys
import time
import traceback
from pathlib import Path

import justetf_scraping

ISINS_FILE = Path(__file__).parent / "isins.txt"
OUTPUT_FILE = Path(__file__).parent / "justetf_snapshot.json"

# فسحة بين كل صندوق وتاني حتى ما نرهق justETF بطلبات متتالية ضخمة
SLEEP_BETWEEN = 2.5


def load_isins():
    if not ISINS_FILE.exists():
        print(f"⚠️ {ISINS_FILE} غير موجود — بلّش بإنشائه (سطر ISIN لكل صندوق).")
        return []
    lines = ISINS_FILE.read_text(encoding="utf-8").splitlines()
    isins = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        isins.append(line.split()[0].upper())  # يسمح بتعليق بعد الـ ISIN بنفس السطر
    return sorted(set(isins))


def jsonable_quote(quote):
    """يحوّل كائن Quote (dataclass فيه datetime) لقاموس عادي قابل لـ json.dumps."""
    if quote is None:
        return None
    if dataclasses.is_dataclass(quote):
        d = dataclasses.asdict(quote)
    elif hasattr(quote, "_asdict"):  # namedtuple احتياطي
        d = dict(quote._asdict())
    elif hasattr(quote, "__dict__"):
        d = dict(vars(quote))
    else:
        return str(quote)
    for k, v in d.items():
        if isinstance(v, (datetime.datetime, datetime.date)):
            d[k] = v.isoformat()
    return d


def scrape_one(isin):
    overview = justetf_scraping.get_etf_overview(isin)
    return {
        "isin": overview.get("isin", isin),
        "name": overview.get("name"),
        "description": overview.get("description"),
        "index": overview.get("index"),
        "ter": overview.get("ter"),
        "fundSizeEur": overview.get("fund_size_eur"),
        "replication": overview.get("replication"),
        "fundCurrency": overview.get("fund_currency"),
        "distributionPolicy": overview.get("distribution_policy"),
        "inceptionDate": overview.get("inception_date"),
        "fundDomicile": overview.get("fund_domicile"),
        "countries": [
            {"country": c.get("name"), "pct": c.get("percentage")}
            for c in (overview.get("countries") or [])
        ],
        "sectors": [
            {"sector": s.get("name"), "pct": s.get("percentage")}
            for s in (overview.get("sectors") or [])
        ],
        "topHoldings": [
            {"name": h.get("name"), "isin": h.get("isin"), "pct": h.get("percentage")}
            for h in (overview.get("top_holdings") or [])
        ],
        "gettexQuote": jsonable_quote(overview.get("gettex")),
    }


def main():
    isins = load_isins()
    if not isins:
        print("ما في أي ISIN لسحبه — تأكد من isins.txt")
        sys.exit(1)

    print(f"=== بدء سحب {len(isins)} صندوق من justETF ===")
    results = {}
    failed = []

    for i, isin in enumerate(isins, 1):
        print(f"[{i}/{len(isins)}] {isin} ... ", end="", flush=True)
        try:
            data = scrape_one(isin)
            results[isin] = data
            print("تم ✓")
        except Exception as e:
            failed.append(isin)
            print(f"فشل ({e})")
            traceback.print_exc(file=sys.stdout)
        time.sleep(SLEEP_BETWEEN)

    snapshot = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(results),
        "failed": failed,
        "funds": results,
    }
    OUTPUT_FILE.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=None), encoding="utf-8"
    )
    print(f"=== خلصنا: {len(results)} نجح، {len(failed)} فشل ===")
    if failed:
        print("الصناديق يلي فشلوا:", ", ".join(failed))


if __name__ == "__main__":
    main()
