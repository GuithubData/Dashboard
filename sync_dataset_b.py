"""
sync_dataset_b.py — Layer 2 (بعد albertored/etfdb) لداشبورد estismar.de

بيقرأ قائمة ISINs من ids.txt (سطر لكل صندوق)، وبيقسّمها لدفعات
(BATCH_SIZE صندوق بكل دفعة)، وبكل تشغيلة أسبوعية بيسحب دفعة وحدة بس —
مش الـ169 كلهم دفعة وحدة. هيك كل صندوق بيتحدّث تقريباً مرة كل 4 أسابيع
(شهرياً تقريباً)، بس بضغط أقل بكتير بكل مرة وفرصة أقل للحظر.

النتيجة الجديدة بتنكتب فوق dataset_b.json الموجود بدمج (merge) —
مش استبدال كامل — يعني الصناديق يلي مش بدورهم هالأسبوع بضلوا محتفظين
ببياناتهم من آخر تحديث ليهم، وبس دفعة هالأسبوع بتتحدّث.

يشتغل أسبوعياً عبر GitHub Actions (.github/workflows/dataset-b-refresh.yml)
— مش على استضافة estismar.de نفسها، لأنو هاي مكتبة Python والاستضافة
PHP بس.

⚠️ إضافة صندوق جديد للتغطية: زيد سطر ISIN جديد بـ ids.txt وادفع
(commit) — بيتوزع تلقائياً على إحدى الدفعات بالتشغيلة الجاية.
"""
import dataclasses
import datetime
import json
import re
import sys
import time
import traceback
from pathlib import Path

import justetf_scraping
import requests
from bs4 import BeautifulSoup

IDS_FILE = Path(__file__).parent / "ids.txt"
OUTPUT_FILE = Path(__file__).parent / "dataset_b.json"

# فسحة بين كل صندوق وتاني
SLEEP_BETWEEN = 5.0

# لو صادفنا 403 (حظر مؤقت من justETF)، نستنى فترة طويلة قبل ما نكمل
COOLDOWN_ON_BLOCK = 90.0

# محاولات لكل صندوق (المحاولة الأولى + إعادة محاولات) قبل ما نعتبره فشل نهائي
MAX_ATTEMPTS = 2

# حجم كل دفعة أسبوعية — ~40 صندوق حسب طلبك
BATCH_SIZE = 40

# ═══ الوضع الضريبي (Tax status) — مش موجود بمكتبة justetf_scraping أصلاً،
# فبنسحبه يدوياً من نفس صفحة الملف الشخصي للصندوق على justETF (قسم
# #collapse-tax تحت تبويب Basics) ═══
JUSTETF_PROFILE_URL_TMPL = "https://www.justetf.com/en/etf-profile.html?isin={isin}"
TAX_REQUEST_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-GB,en;q=0.9",
}
TAX_REQUEST_TIMEOUT = 20


def get_this_weeks_batch(isins):
    """بيقسّم القائمة لدفعات بحجم BATCH_SIZE، وبيرجّع دفعة هالأسبوع —
    محسوبة تلقائياً من رقم الأسبوع بالسنة (ISO week)، فمافي حاجة لأي إعداد
    يدوي أو متغيّر خارجي. كل صندوق بيتحدّث تقريباً مرة كل عدد_الدفعات أسابيع."""
    num_batches = max(1, -(-len(isins) // BATCH_SIZE))  # تقريب لأعلى
    week_number = datetime.date.today().isocalendar()[1]
    batch_index = week_number % num_batches
    batch = isins[batch_index * BATCH_SIZE: (batch_index + 1) * BATCH_SIZE]
    print(f"مجموع الدفعات: {num_batches} (كل وحدة ~{BATCH_SIZE} صندوق) — "
          f"دفعة هالأسبوع (رقم {week_number}): دفعة #{batch_index} ({len(batch)} صندوق)")
    return batch


def load_existing_snapshot():
    if not OUTPUT_FILE.exists():
        return {}
    try:
        data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        return data.get("funds", {}) if isinstance(data, dict) else {}
    except Exception as e:
        print(f"⚠️ تعذّر قراءة snapshot سابق ({e}) — رح نبلّش من صفر")
        return {}


def load_isins():
    if not IDS_FILE.exists():
        print(f"⚠️ {IDS_FILE} غير موجود — بلّش بإنشائه (سطر ISIN لكل صندوق).")
        return []
    lines = IDS_FILE.read_text(encoding="utf-8").splitlines()
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


def scrape_tax_status(isin):
    """بيسحب قسم "Tax status" (#collapse-tax) من صفحة الملف الشخصي للصندوق
    على justETF مباشرة (مش عبر مكتبة justetf_scraping، لأنها ما بتغطي هاد
    الحقل). بيرجّع قاموس {اسم_الدولة: الوضع} زي ما هو ظاهر بالجدول
    (مثلاً {"Germany": "No tax rebate", "Switzerland": "ESTV Reporting", ...})
    أو None لو تعذّر السحب أو ما لقينا القسم أصلاً (بعض الصناديق ما إلها
    هاد القسم).

    ⚠️ هشاشة: هاد اعتماد على تركيب HTML الحالي لصفحة justETF (id="collapse-tax"
    جوا تبويب Basics) — لو غيّروا تصميم الصفحة بالمستقبل، لازم تحديث الـ
    selector هون."""
    url = JUSTETF_PROFILE_URL_TMPL.format(isin=isin)
    resp = requests.get(url, headers=TAX_REQUEST_HEADERS, timeout=TAX_REQUEST_TIMEOUT)
    if resp.status_code != requests.codes.ok:
        raise RuntimeError(f"HTTP {resp.status_code} عند جلب صفحة {isin} لقسم الضرائب")

    soup = BeautifulSoup(resp.text, "html.parser")
    section = soup.find(id="collapse-tax")
    if section is None:
        # احتياط لو تغيّر الـ id — دوّر على العنوان "Tax status" وخد أقرب جدول بعده
        heading = soup.find(string=re.compile(r"Tax\s*status", re.I))
        section = heading.find_parent(["section", "div"]) if heading else None
    if section is None:
        return None  # هاد الصندوق ما إلو قسم tax status أصلاً (طبيعي لبعض الصناديق)

    result = {}
    # الجدول جوا القسم بيصير إما <table> حقيقي أو صفوف <div>/<dl> — نجرب الاتنين
    table = section.find("table")
    if table:
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) >= 2:
                country = cells[0].get_text(strip=True)
                status = cells[1].get_text(strip=True)
                if country:
                    result[country] = status or "-"
    if not result:
        # نسخة احتياطية: صفوف بشكل dl/dt/dd أو div-based
        dts = section.find_all("dt")
        dds = section.find_all("dd")
        if dts and len(dts) == len(dds):
            for dt, dd in zip(dts, dds):
                country = dt.get_text(strip=True)
                status = dd.get_text(strip=True)
                if country:
                    result[country] = status or "-"

    return result or None


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
        "taxStatus": scrape_tax_status_safe(isin),
    }


def scrape_tax_status_safe(isin):
    """نسخة "لا تفشل": بتحاول مرة وحدة إضافية بسيطة، وإذا فشلت بترجع None
    بدل ما توقف سحب باقي بيانات الصندوق (الـ TER/الحيازات...الخ أهم).
    ما بتدخل بمنطق إعادة المحاولة/الـ 403-cooldown تبع scrape_with_retries
    الرئيسي عشان ما تبطّئ الدفعة كلها لصندوق واحد."""
    try:
        time.sleep(1.5)  # فسحة إضافية بسيطة — هاد طلب ثاني منفصل لنفس الصندوق
        return scrape_tax_status(isin)
    except Exception as e:
        print(f"[tax-status] فشل سحب الوضع الضريبي لـ {isin} ({e}) — رح نكمل بدونه")
        return None


def scrape_with_retries(isin):
    """يحاول MAX_ATTEMPTS مرة. لو الخطأ فيه '403' (حظر مؤقت)، يستنى COOLDOWN
    كامل قبل إعادة المحاولة. أخطاء تانية (زي فشل جلب السعر الحي العابر) يعيد
    المحاولة بعد فسحة عادية بس."""
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return scrape_one(isin), None
        except Exception as e:
            last_error = e
            is_block = "403" in str(e)
            if attempt < MAX_ATTEMPTS:
                wait = COOLDOWN_ON_BLOCK if is_block else SLEEP_BETWEEN
                print(f"محاولة {attempt} فشلت ({e}) — استنى {wait:.0f}ث وحاول تاني... ",
                      end="", flush=True)
                time.sleep(wait)
    return None, last_error


def main():
    all_isins = load_isins()
    if not all_isins:
        print("ما في أي ISIN لسحبه — تأكد من ids.txt")
        sys.exit(1)

    batch = get_this_weeks_batch(all_isins)
    if not batch:
        print("⚠️ دفعة هالأسبوع فاضية (غريب) — ما في شي لعمله")
        sys.exit(0)

    # نبدأ من آخر snapshot موجود (بيانات باقي الدفعات من أسابيع سابقة) ونحدّث
    # فيه بس دفعة هالأسبوع — مش نبني من صفر كل مرة
    results = load_existing_snapshot()
    print(f"صناديق محفوظة من دفعات سابقة: {len(results)}")

    print(f"=== بدء سحب دفعة هالأسبوع: {len(batch)} صندوق من justETF ===")
    failed = {}  # isin -> آخر رسالة خطأ (بس لصناديق دفعة هالأسبوع)

    def run_pass(pending_isins, label):
        for i, isin in enumerate(pending_isins, 1):
            print(f"[{label} {i}/{len(pending_isins)}] {isin} ... ", end="", flush=True)
            data, err = scrape_with_retries(isin)
            if data is not None:
                results[isin] = data
                failed.pop(isin, None)
                print("تم ✓")
            else:
                failed[isin] = str(err)
                print(f"فشل نهائياً ({err})")
                traceback.print_exc(file=sys.stdout)
            time.sleep(SLEEP_BETWEEN)

    run_pass(batch, "أولى")

    # جولة أخيرة على أي صندوق فشل بدفعة هالأسبوع
    if failed:
        print(f"\n=== جولة إعادة محاولة نهائية لـ {len(failed)} صندوق فشلوا ===")
        print(f"استراحة {COOLDOWN_ON_BLOCK:.0f}ث قبل المحاولة الأخيرة...")
        time.sleep(COOLDOWN_ON_BLOCK)
        run_pass(list(failed.keys()), "إعادة")

    snapshot = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(results),
        "failed": list(failed.keys()),  # فشل نهائي بدفعة هالأسبوع بس
        "funds": results,  # كل الصناديق المتراكمة من كل الدفعات
    }
    OUTPUT_FILE.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=None), encoding="utf-8"
    )
    print(f"=== خلصنا: {len(results)} صندوق بالمجموع بالملف "
          f"({len(batch) - len(failed)}/{len(batch)} نجحوا بدفعة هالأسبوع)، "
          f"{len(failed)} فشلوا نهائياً بدفعة هالأسبوع ===")
    if failed:
        print("الصناديق يلي فشلوا نهائياً:", ", ".join(failed.keys()))


if __name__ == "__main__":
    main()
