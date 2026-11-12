"""Importes en céntimos enteros; conversión solo al mostrar. Tipos de cambio del BCE vía Frankfurter, con caché en SQLite."""
import re, logging, datetime as dt
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import httpx
from .core import q, one, ex, now, _lock, conn
from contextlib import closing

log = logging.getLogger("suscripciones")
RATES_URL = "https://api.frankfurter.dev/v1/latest?base=EUR"

SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥", "CNY": "CN¥", "INR": "₹", "KRW": "₩"}
# Monedas que ofrece el BCE (más EUR). Si falta el tipo de cambio de alguna, se muestra sin convertir.
CURRENCIES = ["EUR", "USD", "GBP", "CHF", "JPY", "CAD", "AUD", "NZD", "MXN", "BRL", "SEK", "NOK", "DKK", "PLN",
              "CZK", "HUF", "RON", "BGN", "TRY", "CNY", "HKD", "SGD", "KRW", "INR", "ZAR", "ILS", "THB", "MYR",
              "PHP", "IDR", "ISK"]
MAX_CENTS = 100_000_000   # 1.000.000,00


def parse_amount(text):
    """'12,99' / '1.234,56' / '12.99' -> céntimos (int) o None si no es válido."""
    t = (text or "").strip().replace(" ", "")
    if not re.fullmatch(r"\d{1,9}([.,]\d{1,2})?|\d{1,3}([.]\d{3})+(,\d{1,2})?|\d{1,3}(,\d{3})+([.]\d{1,2})?", t):
        return None
    if re.fullmatch(r"\d{1,3}([.]\d{3})+(,\d{1,2})?", t):          # 1.234,56
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+([.]\d{1,2})?", t):        # 1,234.56
        t = t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        c = int((Decimal(t) * 100).quantize(Decimal(1), ROUND_HALF_UP))
    except InvalidOperation:
        return None
    return c if 0 < c <= MAX_CENTS else None


def fmt(cents, cur):
    """Céntimos (int/Decimal) -> '1.234,56 €'."""
    if cents is None:
        return "—"
    v = (Decimal(cents) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} {SYMBOLS.get(cur, cur)}"


def fmt_plain(cents):
    v = (Decimal(cents) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return f"{v:.2f}"


# ---------- tipos de cambio ----------
def load_rates():
    """{moneda: unidades por 1 EUR}. Vacío si nunca se obtuvo ninguno."""
    rows = q("SELECT cur, rate FROM rates")
    r = {x["cur"]: Decimal(x["rate"]) for x in rows}
    if r:
        r["EUR"] = Decimal(1)
    return r


def rates_info():
    return one("SELECT MAX(fetched) AS fetched, MAX(rate_date) AS rate_date FROM rates")


def refresh_rates(force=False):
    """Descarga y guarda los tipos. Si falla, se conservan los últimos conocidos (no se lanza excepción)."""
    info = rates_info()
    if not force and info and info["fetched"]:
        try:
            if now() - dt.datetime.fromisoformat(info["fetched"]) < dt.timedelta(hours=20):
                return True
        except ValueError:
            pass
    try:
        r = httpx.get(RATES_URL, timeout=10, follow_redirects=True)
        r.raise_for_status()
        data = r.json()
        rates = {k: Decimal(str(v)) for k, v in data["rates"].items()
                 if re.fullmatch(r"[A-Z]{3}", k) and Decimal(str(v)) > 0}
        if len(rates) < 10 or "USD" not in rates:
            raise ValueError("respuesta incompleta")
        stamp, rdate = now().isoformat(), str(data.get("date", ""))[:10]
        with _lock, closing(conn()) as c:
            c.executemany("INSERT INTO rates(cur,rate,fetched,rate_date) VALUES(?,?,?,?) "
                          "ON CONFLICT(cur) DO UPDATE SET rate=excluded.rate, fetched=excluded.fetched, rate_date=excluded.rate_date",
                          [(k, str(v), stamp, rdate) for k, v in rates.items()])
            c.commit()
        log.info("tipos de cambio actualizados (%d monedas, fecha %s)", len(rates), rdate)
        return True
    except Exception as e:
        log.warning("no se pudieron actualizar los tipos de cambio: %s", e)
        return False


def convert(amount, cur, base, rates):
    """amount (céntimos, Decimal) de `cur` a `base`. None si falta algún tipo de cambio."""
    if cur == base:
        return Decimal(amount)
    if cur not in rates or base not in rates:
        return None
    return Decimal(amount) / rates[cur] * rates[base]
