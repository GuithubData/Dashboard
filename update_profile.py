"""
update_profile.py — يشتغل مرة/سنة تلقائياً عبر GitHub Actions
(.github/workflows/profile-refresh.yml) — بدون أي تدخل يدوي.

الفكرة: 7 حقول بمعلومات الصندوق (النوع/asset_class، طريقة التكرار،
توزيع الأرباح، تاريخ التأسيس، مكان التسجيل، صندوق إسلامي، الوضع
الضريبي بألمانيا) ما بتتغيّر عملياً إلا نادراً جداً — فما داعي نعتمد
على albertored/justETF الحيّين لهالحقول بكل طلب على الموقع.

⚠️ TER مش هون — إلو سكربت وworkflow منفصلين (build_ter_facts.py،
كل 6 أشهر) لأنو بيتحدّث أسرع شوي من باقي الحقول (تخفيضات رسوم
المزوّدين بمناسبات).

هاد السكربت بيسحب:
  1. albertored/etfdb (etfs.json كامل) — نفس مصدر الطبقة الأولى
  2. dataset_b.json المتراكم بنفس هالريبو (ناتج sync_dataset_b.py)
ويحسب الحقول السبعة لكل ISIN موجود بـ ids.txt، ويكتبهم لملف
profile.json — يلي الـ workflow بيعمله commit تلقائياً،
وdata-proxy.php عالموقع بيسحبه من GitHub raw (نفس نمط dataset_b).
"""
import json
import urllib.request
from pathlib import Path

ETFDB_ETFS_URL = "https://raw.githubusercontent.com/albertored/etfdb/main/json/etfs.json"
IDS_FILE = Path(__file__).parent / "ids.txt"
DATASET_B_FILE = Path(__file__).parent / "dataset_b.json"  # نفس الملف يلي sync_dataset_b.py بيبنيه بهالريبو
OUTPUT_FILE = Path(__file__).parent / "profile.json"


def fetch_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "estismar.de stable-facts builder"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_isins():
    if not IDS_FILE.exists():
        print(f"⚠️ {IDS_FILE} غير موجود")
        return []
    isins = []
    for line in IDS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        isins.append(line.split()[0].upper())
    return sorted(set(isins))


def pick(a, b):
    return a if (a is not None and a != "") else b


def main():
    isins = load_isins()
    if not isins:
        print("ما في أي ISIN — تأكد من ids.txt")
        return

    print("جلب albertored/etfdb...")
    try:
        etfdb_list = fetch_json(ETFDB_ETFS_URL)
        etfdb_index = {f["isin"].upper(): f for f in etfdb_list if f.get("isin")}
        print(f"  {len(etfdb_index)} صندوق")
    except Exception as e:
        print(f"⚠️ فشل جلب albertored ({e}) — رح نكمل بـjustETF بس")
        etfdb_index = {}

    print("قراءة dataset_b.json المحلي (نفس الريبو)...")
    j_funds = {}
    if DATASET_B_FILE.exists():
        try:
            snap = json.loads(DATASET_B_FILE.read_text(encoding="utf-8"))
            j_funds = snap.get("funds", {})
            print(f"  {len(j_funds)} صندوق")
        except Exception as e:
            print(f"⚠️ فشل قراءة dataset_b.json ({e})")

    if not etfdb_index and not j_funds:
        print("✗ ولا مصدر متوفر — توقف بدون كتابة ملف (نحافظ على النسخة القديمة إن وجدت)")
        return

    facts = {}
    missing = []
    for isin in isins:
        fund = etfdb_index.get(isin)
        jfund = j_funds.get(isin)
        if fund is None and jfund is None:
            missing.append(isin)
            continue

        name = pick((fund or {}).get("name"), (jfund or {}).get("name")) or ""
        is_islamic = "islamic" in name.lower()

        facts[isin] = {
            "name": name,
            "assetClass": (fund or {}).get("asset_class"),
            "replication": pick((fund or {}).get("replication"), (jfund or {}).get("replication")),
            "dividends": pick((fund or {}).get("dividends"), (jfund or {}).get("distributionPolicy")),
            "inceptionDate": pick((fund or {}).get("inception_date"), (jfund or {}).get("inceptionDate")),
            "domicileCountry": pick((fund or {}).get("domicile_country"), (jfund or {}).get("fundDomicile")),
            "isIslamic": is_islamic,
            "taxStatusDE": ((jfund or {}).get("taxStatus") or {}).get("Germany"),
        }

    import datetime
    output = {
        "generatedAt": datetime.date.today().isoformat(),
        "count": len(facts),
        "missing": missing,
        "facts": facts,
    }
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=None), encoding="utf-8")
    print(f"\n✓ انكتب profile.json — {len(facts)} صندوق من أصل {len(isins)}")
    if missing:
        print(f"⚠️ {len(missing)} صندوق ما لقينالهم بيانات: {', '.join(missing)}")


if __name__ == "__main__":
    main()
