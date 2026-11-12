import calendar
import datetime as dt
from decimal import Decimal
from .core import q, today
from .dates import next_on_or_after, occurrences_between, annual_factor
from .money import convert, load_rates

CATEGORIES = ["Streaming", "Música", "Software", "Nube y hosting", "Dominios", "Juegos", "Noticias y revistas",
              "Salud y deporte", "Seguros", "Telefonía e internet", "Educación", "Otros"]
MESES_ES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
UNIT_ES = {"day": "día", "week": "semana", "month": "mes", "year": "año"}
UNIT_PL = {"day": "días", "week": "semanas", "month": "meses", "year": "años"}


def d(s):
    return dt.date.fromisoformat(s) if s else None


def period_text(n, unit):
    return f"cada {UNIT_ES[unit]}" if n == 1 else f"cada {n} {UNIT_PL[unit]}"


def enrich(s, day, rates, base):
    """Añade a una suscripción: próxima renovación, coste anual/mensual (en su moneda y en la base) y estado de prueba."""
    s = dict(s)
    start, trial = d(s["start_date"]), d(s["trial_end"])
    s["in_trial"] = bool(trial and trial >= day)
    s["next"] = next_on_or_after(start, s["period_n"], s["period_unit"], day) if s["status"] == "activa" else None
    s["days_left"] = (s["next"] - day).days if s["next"] else None
    s["period_text"] = period_text(s["period_n"], s["period_unit"])
    annual = Decimal(s["amount_cents"]) * annual_factor(s["period_n"], s["period_unit"])
    s["annual_own"], s["monthly_own"] = annual, annual / 12
    a = convert(annual, s["currency"], base, rates)
    s["annual"], s["monthly"] = a, (a / 12 if a is not None else None)
    s["converted"] = s["currency"] != base and a is not None
    s["counts"] = s["status"] == "activa" and not s["in_trial"]    # entra en el gasto actual
    return s


def user_subs(user, day=None):
    day = day or today()
    rates = load_rates()
    return [enrich(s, day, rates, user["base_currency"]) for s in
            q("SELECT * FROM subs WHERE user_id=? ORDER BY lower(name)", (user["id"],))], rates


def month_end(y, m):
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def next_months(day, n):
    """Los n meses naturales siguientes al de `day`: [(año, mes)]."""
    out, y, m = [], day.year, day.month
    for _ in range(n):
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        out.append((y, m))
    return out


def dashboard(user, day=None, months=3):
    day = day or today()
    base = user["base_currency"]
    subs, rates = user_subs(user, day)
    active = [s for s in subs if s["status"] == "activa"]
    counting = [s for s in active if s["counts"]]
    total_annual = sum((s["annual"] for s in counting if s["annual"] is not None), Decimal(0))
    missing = [s for s in counting if s["annual"] is None]

    by_cat = {}
    for s in counting:
        if s["annual"] is not None:
            by_cat[s["category"]] = by_cat.get(s["category"], Decimal(0)) + s["annual"]
    cats = sorted(by_cat.items(), key=lambda x: -x[1])

    top = sorted([s for s in counting if s["annual"] is not None], key=lambda s: -s["annual"])[:5]
    upcoming = sorted(active, key=lambda s: s["next"])[:8]

    # Cobros reales de los próximos meses naturales (incluye el primer cobro tras una prueba gratuita).
    # Los importes se convierten a la moneda base con el tipo de cambio de hoy.
    base_cur = user["base_currency"]
    keys = next_months(day, months)
    proj = {k: Decimal(0) for k in keys}
    next30 = Decimal(0)                     # cobros de los próximos 30 días
    rest = Decimal(0)                       # lo que queda por cobrar de lo que resta del mes actual
    skipped = 0
    for s in active:
        c = convert(s["amount_cents"], s["currency"], base_cur, rates)
        if c is None:
            skipped += 1
            continue
        st = d(s["start_date"])
        for o in occurrences_between(st, s["period_n"], s["period_unit"], day, month_end(day.year, day.month)):
            rest += c
        for o in occurrences_between(st, s["period_n"], s["period_unit"], day, day + dt.timedelta(days=30)):
            next30 += c
        for o in occurrences_between(st, s["period_n"], s["period_unit"], dt.date(keys[0][0], keys[0][1], 1),
                                     month_end(*keys[-1])):
            proj[(o.year, o.month)] += c
    return dict(subs=subs, active=active, total_annual=total_annual, total_monthly=total_annual / 12,
                missing=missing, cats=cats, top=top, upcoming=upcoming,
                trials=[s for s in active if s["in_trial"]], projection=list(proj.items()), rest_of_month=rest, next30=next30,
                proj_skipped=skipped, months=months,
                n_paused=len([s for s in subs if s["status"] == "pausada"]), base=base)
