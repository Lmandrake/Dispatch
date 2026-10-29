# NOTE: all people, handles and ticket/incident numbers in this generator are FICTIONAL test data.
"""Dataset builder for task 19 (two datasets: visible 2026-03, hidden 2026-10).

build(which) -> dict filename -> text (feeds under 'feeds/').
"""
import json, random
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc

CATALOG = '''# Kettle Cloud plan catalogue, finance-approved 2025-09-15 (rev 7)

[metrics.api_calls]
name = "API calls"
unit = "calls"
aggregation = "sum"

[metrics.storage_gb]
name = "Storage"
unit = "GB"
aggregation = "last"
precision = 3

[metrics.seats]
name = "Seats"
unit = "seats"
aggregation = "max"

[plans.starter]
name = "Starter"
currency = "USD"
base_fee = "49.00"

[[plans.starter.charges]]
metric = "api_calls"
model = "per_unit"
unit_price = "0.0005"
included = 100000

[[plans.starter.charges]]
metric = "storage_gb"
model = "per_unit"
unit_price = "0.023"
included = 50

[plans.team]
name = "Team"
currency = "USD"
base_fee = "199.00"

[[plans.team.charges]]
metric = "api_calls"
model = "graduated"
tiers = [
  { up_to = 1000000, unit_price = "0.0004" },
  { up_to = 10000000, unit_price = "0.00025" },
  { up_to = "inf", unit_price = "0.00012" },
]

[[plans.team.charges]]
metric = "storage_gb"
model = "graduated"
tiers = [
  { up_to = 500, unit_price = "0.021" },
  { up_to = "inf", unit_price = "0.018" },
]

[[plans.team.charges]]
metric = "seats"
model = "volume"
tiers = [
  { up_to = 10, unit_price = "12.00" },
  { up_to = 25, unit_price = "10.00" },
  { up_to = "inf", unit_price = "8.00" },
]

[plans.business]
name = "Business"
currency = "USD"
base_fee = "499.00"

[[plans.business.charges]]
metric = "api_calls"
model = "volume"
tiers = [
  { up_to = 1000000, unit_price = "0.00035" },
  { up_to = 5000000, unit_price = "0.0003" },
  { up_to = "inf", unit_price = "0.00022" },
]

[[plans.business.charges]]
metric = "storage_gb"
model = "package"
package_size = 100
unit_price = "1.90"
included = 200

[[plans.business.charges]]
metric = "seats"
model = "volume"
tiers = [
  { up_to = 20, unit_price = "11.00" },
  { up_to = 50, unit_price = "9.00" },
  { up_to = "inf", unit_price = "7.00" },
]

[plans.team_eu]
name = "Team (EU)"
currency = "EUR"
base_fee = "185.00"

[[plans.team_eu.charges]]
metric = "api_calls"
model = "graduated"
tiers = [
  { up_to = 1000000, unit_price = "0.00037" },
  { up_to = 10000000, unit_price = "0.00023" },
  { up_to = "inf", unit_price = "0.00011" },
]

[[plans.team_eu.charges]]
metric = "storage_gb"
model = "graduated"
tiers = [
  { up_to = 500, unit_price = "0.0195" },
  { up_to = "inf", unit_price = "0.0167" },
]

[[plans.team_eu.charges]]
metric = "seats"
model = "volume"
tiers = [
  { up_to = 10, unit_price = "11.00" },
  { up_to = 25, unit_price = "9.25" },
  { up_to = "inf", unit_price = "7.40" },
]

[plans.business_eu]
name = "Business (EU)"
currency = "EUR"
base_fee = "459.00"

[[plans.business_eu.charges]]
metric = "api_calls"
model = "volume"
tiers = [
  { up_to = 1000000, unit_price = "0.00032" },
  { up_to = 5000000, unit_price = "0.00028" },
  { up_to = "inf", unit_price = "0.0002" },
]

[[plans.business_eu.charges]]
metric = "storage_gb"
model = "package"
package_size = 100
unit_price = "1.75"
included = 200

[[plans.business_eu.charges]]
metric = "seats"
model = "volume"
tiers = [
  { up_to = 20, unit_price = "10.20" },
  { up_to = 50, unit_price = "8.30" },
  { up_to = "inf", unit_price = "6.50" },
]

[plans.legacy_basic]
name = "Basic (legacy)"
currency = "USD"
base_fee = "29.00"
legacy = true

[[plans.legacy_basic.charges]]
metric = "api_calls"
model = "per_unit"
unit_price = "0.0006"
'''

TAX = '''# Tax jurisdictions (Finance / Tax, reviewed 2026-01-05)

[jurisdictions.US-NY]
name = "New York City"
rate = "0.08875"
rounding = "per_invoice"
label = "Sales tax"

[jurisdictions.US-CA]
name = "California (SaaS exempt)"
rate = "0"
label = "Sales tax"

[jurisdictions.US-TX]
name = "Texas"
rate = "0.0625"
rounding = "per_line"
label = "Sales tax"

[jurisdictions.US-CO]
name = "Colorado"
rate = "0.029"
label = "Sales tax"

[jurisdictions.DE]
name = "Germany"
rate = "0.19"
reverse_charge = true
label = "VAT"

[jurisdictions.NL]
name = "Netherlands"
rate = "0.21"
reverse_charge = true
label = "VAT"

[jurisdictions.GB]
name = "United Kingdom"
rate = "0.20"
rounding = "per_line"
label = "VAT"

[jurisdictions.SE]
name = "Sweden"
rate = "0.25"
label = "Moms"

[jurisdictions.CH]
name = "Switzerland"
rate = "0.081"
mode = "half_even"
label = "MWST"

[jurisdictions.JP]
name = "Japan"
rate = "0.10"
mode = "down"
label = "Consumption tax"

[jurisdictions.AU]
name = "Australia"
rate = "0.10"
rounding = "per_line"
label = "GST"
'''

COUPONS = '''# Coupons (Revenue Ops)

[coupons.WELCOME10]
name = "Welcome"
percent_off = "10"
duration = "repeating"
cycles = 3

[coupons.SPRING15]
name = "Spring usage"
percent_off = "15"
applies_to = "usage"
duration = "once"

[coupons.PARTNER50]
name = "Partner credit"
amount_off = "50.00"
currency = "USD"
duration = "forever"

[coupons.BASE20]
name = "Annual prepay"
percent_off = "20"
applies_to = "base"
duration = "forever"

[coupons.AUTUMN12]
name = "Autumn"
percent_off = "12.5"
duration = "once"
'''

DUNNING = '''# Dunning schedule (Credit control, 2025-11)

[[steps]]
days = 7
action = "reminder"

[[steps]]
days = 21
action = "late_fee"
percent = "1.5"
minimum = "5.00"
currency = "USD"

[[steps]]
days = 45
action = "suspend"
'''

# customer rows: id,name,tz,anchor,currency,jurisdiction,tax_id,email,terms
CUSTOMERS = [
    ("C01", "Acme Robotics Inc.", "America/New_York", 1, "USD", "US-NY", "", "ap@acme-robotics.example", 30),
    ("C02", "Brightline GmbH", "Europe/Berlin", 1, "EUR", "DE", "DE 811 907 980", "rechnung@brightline.example", 14),
    ("C03", "Cobalt Analytics LLC", "America/Los_Angeles", 15, "USD", "US-CA", "", "billing@cobalt.example", 30),
    ("C04", "Dunmore Ltd", "Europe/London", 1, "GBP", "GB", "", "accounts@dunmore.example", 30),
    ("C05", "Eastgate Studio KK", "Asia/Tokyo", 10, "JPY", "JP", "", "keiri@eastgate.example", 30),
    ("C06", "Fjallbacka Data AB", "Europe/Stockholm", 1, "SEK", "SE", "", "faktura@fjallbacka.example", 30),
    ("C07", "Granite Health Partners", "America/Chicago", 28, "USD", "US-TX", "", "ap@granitehealth.example", 45),
    ("C08", "Harbour & Co Pty Ltd", "Australia/Sydney", 1, "AUD", "AU", "", "accounts@harbour.example", 30),
    ("C09", "Ironwood SA", "Europe/Zurich", 1, "CHF", "CH", "", "finance@ironwood.example", 30),
    ("C10", "Juniper Labs Inc.", "America/New_York", 1, "USD", "US-NY", "", "ap@juniperlabs.example", 30),
    ("C11", "Lumen BV", "Europe/Amsterdam", 20, "EUR", "NL", "NL 8533.67.432.B01", "facturen@lumen.example", 30),
    ("C12", "Meridian Outfitters Corp.", "America/Denver", 5, "USD", "US-CO", "", "billing@meridian.example", 30),
]

# second dataset: same ids/zones mostly, different anchors/plans for Oct 2026
CUSTOMERS2 = [
    ("C01", "Acme Robotics Inc.", "America/New_York", 1, "USD", "US-NY", "", "ap@acme-robotics.example", 30),
    ("C02", "Brightline GmbH", "Europe/Berlin", 1, "EUR", "DE", "", "rechnung@brightline.example", 14),
    ("C03", "Cobalt Analytics LLC", "America/Los_Angeles", 12, "USD", "US-CA", "", "billing@cobalt.example", 30),
    ("C04", "Dunmore Ltd", "Europe/London", 1, "GBP", "GB", "", "accounts@dunmore.example", 30),
    ("C05", "Eastgate Studio KK", "Asia/Tokyo", 1, "JPY", "JP", "", "keiri@eastgate.example", 30),
    ("C06", "Fjallbacka Data AB", "Europe/Stockholm", 20, "SEK", "SE", "SE 556677889901", "faktura@fjallbacka.example", 30),
    ("C07", "Granite Health Partners", "America/Chicago", 1, "USD", "US-TX", "", "ap@granitehealth.example", 45),
    ("C08", "Harbour & Co Pty Ltd", "Australia/Sydney", 1, "AUD", "AU", "", "accounts@harbour.example", 30),
    ("C09", "Ironwood SA", "Europe/Zurich", 15, "CHF", "CH", "", "finance@ironwood.example", 30),
    ("C10", "Juniper Labs Inc.", "America/New_York", 1, "USD", "US-NY", "", "ap@juniperlabs.example", 30),
    ("C13", "Nordlicht AG", "Europe/Berlin", 1, "EUR", "DE", "", "buchhaltung@nordlicht.example", 30),
    ("C14", "Orchard Lane Ltd", "Europe/London", 25, "USD", "GB", "", "ap@orchardlane.example", 30),
]


def csv_rows(rows):
    import csv, io
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    for r in rows:
        w.writerow(r)
    return out.getvalue()


def local(tzname, y, m, d, hh=0, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=ZoneInfo(tzname)).astimezone(UTC)


def iso(dt, tzname=None, style="Z"):
    if style == "Z":
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    loc = dt.astimezone(ZoneInfo(tzname))
    off = loc.strftime("%z")
    return loc.strftime("%Y-%m-%dT%H:%M:%S") + off[:3] + ":" + off[3:]


def daterange(a, b):
    d = a
    while d < b:
        yield d
        d += timedelta(days=1)


class Feeds:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.api = []      # (event_id, customer, metric, qty, ts_text, note)
        self.storage = []  # dict lines
        self.seats = []    # text lines (sorted later)
        self.n = {"api": 0, "st": 0, "se": 0}

    def eid(self, kind):
        self.n[kind] += 1
        return f"{kind}-{self.n[kind]:05d}"

    def add_api(self, cust, at, qty, tz, note=""):
        style = self.rng.choice(["Z", "Z", "off"])
        self.api.append([self.eid("api"), cust, "api_calls", str(qty), iso(at, tz, style), note])
        return self.api[-1]

    def add_storage(self, cust, at, gb, tz, ts_style=None):
        e = self.eid("st")
        r = self.rng.random()
        if r < 0.5:
            val, unit = f"{gb}", "GB"
        elif r < 0.8:
            val, unit = f"{(gb * 1000).normalize():f}", "MB"
        else:
            val, unit = f"{gb}", None
        ts_r = self.rng.random()
        if ts_style == "iso":
            ts_r = 0.9
        if ts_r < 0.5:
            ts = int(at.timestamp())
        elif ts_r < 0.75:
            ts = int(at.timestamp()) * 1000
        else:
            ts = iso(at, tz, "off")
        obj = {"id": e, "customer": cust, "metric": "storage_gb", "value": val, "ts": ts}
        if unit:
            obj["unit"] = unit
        self.storage.append(obj)

    def add_seats(self, cust, at, n, tz, by="seat-sync"):
        e = self.eid("se")
        stamp = iso(at, tz, "off")
        byv = f'"{by}"' if " " in by else by
        self.seats.append((at, f"{stamp} event={e} cust={cust} metric=seats qty={n} by={byv}"))


from decimal import Decimal as D


def profile(fd, cust, tz, start, end, *, api=(2000, 60000), api_per_day=2, storage=None, seats=None,
            seat_days=4, storage_days=3, quiet_hours=True):
    """Background usage between local dates start..end (exclusive), away from midnight."""
    rng = fd.rng
    for day in daterange(start, end):
        for _ in range(api_per_day):
            hh = rng.randint(2, 21) if quiet_hours else rng.randint(0, 23)
            at = local(tz, day.year, day.month, day.day, hh, rng.randint(0, 59), rng.randint(0, 59))
            fd.add_api(cust, at, rng.randint(*api), tz)
    if storage:
        lo, hi = storage
        val = D(str(lo))
        step = (D(str(hi)) - D(str(lo))) / max(1, (end - start).days // storage_days)
        for i, day in enumerate(list(daterange(start, end))[::storage_days]):
            at = local(tz, day.year, day.month, day.day, 12, 0, 0)
            gb = (val + step * i + D(rng.randint(0, 999)) / 1000).quantize(D("0.001"))
            fd.add_storage(cust, at, gb, tz)
    if seats:
        lo, hi = seats
        for day in list(daterange(start, end))[::seat_days]:
            at = local(tz, day.year, day.month, day.day, 9, rng.randint(0, 59), 0)
            fd.add_seats(cust, at, rng.randint(lo, hi), tz)


def write_feeds(fd, files, prefix):
    api = sorted(fd.api, key=lambda r: r[0])
    header = ["event_id", "customer", "metric", "quantity", "timestamp", "note"]
    half = len(api) // 2
    files[f"feeds/{prefix}-gateway-a.csv"] = csv_rows([header] + api[:half])
    # second gateway export uses a different column order
    hdr2 = ["timestamp", "event_id", "customer", "note", "metric", "quantity"]
    rows2 = [[r[4], r[0], r[1], r[5], r[2], r[3]] for r in api[half:]]
    files[f"feeds/{prefix}-gateway-b.csv"] = csv_rows([hdr2] + rows2)
    files[f"feeds/{prefix}-storage.jsonl"] = "".join(json.dumps(o) + "\n" for o in fd.storage)
    seats = [ln for _, ln in sorted(fd.seats, key=lambda t: t[0])]
    files[f"feeds/{prefix}-seats.log"] = "# seat-service audit log\n" + "".join(ln + "\n" for ln in seats)


def customers_csv(rows, extra=None):
    """extra: id -> (service_region, tax_override, status)"""
    extra = extra or {}
    head = ["id", "name", "timezone", "anchor_day", "currency", "jurisdiction", "tax_id", "email", "terms_days",
            "service_region", "tax_override", "status"]
    out = []
    for r in rows:
        sr, to, st = extra.get(r[0], ("", "", "active"))
        out.append(list(r) + [sr, to, st])
    return csv_rows([head] + out)


# ---------------------------------------------------------------- dataset 1
def build_visible():
    files = {}
    fd = Feeds(1903)
    files["customers.csv"] = customers_csv(CUSTOMERS + [
        ("C13", "Mercer Bio Inc.", "America/New_York", 1, "USD", "US-NY", "", "ap@mercerbio.example", 30),
        ("C14", "Orchard Lane Ltd", "Europe/London", 1, "USD", "GB", "", "ap@orchardlane.example", 30)],
        {"C13": ("US-CA", "", "closed"), "C14": ("US-TX", "", "active")})
    files["catalog.toml"] = CATALOG
    files["tax.toml"] = TAX
    files["coupons.toml"] = COUPONS
    files["dunning.toml"] = DUNNING
    files["subscriptions.csv"] = csv_rows([["customer", "plan", "effective"],
        ["C01", "team", "2025-06-01"],
        ["C02", "team_eu", "2025-09-01"],
        ["C03", "team", "2025-10-15"], ["C03", "business", "2026-04-02"],
        ["C04", "team", "2025-04-01"],
        ["C05", "starter", "2026-01-10"], ["C05", "team", "2026-03-21"],
        ["C06", "business", "2025-12-01"],
        ["C07", "starter", "2025-08-28"], ["C07", "team", "2026-04-10"],
        ["C08", "team", "2025-11-01"],
        ["C09", "business_eu", "2025-07-01"],
        ["C10", "starter", "2025-12-01"], ["C10", "team", "2026-02-14"], ["C10", "starter", "2026-02-14"],
        ["C10", "starter", "2026-03-01"],
        ["C11", "business", "2025-05-20"], ["C11", "team", "2026-04-07"],
        ["C12", "team", "2025-03-05"], ["C12", "team", "2026-03-20"],
        ["C13", "team", "2025-10-01"], ["C13", "none", "2026-03-01"],
        ["C14", "starter", "2025-11-01"],
    ])
    files["redemptions.csv"] = csv_rows([["customer", "coupon", "first_cycle"],
        ["C02", "WELCOME10", "2026-02"],
        ["C03", "SPRING15", "2026-03"],
        ["C05", "WELCOME10", "2026-01"],
        ["C06", "PARTNER50", "2025-12"],
        ["C07", "BASE20", "2025-08"],
        ["C10", "WELCOME10", "2026-02"],
        ["C10", "PARTNER50", "2026-03"],
        ["C12", "SPRING15", "2026-04"],
        ["C14", "PARTNER50", "2026-03"],
    ])
    files["credits.csv"] = csv_rows([["customer", "grant_id", "currency", "amount", "granted", "expires"],
        ["C08", "G-2201", "AUD", "300.00", "2026-01-15", "2026-07-15"],
        ["C08", "G-2202", "AUD", "5000.00", "2026-02-01", ""],
        ["C09", "G-2310", "EUR", "120.00", "2025-12-01", "2026-12-01"],
        ["C11", "G-2400", "EUR", "200.00", "2025-01-01", "2026-01-01"],
        ["C03", "G-2510", "EUR", "25.00", "2026-03-01", ""],
        ["C04", "G-2120", "GBP", "460.00", "2026-01-01", "2026-03-01"],
        ["C06", "G-2130", "SEK", "500.00", "2025-12-15", "2026-02-01"],
        ["C07", "G-2511", "EUR", "40.00", "2026-03-01", ""],
    ])
    files["receivables.csv"] = csv_rows([["invoice", "customer", "currency", "amount", "due", "paid_on"],
        ["KC-2025-12-C06", "C06", "SEK", "3120.00", "2026-02-01", ""],
    ])
    files["fx_rates.csv"] = csv_rows([["effective", "currency", "per_usd"],
        ["2025-12-01", "EUR", "0.9140"], ["2025-12-01", "GBP", "0.7872"], ["2025-12-01", "JPY", "151.40"],
        ["2025-12-01", "SEK", "10.512"], ["2025-12-01", "AUD", "1.5466"], ["2025-12-01", "CHF", "0.8870"],
        ["2026-01-01", "EUR", "0.9165"], ["2026-01-01", "GBP", "0.7889"], ["2026-01-01", "JPY", "152.10"],
        ["2026-01-01", "SEK", "10.455"], ["2026-01-01", "AUD", "1.5402"], ["2026-01-01", "CHF", "0.8851"],
        ["2026-02-01", "EUR", "0.9188"], ["2026-03-01", "EUR", "0.9210"], ["2026-03-16", "EUR", "0.9234"],
        ["2026-04-01", "EUR", "0.9251"], ["2026-04-20", "EUR", "0.9277"],
        ["2026-02-01", "GBP", "0.7902"], ["2026-03-01", "GBP", "0.7915"], ["2026-03-26", "GBP", "0.7948"],
        ["2026-04-01", "GBP", "0.7960"],
        ["2026-02-01", "JPY", "151.20"], ["2026-03-01", "JPY", "149.85"], ["2026-04-01", "JPY", "150.40"],
        ["2026-04-06", "JPY", "151.05"],
        ["2026-02-01", "SEK", "10.412"], ["2026-03-01", "SEK", "10.3375"], ["2026-03-20", "SEK", "10.2950"],
        ["2026-04-01", "SEK", "10.3010"],
        ["2026-02-01", "AUD", "1.5321"], ["2026-03-01", "AUD", "1.5187"], ["2026-04-01", "AUD", "1.5240"],
        ["2026-02-01", "CHF", "0.8823"], ["2026-03-01", "CHF", "0.8790"], ["2026-03-23", "CHF", "0.8812"],
        ["2026-04-01", "CHF", "0.8835"],
    ])
    files["README.txt"] = ("March 2026 billing data (cycle 2026-03), exported 2026-04-29.\n"
                           "feeds/ holds the raw gateway, storage and seat feeds for 2026-01-26 .. 2026-05-02.\n"
                           "issued/ holds the February 2026 invoices as they were sent.\n")
    s = date
    # background usage: a few days either side of each customer's period
    profile(fd, "C01", "America/New_York", s(2025, 12, 27), s(2026, 4, 5), api=(5000, 25000), storage=(310, 380), seats=(6, 9))
    profile(fd, "C02", "Europe/Berlin", s(2025, 12, 27), s(2026, 4, 4), api=(4000, 18000), storage=(520, 610), seats=(11, 18))
    profile(fd, "C03", "America/Los_Angeles", s(2025, 12, 27), s(2026, 4, 19), api=(10000, 40000), storage=(200, 640), seats=(14, 23))
    profile(fd, "C04", "Europe/London", s(2025, 12, 27), s(2026, 4, 4), api=(3000, 12000), storage=(90, 140), seats=(4, 9))
    profile(fd, "C05", "Asia/Tokyo", s(2025, 12, 27), s(2026, 4, 13), api=(1000, 6000), storage=(60, 75))
    profile(fd, "C06", "Europe/Stockholm", s(2025, 12, 27), s(2026, 4, 4), api=(20000, 60000), storage=(700, 980), seats=(12, 19))
    profile(fd, "C07", "America/Chicago", s(2025, 12, 27), s(2026, 5, 2), api=(1000, 9000), storage=(30, 160), seats=(3, 8))
    profile(fd, "C08", "Australia/Sydney", s(2025, 12, 27), s(2026, 4, 4), api=(8000, 30000), storage=(400, 470), seats=(15, 22))
    profile(fd, "C09", "Europe/Zurich", s(2025, 12, 27), s(2026, 4, 4), api=(15000, 45000), storage=(380, 455), seats=(30, 49))
    profile(fd, "C10", "America/New_York", s(2025, 12, 27), s(2026, 4, 4), api=(2000, 9000), storage=(20, 70))
    profile(fd, "C11", "Europe/Amsterdam", s(2025, 12, 27), s(2026, 4, 24), api=(30000, 90000), storage=(250, 330), seats=(18, 30))
    profile(fd, "C12", "America/Denver", s(2025, 12, 27), s(2026, 4, 9), api=(4000, 20000), storage=(150, 230), seats=(18, 24))

    # --- traps -------------------------------------------------------------
    # C01: a usage record 20 minutes into April (local) -- DST trap -- and a
    # gateway row with a quoted comma in its note of the very same size.
    fd.add_api("C01", local("America/New_York", 2026, 4, 1, 0, 20, 0), 3500, "America/New_York")
    fd.add_api("C01", local("America/New_York", 2026, 3, 17, 14, 2, 11), 3500, "America/New_York",
               note="replayed by support, ticket 4471")
    # C02: storage snapshot and seats just after local midnight on 1 April
    fd.add_storage("C02", local("Europe/Berlin", 2026, 4, 1, 0, 30, 0), D("702.250"), "Europe/Berlin", ts_style="iso")
    fd.add_api("C02", local("Europe/Berlin", 2026, 4, 1, 0, 10, 0), 41000, "Europe/Berlin")
    fd.add_storage("C02", local("Europe/Berlin", 2026, 3, 31, 23, 30, 0), D("611.875"), "Europe/Berlin", ts_style="iso")
    fd.add_storage("C09", local("Europe/Zurich", 2026, 3, 31, 22, 0, 0), D("447.120"), "Europe/Zurich", ts_style="iso")
    fd.add_storage("C13", local("America/New_York", 2026, 2, 27, 12, 0, 0), D("410.000"), "America/New_York")
    profile(fd, "C13", "America/New_York", s(2025, 12, 27), s(2026, 3, 1), api=(20000, 40000), seats=(5, 8))
    profile(fd, "C14", "Europe/London", s(2025, 12, 27), s(2026, 2, 28), api=(4000, 9000), storage=(40, 90))
    profile(fd, "C14", "Europe/London", s(2026, 3, 1), s(2026, 4, 4), api=(500, 1400), storage=(10, 30))
    # C06: peak seats exactly at the business tier-1 bound (20)
    fd.add_seats("C06", local("Europe/Stockholm", 2026, 3, 18, 10, 0, 0), 20, "Europe/Stockholm")
    # C08: two gateway rows with commas inside quoted notes
    fd.add_api("C08", local("Australia/Sydney", 2026, 3, 9, 11, 0, 0), 27500, "Australia/Sydney",
               note='backfill, see "INC-2207"')
    fd.add_api("C08", local("Australia/Sydney", 2026, 3, 22, 16, 45, 0), 18250, "Australia/Sydney",
               note="manual, approved by J. Ortiz")
    # C09: peak seats exactly 50 (business_eu tier-2 bound)
    fd.add_seats("C09", local("Europe/Zurich", 2026, 3, 12, 15, 0, 0), 50, "Europe/Zurich", by="admin console")
    # C10: a quoted-comma note
    fd.add_api("C10", local("America/New_York", 2026, 3, 30, 9, 30, 0), 9000, "America/New_York",
               note="load test, customer approved")
    c10_replay = fd.add_api("C10", local("America/New_York", 2026, 3, 12, 15, 10, 0), 9000, "America/New_York")
    # C12: peak 25 seats (team tier-2 bound) in period, 26 seats just after local midnight Apr 5
    fd.add_seats("C12", local("America/Denver", 2026, 3, 27, 8, 0, 0), 25, "America/Denver")
    fd.add_seats("C12", local("America/Denver", 2026, 4, 5, 0, 30, 0), 26, "America/Denver")
    # C11 seats peak in its period just over the business bound handled normally
    fd.add_seats("C11", local("Europe/Amsterdam", 2026, 4, 2, 9, 0, 0), 31, "Europe/Amsterdam")
    # quoted-comma note on a row outside any billed period (harmless either way)
    fd.add_api("C04", local("Europe/London", 2026, 4, 3, 10, 0, 0), 1200, "Europe/London", note="late, ignore")

    write_feeds(fd, files, "2026-03")
    # genuinely bad rows that must be rejected (appended to feeds)
    files["feeds/2026-03-gateway-a.csv"] += (
        'api-80001,C02,api_calls,2600,2026-04-10T00:30:00+02:00,\n'
        'api-80002,C07,api_calls,96000,2026-04-10T00:30:00-05:00,\n'
        'api-80003,C09,api_calls,1800,2026-04-07T00:05:00+02:00,\n'
        'api-80004,C11,api_calls,240000,2026-04-07T00:05:00-05:00,\n'
        'api-90001,C03,api_calls,1200,2026-03-20T10:00:00,\n'          # no offset
        'api-90002,C03,api_calls,-50,2026-03-20T10:00:00Z,\n'          # negative
        'api-90003,C99,api_calls,100,2026-03-20T10:00:00Z,\n'          # unknown customer
        'api-90004,C07,api_calls,100,2026-04-01T10:00:00Z\n'           # 5 fields
    )
    # replays: identical re-delivery of an existing event, and a conflicting one
    rows = sorted(fd.api, key=lambda r: r[0])
    for i in (3, 140, 333):
        r = rows[i]
        files["feeds/2026-03-gateway-b.csv"] += csv_rows([[r[4], r[0], r[1], r[5], r[2], r[3]]])
    r = c10_replay
    if r in rows[:len(rows) // 2]:
        files["feeds/2026-03-gateway-b.csv"] += csv_rows([[r[4], r[0], r[1], r[5], r[2], r[3]]])
    else:
        files["feeds/2026-03-gateway-a.csv"] += csv_rows([r])
    second = rows[10]
    files["feeds/2026-03-gateway-b.csv"] += csv_rows([[second[4], second[0], second[1], "", second[2], str(int(second[3]) + 1)]])
    files["feeds/2026-03-storage.jsonl"] += (
        '{"id": "st-90001", "customer": "C02", "metric": "storage_gb", "value": 12.5, "ts": 1773000000}\n'
        'not json at all\n'
    )
    files["feeds/2026-03-seats.log"] += '2026-03-15T10:00:00+01:00 event=se-90001 cust=C09 metric=seats by="unterminated\n'
    return files


# ---------------------------------------------------------------- dataset 2
def build_hidden():
    files = {}
    fd = Feeds(1910)
    files["customers.csv"] = customers_csv(CUSTOMERS2 + [
        ("C15", "Pellucid Systems Ltd", "Europe/London", 1, "GBP", "GB", "", "ap@pellucid.example", 30)],
        {"C14": ("US-TX", "", "active"), "C03": ("US-WA", "", "active"), "C15": ("", "", "closed"),
         "C06": ("NO", "", "active")})
    files["catalog.toml"] = CATALOG
    files["tax.toml"] = TAX
    files["coupons.toml"] = COUPONS
    files["dunning.toml"] = DUNNING
    files["subscriptions.csv"] = csv_rows([["customer", "plan", "effective"],
        ["C01", "team", "2025-06-01"],
        ["C02", "team_eu", "2025-09-01"],
        ["C03", "business", "2026-04-02"],
        ["C04", "team", "2025-04-01"],
        ["C05", "starter", "2026-01-10"], ["C05", "team", "2026-10-12"],
        ["C06", "team", "2026-11-07"],
        ["C06", "business", "2025-12-01"],
        ["C07", "team", "2026-04-10"],
        ["C08", "team", "2025-11-01"], ["C08", "none", "2026-10-21"],
        ["C09", "business_eu", "2025-07-01"], ["C09", "team_eu", "2026-11-03"],
        ["C10", "team", "2026-06-01"], ["C10", "team", "2026-10-15"], ["C10", "business", "2026-10-15"],
        ["C07", "team", "2026-09-10"], ["C07", "starter", "2026-09-10"],
        ["C15", "team", "2026-02-01"], ["C15", "none", "2026-10-15"],
        ["C13", "business_eu", "2026-08-01"],
        ["C14", "starter", "2026-05-25"], ["C14", "business", "2026-11-02"],
    ])
    files["redemptions.csv"] = csv_rows([["customer", "coupon", "first_cycle"],
        ["C01", "AUTUMN12", "2026-10"],
        ["C03", "WELCOME10", "2026-09"],
        ["C05", "SPRING15", "2026-10"],
        ["C06", "BASE20", "2026-01"],
        ["C09", "PARTNER50", "2026-06"],
        ["C13", "PARTNER50", "2026-08"],
        ["C14", "WELCOME10", "2026-10"],
    ])
    files["credits.csv"] = csv_rows([["customer", "grant_id", "currency", "amount", "granted", "expires"],
        ["C04", "G-3101", "USD", "75.00", "2026-09-01", "2027-03-01"],
        ["C07", "G-3150", "USD", "40.00", "2026-10-01", ""],
        ["C07", "G-3151", "USD", "60.00", "2026-10-01", "2026-12-31"],
        ["C09", "G-3200", "EUR", "900.00", "2026-06-01", ""],
        ["C14", "G-3300", "EUR", "30.00", "2026-10-01", ""],
        ["C04", "G-3102", "GBP", "20.00", "2026-09-01", "2026-11-01"],
        ["C02", "G-3110", "EUR", "615.00", "2026-08-01", "2026-10-01"],
        ["C08", "G-3120", "AUD", "40.00", "2026-08-01", "2026-09-01"],
        ["C01", "G-3301", "EUR", "15.00", "2026-10-01", ""],
    ])
    files["receivables.csv"] = csv_rows([["invoice", "customer", "currency", "amount", "due", "paid_on"],
        ["KC-2026-07-C08", "C08", "AUD", "640.00", "2026-08-20", ""],
    ])
    files["fx_rates.csv"] = csv_rows([["effective", "currency", "per_usd"],
        ["2026-07-01", "EUR", "0.9330"], ["2026-07-01", "GBP", "0.7850"], ["2026-07-01", "JPY", "146.10"],
        ["2026-07-01", "SEK", "10.071"], ["2026-07-01", "AUD", "1.5022"], ["2026-07-01", "CHF", "0.8690"],
        ["2026-08-01", "EUR", "0.9315"], ["2026-08-01", "GBP", "0.7861"], ["2026-08-01", "JPY", "146.80"],
        ["2026-08-01", "SEK", "10.097"], ["2026-08-01", "AUD", "1.4990"], ["2026-08-01", "CHF", "0.8702"],
        ["2026-09-01", "EUR", "0.9302"], ["2026-10-01", "EUR", "0.9288"], ["2026-10-19", "EUR", "0.9341"],
        ["2026-11-01", "EUR", "0.9356"], ["2026-11-10", "EUR", "0.9371"],
        ["2026-09-01", "GBP", "0.7870"], ["2026-10-01", "GBP", "0.7884"], ["2026-10-16", "GBP", "0.7931"],
        ["2026-11-01", "GBP", "0.7944"],
        ["2026-09-01", "JPY", "147.30"], ["2026-10-01", "JPY", "148.95"], ["2026-11-01", "JPY", "149.60"],
        ["2026-09-01", "SEK", "10.118"], ["2026-10-01", "SEK", "10.2045"], ["2026-11-01", "SEK", "10.2390"],
        ["2026-11-12", "SEK", "10.2711"],
        ["2026-09-01", "AUD", "1.4962"], ["2026-10-01", "AUD", "1.5034"], ["2026-11-01", "AUD", "1.5101"],
        ["2026-09-01", "CHF", "0.8711"], ["2026-10-01", "CHF", "0.8693"], ["2026-11-01", "CHF", "0.8730"],
        ["2026-11-09", "CHF", "0.8752"],
    ])
    s = date
    profile(fd, "C01", "America/New_York", s(2026, 7, 27), s(2026, 11, 5), api=(20000, 60000), storage=(420, 560), seats=(9, 14))
    profile(fd, "C02", "Europe/Berlin", s(2026, 7, 27), s(2026, 11, 4), api=(4000, 15000), storage=(480, 515), seats=(8, 12))
    profile(fd, "C03", "America/Los_Angeles", s(2026, 7, 27), s(2026, 11, 16), api=(30000, 70000), storage=(500, 900), seats=(21, 40))
    profile(fd, "C04", "Europe/London", s(2026, 7, 27), s(2026, 11, 4), api=(3000, 12000), storage=(100, 150), seats=(4, 9))
    profile(fd, "C05", "Asia/Tokyo", s(2026, 7, 27), s(2026, 11, 4), api=(1000, 7000), storage=(80, 110), seats=(2, 5))
    profile(fd, "C06", "Europe/Stockholm", s(2026, 7, 27), s(2026, 11, 24), api=(20000, 50000), storage=(820, 990), seats=(14, 19))
    profile(fd, "C07", "America/Chicago", s(2026, 7, 27), s(2026, 11, 4), api=(1000, 9000), storage=(130, 190), seats=(5, 9))
    profile(fd, "C08", "Australia/Sydney", s(2026, 7, 27), s(2026, 11, 4), api=(8000, 30000), storage=(400, 470), seats=(15, 22))
    profile(fd, "C09", "Europe/Zurich", s(2026, 7, 27), s(2026, 11, 19), api=(15000, 45000), storage=(380, 455), seats=(22, 34))
    profile(fd, "C10", "America/New_York", s(2026, 7, 27), s(2026, 11, 4), api=(3000, 11000), storage=(40, 90), seats=(6, 9))
    profile(fd, "C13", "Europe/Berlin", s(2026, 7, 27), s(2026, 11, 4), api=(22000, 40000), storage=(300, 360), seats=(12, 19))
    profile(fd, "C14", "Europe/London", s(2026, 7, 27), s(2026, 11, 29), api=(2000, 15000), storage=(60, 340), seats=(8, 15))
    profile(fd, "C15", "Europe/London", s(2026, 7, 27), s(2026, 10, 15), api=(4000, 16000), storage=(90, 120), seats=(3, 6))

    # --- traps -------------------------------------------------------------
    # DST: Berlin period ends at local midnight 1 Nov (CET); 23:40 on 31 Oct is still October
    fd.add_api("C13", local("Europe/Berlin", 2026, 10, 31, 23, 40, 0), 52000, "Europe/Berlin")
    fd.add_storage("C02", local("Europe/Berlin", 2026, 10, 31, 23, 15, 0), D("533.400"), "Europe/Berlin", ts_style="iso")
    fd.add_storage("C14", local("Europe/London", 2026, 11, 24, 22, 30, 0), D("344.500"), "Europe/London", ts_style="iso")
    # Sydney: DST starts 4 Oct, so 00:20 on 1 Nov is November
    fd.add_api("C08", local("Australia/Sydney", 2026, 11, 1, 0, 20, 0), 64000, "Australia/Sydney")
    # Los Angeles anchor 12: period ends 12 Nov 00:00 PST; 23:30 on 11 Nov is inside
    fd.add_seats("C03", local("America/Los_Angeles", 2026, 11, 11, 23, 30, 0), 51, "America/Los_Angeles")
    # London anchor 25 crosses the end of BST
    fd.add_api("C14", local("Europe/London", 2026, 11, 24, 23, 50, 0), 31000, "Europe/London")
    # tier bounds
    fd.add_seats("C10", local("America/New_York", 2026, 10, 14, 9, 0, 0), 10, "America/New_York")
    fd.add_seats("C01", local("America/New_York", 2026, 10, 20, 9, 0, 0), 25, "America/New_York")
    # C05 Tokyo: storage exactly at the team graduated bound is harmless; seats at 10 is not
    fd.add_seats("C05", local("Asia/Tokyo", 2026, 10, 15, 9, 0, 0), 10, "Asia/Tokyo")
    # quoted commas and doubled quotes
    fd.add_api("C03", local("America/Los_Angeles", 2026, 10, 20, 9, 0, 0), 48000, "America/Los_Angeles",
               note='migration, phase 2')
    fd.add_api("C07", local("America/Chicago", 2026, 10, 7, 13, 0, 0), 15500, "America/Chicago",
               note='customer said ""urgent"", call back')
    fd.add_api("C07", local("America/Chicago", 2026, 10, 8, 13, 0, 0), 4400, "America/Chicago",
               note='retry, 503, then ok')
    fd.add_api("C10", local("America/New_York", 2026, 10, 9, 9, 0, 0), 7700, "America/New_York",
               note='he said "fine"')
    write_feeds(fd, files, "2026-10")
    rows = sorted(fd.api, key=lambda r: r[0])
    for i in (5, 77):
        r = rows[i]
        files["feeds/2026-10-gateway-b.csv"] += csv_rows([[r[4], r[0], r[1], r[5], r[2], r[3]]])
    files["feeds/2026-10-gateway-a.csv"] += (
        'api-81001,C13,api_calls,3100,2026-10-15T00:20:00+02:00,\n'
        'api-81002,C10,api_calls,880000,2026-10-15T00:20:00-04:00,\n'
        'api-81003,C04,api_calls,1500,2026-11-03T00:10:00+00:00,\n'
        'api-81004,C09,api_calls,450000,2026-11-03T00:10:00+01:00,\n'
        'api-91001,C04,api_calls,1200,2026-10-20 10:00:00,\n'
        'api-91002,C07,api_calls,12.5.1,2026-10-20T10:00:00Z,\n'
    )
    files["feeds/2026-10-seats.log"] += '2026-10-15T10:00:00+02:00 event=se-91001 cust=C13 metric=seats qty=many\n'
    return files


ENTITIES = '''# Legal entities (Group finance, 2025-10)

[entities.KC-US]
name = "Kettle Cloud Inc."
functional_currency = "USD"
currencies = ["USD", "CAD", "JPY", "AUD"]

[entities.KC-EU]
name = "Kettle Cloud B.V."
functional_currency = "EUR"
currencies = ["EUR", "CHF", "SEK"]

[entities.KC-UK]
name = "Kettle Cloud Ltd"
functional_currency = "GBP"
currencies = ["GBP"]

[group]
presentation_currency = "USD"
parent = "KC-US"
'''


def payments_csv(rows):
    return csv_rows([["payment_id", "customer", "currency", "amount", "received", "reference"]] + rows)


def build(which):
    files = build_visible() if which == "visible" else build_hidden()
    files["entities.toml"] = ENTITIES
    if which == "visible":
        files["payments.csv"] = payments_csv([
            ["P-3001", "C04", "GBP", "200.00", "2026-02-20", "KC-2026-01-C04 part"],
            ["P-3002", "C05", "JPY", "5000", "2026-03-15", "KC-2026-01-C05"],
            ["P-3003", "C06", "SEK", "10000.00", "2026-01-25", "on account"],
            ["P-3004", "C12", "USD", "300.00", "2026-03-20", "KC-2026-01-C12"],
            ["P-3005", "C01", "USD", "400.00", "2026-03-28", "Feb"],
            ["P-3006", "C14", "USD", "100.00", "2026-03-30", "Feb part"],
            ["P-3007", "C09", "CHF", "50.00", "2026-02-10", "unidentified"],
            ["P-3008", "C08", "AUD", "20.00", "2026-03-12", "fees"],
        ])
    else:
        files["payments.csv"] = payments_csv([
            ["P-4001", "C04", "GBP", "150.00", "2026-09-25", "Aug part"],
            ["P-4002", "C13", "EUR", "700.00", "2026-10-05", "KC-2026-08-C13"],
            ["P-4003", "C07", "USD", "120.00", "2026-09-30", ""],
            ["P-4004", "C02", "EUR", "250.00", "2026-10-28", "Sep"],
            ["P-4005", "C09", "CHF", "400.00", "2026-10-10", "Sep part"],
            ["P-4006", "C08", "AUD", "800.00", "2026-08-25", "July"],
            ["P-4007", "C14", "USD", "45.00", "2026-10-20", ""],
            ["P-4008", "C05", "JPY", "12000", "2026-09-14", "deposit"],
        ])
    return files
