"""Cálculo de renovaciones. Todo el calendario se deriva de la fecha de inicio (ancla):
una suscripción mensual iniciada el 31 renueva el 28/29 en febrero y vuelve al 31 en marzo."""
import calendar
import datetime as dt
from decimal import Decimal

UNITS = ("day", "week", "month", "year")
UNIT_LABEL = {"day": "día(s)", "week": "semana(s)", "month": "mes(es)", "year": "año(s)"}


def add_months(d, months):
    """Suma meses a `d` usando como ancla d.day (recortada al último día del mes destino)."""
    idx = d.year * 12 + (d.month - 1) + months
    y, m = divmod(idx, 12)
    m += 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def occurrence(start, n, unit, k):
    """Fecha del cobro número k (k=0 es el inicio)."""
    if unit == "day":
        return start + dt.timedelta(days=n * k)
    if unit == "week":
        return start + dt.timedelta(days=7 * n * k)
    if unit == "month":
        return add_months(start, n * k)
    if unit == "year":
        return add_months(start, 12 * n * k)
    raise ValueError(unit)


_MAX_DAYS = {"day": 1, "week": 7, "month": 31, "year": 366}


def first_index_not_before(start, n, unit, day):
    """Menor k >= 0 con occurrence(k) >= day."""
    if day <= start:
        return 0
    # Cota inferior segura: con k0 periodos de duración máxima aún no se ha pasado de `day`.
    k = max(0, (day - start).days // (n * _MAX_DAYS[unit]))
    while occurrence(start, n, unit, k) < day:
        k += 1
    return k


def next_on_or_after(start, n, unit, day):
    return occurrence(start, n, unit, first_index_not_before(start, n, unit, day))


def occurrences_between(start, n, unit, a, b, limit=500):
    """Cobros con a <= fecha <= b."""
    out = []
    k = first_index_not_before(start, n, unit, a)
    while len(out) < limit:
        d = occurrence(start, n, unit, k)
        if d > b:
            break
        out.append(d)
        k += 1
    return out


def annual_factor(n, unit):
    """Cobros por año (Decimal): importe * factor = coste anual."""
    n = Decimal(n)
    return {"day": Decimal(365) / n, "week": Decimal(52) / n,
            "month": Decimal(12) / n, "year": Decimal(1) / n}[unit]
