import datetime as dt, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from decimal import Decimal
from app.dates import *

D = dt.date

# fin de mes: ancla 31 de enero
s = D(2026, 1, 31)
assert occurrence(s, 1, "month", 1) == D(2026, 2, 28)
assert occurrence(s, 1, "month", 2) == D(2026, 3, 31)      # vuelve al 31, no se arrastra al 28
assert occurrence(s, 1, "month", 3) == D(2026, 4, 30)
assert occurrence(D(2027, 1, 31), 1, "month", 1) == D(2027, 2, 28)
assert occurrence(D(2023, 1, 31), 1, "month", 13) == D(2024, 2, 29)   # bisiesto
# anual desde 29 de febrero
assert occurrence(D(2024, 2, 29), 1, "year", 1) == D(2025, 2, 28)
assert occurrence(D(2024, 2, 29), 1, "year", 4) == D(2028, 2, 29)
# trimestral
assert occurrence(D(2026, 11, 30), 3, "month", 1) == D(2027, 2, 28)
assert occurrence(D(2026, 11, 30), 3, "month", 2) == D(2027, 5, 30)
# cambio de año
assert occurrence(D(2026, 12, 15), 1, "month", 1) == D(2027, 1, 15)
# semanas y días
assert occurrence(D(2026, 1, 1), 2, "week", 1) == D(2026, 1, 15)
assert occurrence(D(2026, 1, 1), 30, "day", 2) == D(2026, 3, 2)

# próxima renovación: pasado, hoy, futuro
assert next_on_or_after(D(2026, 1, 31), 1, "month", D(2026, 2, 1)) == D(2026, 2, 28)
assert next_on_or_after(D(2026, 1, 31), 1, "month", D(2026, 2, 28)) == D(2026, 2, 28)   # hoy cuenta
assert next_on_or_after(D(2026, 1, 31), 1, "month", D(2026, 3, 1)) == D(2026, 3, 31)
assert next_on_or_after(D(2030, 5, 5), 1, "month", D(2026, 1, 1)) == D(2030, 5, 5)     # inicio futuro
assert next_on_or_after(D(2020, 2, 29), 1, "year", D(2026, 11, 10)) == D(2027, 2, 28)
assert next_on_or_after(D(2000, 1, 1), 1, "day", D(2026, 11, 10)) == D(2026, 11, 10)
# vencida hace años: salta a la próxima futura
assert next_on_or_after(D(2015, 3, 17), 1, "month", D(2026, 11, 10)) == D(2026, 11, 17)
assert next_on_or_after(D(2015, 3, 17), 2, "week", D(2026, 11, 10)) >= D(2026, 11, 10)

# propiedad: nunca devuelve algo anterior a `day`, y es mínima
import random
random.seed(1)
for _ in range(3000):
    st = D(2018, 1, 1) + dt.timedelta(days=random.randint(0, 3000))
    n = random.randint(1, 14); u = random.choice(UNITS)
    day = D(2024, 1, 1) + dt.timedelta(days=random.randint(0, 1500))
    k = first_index_not_before(st, n, u, day)
    assert occurrence(st, n, u, k) >= day
    assert k == 0 or occurrence(st, n, u, k - 1) < day, (st, n, u, day)

# rangos
r = occurrences_between(D(2026, 1, 31), 1, "month", D(2026, 11, 10), D(2027, 11, 10))
assert len(r) == 12 and r[0] == D(2026, 11, 30) and r[-1] == D(2027, 10, 31), r
assert all(a < b for a, b in zip(r, r[1:]))

# equivalencia anual
assert annual_factor(1, "month") == 12 and annual_factor(3, "month") == 4
assert annual_factor(1, "year") == 1 and annual_factor(2, "year") == Decimal("0.5")
assert annual_factor(1, "week") == 52
print("dates OK")
