"""
build_ter_facts.py — يشتغل مرتين بالسنة تلقائياً عبر GitHub Actions
(.github/workflows/build-ter-facts.yml) — بدون أي تدخل يدوي.

TER إله سكربت منفصل عن باقي الحقول "الثابتة" (build_stable_facts.py)
لأنو بيتحدّث أسرع شوي منهم (تخفيضات رسوم عند المزوّدين بمناسبات) —
فبنفحصه كل 6 أشهر بدل مرة/سنة بس.

منطق الاختيار (نفس المنطق يلي كان live بـetfdb-proxy.php قبل):
  - لو الاثنين (albertored وjustETF) متوفرين وفيه فرق جوهري بينهم
    (أكتر من 20% نسبياً)، نفضّل justETF (عادة أدق/أحدث لهالحقل).
  - غير هيك، نفضّل albertored، وjustETF كاحتياط لو albertored ناقص.
"""
import json
import urllib.request
from pathlib import Path

ETFDB_ETFS_URL = "https://raw.githubusercontent.com/albertored/etfdb/main/json/etfs.json"
ISINS_FILE = Path(__file__).parent / "isins.txt"
JUSTETF_SNAPSHOT_FILE = Path(__file__).parent / "justetf_snapshot.json"
OUTPUT_FILE = Path(__file__).parent / "ter_facts.json"


def fetch_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "estismar.de ter-facts builder"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_isins():
    if not ISINS_FILE.exists():
        print(f"⚠️ {ISINS_FILE} غير موجود")
        return []
    isins = []
    for line in ISINS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        isins.append(line.split()[0].upper())
    return sorted(set(isins))


def pick_ter(a, b):
    """a = albertored, b = justETF. يرجع (القيمة, هل استخدمنا justETF)."""
    try:
        af = float(a) if a not in (None, "") else None
    except (TypeError, ValueError):
        af = None
    try:
        bf = float(b) if b not in (None, "") else None
    except (TypeError, ValueError):
        bf = None

    if af is not None and bf is not None:
        if af > 0 and abs(af - bf) / af > 0.20:
            return bf, True
        return af, False
    if af is not None:
        return af, False
    if bf is not None:
        return bf, True
    return None, False


def main():
    isins = load_isins()
    if not isins:
        print("ما في أي ISIN — تأكد من isins.txt")
        return

    print("جلب albertored/etfdb...")
    try:
        etfdb_list = fetch_json(ETFDB_ETFS_URL)
        etfdb_index = {f["isin"].upper(): f for f in etfdb_list if f.get("isin")}
        print(f"  {len(etfdb_index)} صندوق")
    except Exception as e:
        print(f"⚠️ فشل جلب albertored ({e}) — رح نكمل بـjustETF بس")
        etfdb_index = {}

    j_funds = {}
    if JUSTETF_SNAPSHOT_FILE.exists():
        try:
            snap = json.loads(JUSTETF_SNAPSHOT_FILE.read_text(encoding="utf-8"))
            j_funds = snap.get("funds", {})
        except Exception as e:
            print(f"⚠️ فشل قراءة justetf_snapshot.json ({e})")

    if not etfdb_index and not j_funds:
        print("✗ ولا مصدر متوفر — توقف بدون كتابة ملف")
        return

    facts = {}
    missing = []
    used_justetf_count = 0
    for isin in isins:
        fund = etfdb_index.get(isin)
        jfund = j_funds.get(isin)
        ter, used_justetf = pick_ter((fund or {}).get("ter"), (jfund or {}).get("ter"))
        if ter is None:
            missing.append(isin)
            continue
        facts[isin] = {"ter": ter, "source": "justETF" if used_justetf else "albertored"}
        if used_justetf:
            used_justetf_count += 1

    import datetime
    output = {
        "generatedAt": datetime.date.today().isoformat(),
        "count": len(facts),
        "missing": missing,
        "facts": facts,
    }
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=None), encoding="utf-8")
    print(f"\n✓ انكتب ter_facts.json — {len(facts)} صندوق من أصل {len(isins)} "
          f"({used_justetf_count} منهم من justETF بسبب فرق جوهري أو نقص بـalbertored)")
    if missing:
        print(f"⚠️ {len(missing)} صندوق ما لقينالهم TER بأي مصدر: {', '.join(missing)}")


if __name__ == "__main__":
    main()
