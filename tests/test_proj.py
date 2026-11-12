import os, sys, tempfile, datetime as dt
os.environ.update(SECRET_KEY="x", INVITE_CODE="i", DB_PATH=os.path.join(tempfile.mkdtemp(), "a.db"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from decimal import Decimal
from app.core import ex, init_db, one
from app import calc
init_db()
ex("INSERT INTO rates(cur,rate,fetched,rate_date) VALUES('USD','1.2','x','x')")
ex("INSERT INTO users(id,username,pw_hash,ics_token) VALUES(1,'a','h','t1'),(2,'b','h','t2')")
def sub(uid, name, cents, cur, n, unit, start, status="activa", trial=None):
    ex("INSERT INTO subs(user_id,name,category,amount_cents,currency,period_n,period_unit,start_date,trial_end,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
       (uid, name, "Otros", cents, cur, n, unit, start, trial, status))
sub(1, "Netflix", 1399, "EUR", 1, "month", "2026-11-20")     # 20/11, 20/12, 20/01, 20/02
sub(1, "Seguro", 9000, "EUR", 1, "year", "2026-12-05")       # solo 5/12
sub(1, "Porkbun", 1200, "USD", 1, "year", "2027-01-31")      # 12 USD = 10 EUR el 31/01
sub(1, "Fin de mes", 500, "EUR", 1, "month", "2026-01-31")   # 30/11, 31/12, 31/01, 28/02
sub(1, "Pausada", 99900, "EUR", 1, "month", "2026-11-15", status="pausada")
sub(1, "Cancelada", 99900, "EUR", 1, "month", "2026-11-15", status="cancelada")
sub(2, "Ajena", 77700, "EUR", 1, "month", "2026-11-15")
u = one("SELECT * FROM users WHERE id=1")
day = dt.date(2026, 11, 12)
dash = calc.dashboard(u, day=day, months=3)
got = {k: v for k, v in dash["projection"]}
assert list(got) == [(2026, 12), (2027, 1), (2027, 2)], list(got)
assert got[(2026, 12)] == Decimal(1399 + 9000 + 500), got      # dic: Netflix + Seguro + Fin de mes
assert got[(2027, 1)] == Decimal(1399 + 1000 + 500), got       # ene: Netflix + Porkbun(10 €) + Fin de mes
assert got[(2027, 2)] == Decimal(1399 + 500), got              # feb: Netflix + Fin de mes (28/02)
assert dash["rest_of_month"] == Decimal(1399 + 500), dash["rest_of_month"]   # resto de nov: 20/11 y 30/11
# 12 meses cruza el año y no se sale del rango
d12 = calc.dashboard(u, day=dt.date(2026, 12, 20), months=12)
ks = [k for k, _ in d12["projection"]]
assert ks[0] == (2027, 1) and ks[-1] == (2027, 12) and len(ks) == 12
assert calc.next_months(dt.date(2026, 12, 31), 2) == [(2027, 1), (2027, 2)]
# la prueba gratuita no cuenta en el gasto actual, pero su cobro posterior sí está en la gráfica
sub(1, "Prueba", 1000, "EUR", 1, "month", "2026-12-10", trial="2026-12-10")
d = calc.dashboard(u, day=day, months=3)
assert dict(d["projection"])[(2026, 12)] == Decimal(1399 + 9000 + 500 + 1000)
# sin tipo de cambio: se omite y se avisa, sin romper
ex("DELETE FROM rates"); d = calc.dashboard(u, day=day, months=3)
assert d["proj_skipped"] == 1
print("proyección OK")
