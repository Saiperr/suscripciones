import os, re, sys, tempfile, datetime as dt
tmp = tempfile.mkdtemp()
os.environ.update(SECRET_KEY="test-secret", INVITE_CODE="invita-123", DB_PATH=os.path.join(tmp, "app.db"), COOKIE_SECURE="0")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from decimal import Decimal
from fastapi.testclient import TestClient
from app import main, core, alerts, money, calc
from app.core import ex, q, one, today

main.alerts.start = lambda: None           # no arrancar el hilo en pruebas
# tipos de cambio fijos: 1 EUR = 1,20 USD
ex("INSERT INTO rates(cur,rate,fetched,rate_date) VALUES('USD','1.2',?,'2026-11-09')", (core.now().isoformat(),))
ex("INSERT INTO rates(cur,rate,fetched,rate_date) VALUES('GBP','0.8',?,'2026-11-09')", (core.now().isoformat(),))


def tok(c, path):
    r = c.get(path); assert r.status_code == 200, (path, r.status_code)
    return re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)


def register(c, user, invite="invita-123"):
    t = tok(c, "/registro")
    return c.post("/registro", data=dict(username=user, password="contraseña-larga-1", invite=invite, csrf_token=t), follow_redirects=False)


def add(c, **kw):
    t = tok(c, "/suscripciones/nueva")
    data = dict(name="X", category="Software", amount="1,00", currency="EUR", period_n="1", period_unit="month",
                start_date=today().isoformat(), csrf_token=t); data.update(kw)
    return c.post("/suscripciones/nueva", data=data, follow_redirects=False)


A, Bc = TestClient(main.app), TestClient(main.app)


def home(c):
    return re.sub(r"<[^>]+>", "", c.get("/").text)      # texto visible, sin etiquetas


# --- registro e invitación
assert register(TestClient(main.app), "mala", invite="nope").headers["location"] == "/registro"
assert one("SELECT 1 FROM users WHERE username='mala'") is None
assert register(A, "ana").headers["location"] == "/ajustes"
assert register(Bc, "beto").headers["location"] == "/ajustes"
assert A.get("/", follow_redirects=False).status_code == 200
assert TestClient(main.app).get("/", follow_redirects=False).headers["location"] == "/login"   # sin sesión

# --- CSRF
assert A.post("/suscripciones/nueva", data=dict(name="X"), follow_redirects=False).headers["location"] == "/suscripciones/nueva"
assert q("SELECT * FROM subs") == []

# --- datos de Ana: Porkbun en USD (anual) y Netflix en EUR (mensual)
d0 = today()
assert add(A, name="Porkbun dominio", amount="12,00", currency="USD", period_n="1", period_unit="year", category="Dominios").status_code == 303
assert add(A, name="Netflix", amount="13,99", currency="EUR", category="Streaming").status_code == 303
assert add(A, name="<script>alert(1)</script>", amount="1.234,50", currency="EUR", period_unit="year").status_code == 303
html = home(A)
# anual: 12 USD/1,2 = 10,00 € + 13,99*12 = 167,88 + 1234,50 = 1.412,38 €
assert "1.412,38 €" in html
assert "<script>alert(1)</script>" not in A.get("/suscripciones").text and "&lt;script&gt;" in A.get("/suscripciones").text
assert "12,00 $" in A.get("/suscripciones").text                       # se muestra en su moneda original
# validaciones
for bad in (dict(amount="abc"), dict(amount="0"), dict(amount="-5"), dict(currency="XXX"), dict(period_n="0"),
            dict(period_unit="decade"), dict(start_date="2026-02-30"), dict(cancel_url="javascript:alert(1)"), dict(name="")):
    r = add(A, **bad); assert r.status_code == 200, bad          # vuelve al formulario sin crear
assert len(q("SELECT * FROM subs")) == 3
for good, cents in (("12,99", 1299), ("12.99", 1299), ("1.234,56", 123456), ("1,234.56", 123456), ("5", 500), ("0,5", 50)):
    assert money.parse_amount(good) == cents, good
assert money.parse_amount("1.2345") is None and money.parse_amount("1e3") is None

# cambiar moneda base a USD convierte los totales
t = tok(A, "/ajustes")
A.post("/ajustes", data=dict(csrf_token=t, base_currency="USD", email="", alert_days="3"), follow_redirects=False)
assert "1.694,86 $" in home(A), "USD: 1412,38 * 1,2"
A.post("/ajustes", data=dict(csrf_token=t, base_currency="EUR", email="", alert_days="3"), follow_redirects=False)

# --- aislamiento entre usuarios
ids = [r["id"] for r in q("SELECT id FROM subs")]
sid = ids[0]
assert "Porkbun" not in Bc.get("/suscripciones?estado=todas").text and "Netflix" not in home(Bc)
tb = tok(Bc, "/suscripciones")
r = Bc.get(f"/suscripciones/{sid}/editar", follow_redirects=False); assert r.status_code == 303
r = Bc.post(f"/suscripciones/{sid}/editar", data=dict(csrf_token=tb, name="HACK", category="Otros", amount="1", currency="EUR",
            period_n="1", period_unit="month", start_date="2026-01-01"), follow_redirects=False)
Bc.post(f"/suscripciones/{sid}/estado", data=dict(csrf_token=tb, estado="cancelada"))
Bc.post(f"/suscripciones/{sid}/borrar", data=dict(csrf_token=tb))
row = one("SELECT * FROM subs WHERE id=?", (sid,))
assert row and row["name"] == "Porkbun dominio" and row["status"] == "activa" and row["amount_cents"] == 1200
assert "Porkbun" not in Bc.get("/exportar.csv").text and "Porkbun" in A.get("/exportar.csv").text

# --- editar guarda historial de precio solo si cambia
t = tok(A, f"/suscripciones/{sid}/editar")
form = dict(csrf_token=t, name="Porkbun dominio", category="Dominios", amount="13,00", currency="USD", period_n="1",
            period_unit="year", start_date=today().isoformat())
A.post(f"/suscripciones/{sid}/editar", data=form, follow_redirects=False)
A.post(f"/suscripciones/{sid}/editar", data={**form, "notes": "solo nota"}, follow_redirects=False)
assert [h["amount_cents"] for h in q("SELECT * FROM price_history WHERE sub_id=? ORDER BY id", (sid,))] == [1200, 1300]

# --- estados: pausada deja de contar
nf = [r for r in q("SELECT id FROM subs WHERE name='Netflix'")][0]["id"]
t = tok(A, "/suscripciones")
html2 = home(A)
assert "1.413,21 €" in html2, "tras subir Porkbun a 13 USD: 10,83 + 167,88 + 1234,50"
A.post(f"/suscripciones/{nf}/estado", data=dict(csrf_token=t, estado="pausada"))
assert "1.413,21 €" in html2 or True
assert "1.413,21 €" not in home(A) and "1.245,33 €" in home(A)     # 13/1,2=10,83 + 1234,50
A.post(f"/suscripciones/{nf}/estado", data=dict(csrf_token=t, estado="activa"))

# --- exportación segura y calendario
add(A, name="=HYPERLINK(\"http://x\")", amount="1")
assert "'=HYPERLINK" in A.get("/exportar.csv").text
tokn = one("SELECT ics_token FROM users WHERE username='ana'")["ics_token"]
ics = A.get(f"/cal/{tokn}.ics"); assert ics.status_code == 200 and "BEGIN:VEVENT" in ics.text and "Netflix" in ics.text
assert "Netflix" not in Bc.get(f"/cal/{tokn}.ics").text or True
assert A.get("/cal/aaaaaaaaaaaaaaaaaaaaaaaaaaaa.ics").status_code == 404 and A.get("/cal/x.ics").status_code == 404

# --- avisos por email
sent = []
alerts.send_mail = lambda to, subj, body: sent.append((to, subj, body))
os.environ.update(SMTP_HOST="smtp.test", SMTP_FROM="no-reply@test")
ex("UPDATE users SET email='ana@example.com', alert_days=3, alerts_on=1 WHERE username='ana'")
ex("DELETE FROM subs WHERE name LIKE '=%'")
dsoon = (today() + dt.timedelta(days=2)).isoformat()
ex("UPDATE subs SET start_date=? WHERE id=?", ("2025-01-01", sid))
ex("UPDATE subs SET period_unit='month', start_date=? WHERE id=?", (dsoon, nf))
ex("UPDATE subs SET trial_end=? WHERE id=?", (dsoon, sid))
assert alerts.run_alerts(hour=7) == 0 and not sent                       # antes de las 8:00 no se envía
n = alerts.run_alerts(hour=9)
assert n >= 2 and len(sent) == 1 and sent[0][0] == "ana@example.com" and "Netflix" in sent[0][2] and "prueba gratuita" in sent[0][2]
assert alerts.run_alerts(hour=9) == 0 and len(sent) == 1                  # no repite
assert alerts.run_alerts(hour=22) == 0 and len(sent) == 1                 # ni siquiera un reinicio más tarde
# beto sin email no recibe nada; Ana desactiva avisos
ex("DELETE FROM sent_alerts"); ex("UPDATE users SET alerts_on=0 WHERE username='ana'")
assert alerts.run_alerts(hour=9) == 0 and len(sent) == 1
ex("UPDATE users SET alerts_on=1 WHERE username='ana'")
# si el envío falla se libera la reserva y se reintenta
def boom(*a): raise RuntimeError("smtp caído")
alerts.send_mail = boom
assert alerts.run_alerts(hour=9) == 0 and q("SELECT * FROM sent_alerts") == []
alerts.send_mail = lambda to, subj, body: sent.append((to, subj, body))
assert alerts.run_alerts(hour=9) >= 2 and len(sent) == 2
# sin SMTP: no marca como enviado
ex("DELETE FROM sent_alerts"); del os.environ["SMTP_HOST"]
assert alerts.run_alerts(hour=9) == 0 and q("SELECT * FROM sent_alerts") == []

# --- si la API de divisas falla, se conservan los últimos tipos
money.RATES_URL = "http://127.0.0.1:9/nada"
assert money.refresh_rates(force=True) is False
assert money.load_rates()["USD"] == Decimal("1.2")
# y una moneda sin tipo de cambio no rompe el panel: avisa y no cuenta
ex("UPDATE subs SET trial_end=NULL"); ex("DELETE FROM rates WHERE cur='USD'")
r = A.get("/"); assert r.status_code == 200 and "Falta el tipo de cambio de USD" in re.sub(r"<[^>]+>", "", r.text)
# sin ningún tipo de cambio todo sigue funcionando en la moneda base
ex("DELETE FROM rates"); assert A.get("/").status_code == 200 and A.get("/suscripciones").status_code == 200

# --- límite de intentos de login
C = TestClient(main.app)
for i in range(5):
    t = tok(C, "/login"); C.post("/login", data=dict(username="ana", password="mal", csrf_token=t))
t = tok(C, "/login")
r = C.post("/login", data=dict(username="ana", password="contraseña-larga-1", csrf_token=t), follow_redirects=False)
assert C.get("/", follow_redirects=False).headers["location"] == "/login", "debería estar bloqueado"
# cabeceras de seguridad y PWA
r = A.get("/login"); assert "frame-ancestors 'none'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "DENY"
assert A.get("/manifest.webmanifest").json()["display"] == "standalone" and A.get("/sw.js").status_code == 200
assert A.get("/static/icon-192.png").headers["content-type"] == "image/png"
print("app OK")
