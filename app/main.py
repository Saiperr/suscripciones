import os, re, csv, io, secrets, time, datetime as dt
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse
from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, Response, PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .core import q, one, ex, init_db, now, today
from .calc import dashboard, user_subs, enrich, CATEGORIES, UNIT_ES, MESES_ES, d
from .dates import UNITS, occurrences_between
from .money import parse_amount, fmt, fmt_plain, CURRENCIES, SYMBOLS, load_rates, rates_info, refresh_rates
from . import alerts

HERE = os.path.dirname(__file__)
init_db()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=os.environ["SECRET_KEY"], same_site="lax",
                   https_only=os.environ.get("COOKIE_SECURE", "0") == "1", max_age=60 * 60 * 24 * 30)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))
templates.env.filters["money"] = fmt
templates.env.filters["money0"] = lambda c, cur: fmt((Decimal(c) / 100).quantize(Decimal(1), ROUND_HALF_UP) * 100, cur).replace(",00", "")
AVATARS = [("#7c5cff", "#4f8cf7"), ("#22d3ee", "#3b82f6"), ("#f472b6", "#c026d3"), ("#fb923c", "#ef4444"),
           ("#2dd4bf", "#0ea5e9"), ("#a78bfa", "#ec4899"), ("#fbbf24", "#f97316"), ("#60a5fa", "#6366f1")]
templates.env.filters["avgrad"] = lambda n: "linear-gradient(135deg,%s,%s)" % AVATARS[sum((i + 7) * ord(ch) for i, ch in enumerate(str(n))) * 37 % len(AVATARS)]
templates.env.filters["hue"] = lambda n: sum((i + 7) * ord(ch) for i, ch in enumerate(str(n))) * 37 % 360
templates.env.filters["initial"] = lambda n: (re.sub(r"[^\wÁÉÍÓÚÜÑáéíóúüñ]", "", str(n)) or "?")[0].upper()
templates.env.filters["fecha"] = lambda x: x.strftime("%d/%m/%Y") if x else ""
templates.env.filters["corta"] = lambda x: f"{x.day} {MESES_ES[x.month - 1][:3].lower()}" if x else ""
templates.env.filters["dt"] = lambda s: dt.date.fromisoformat(s).strftime("%d/%m/%Y") if s else ""
ph = PasswordHasher()
import hashlib
# Versión de los ficheros estáticos en la URL (?v=…): cualquier caché (navegador, Cloudflare) pide el fichero nuevo al cambiar.
templates.env.globals["asset_v"] = hashlib.sha1(b"".join(open(os.path.join(HERE, "static", f), "rb").read() for f in ("style.css", "app.js"))).hexdigest()[:10]
INVITE = os.environ.get("INVITE_CODE", "")
FAILS = {}
WINDOW = 600
MAIL_TEST = {}


@app.middleware("http")
async def security(request: Request, call_next):
    try:
        if int(request.headers.get("content-length") or 0) > 64 * 1024:
            return PlainTextResponse("Petición demasiado grande", status_code=413)
    except ValueError:
        return PlainTextResponse("Petición no válida", status_code=400)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                               "script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
    if request.url.path not in ("/sw.js",) and not request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.on_event("startup")
def _start():
    alerts.start()


# ---------- utilidades ----------
def client_ip(request):
    return request.client.host if request.client else "?"


def blocked(keys_limits):
    t = time.time()
    for k in [k for k, v in FAILS.items() if not any(x > t - WINDOW for x in v)]:
        FAILS.pop(k, None)
    return any(len([x for x in FAILS.get(k, []) if x > t - WINDOW]) >= m for k, m in keys_limits)


def register_fail(keys):
    t = time.time()
    for k in keys:
        FAILS[k] = [x for x in FAILS.get(k, []) if x > t - WINDOW] + [t]


def csrf(request):
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(24)
    return request.session["csrf"]


def check_csrf(request, token):
    if not token or not secrets.compare_digest(str(token), request.session.get("csrf", "")):
        raise PermissionError


def getuser(request):
    uid = request.session.get("uid")
    return one("SELECT * FROM users WHERE id=?", (uid,)) if uid else None


def flash(request, msg, kind="ok"):
    request.session["flash"] = {"msg": msg, "kind": kind}


def go(path):
    return RedirectResponse(path, status_code=303)


DONUT = ["#7c5cff", "#22d3ee", "#34d399", "#fbbf24", "#f472b6", "#60a5fa", "#fb923c", "#a3e635", "#c084fc", "#2dd4bf", "#f87171", "#94a3b8"]
DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def donut_data(cats):
    """Segmentos de la rosca SVG (circunferencia = 100 unidades)."""
    tot = sum((v for _, v in cats), Decimal(0)) or Decimal(1)
    out, acc = [], 0.0
    for i, (name, v) in enumerate(cats):
        pct = float(v / tot * 100)
        out.append(dict(name=name, value=v, pct=round(pct, 1), seg=round(max(pct - (0.8 if len(cats) > 1 else 0), 0.1), 2),
                        off=round(25 - acc, 2), color=DONUT[i % len(DONUT)]))
        acc += pct
    return out


def render(request, name, **ctx):
    ctx.update(user=getuser(request), csrf=csrf(request), flash=request.session.pop("flash", None))
    return templates.TemplateResponse(request, name, ctx)


async def post_form(request):
    """Lee el formulario y valida el CSRF. Devuelve el formulario o None (con aviso ya puesto)."""
    form = await request.form()
    try:
        check_csrf(request, form.get("csrf_token"))
    except PermissionError:
        flash(request, "Sesión caducada, inténtalo de nuevo.", "err")
        return None
    return form


def new_token():
    return secrets.token_urlsafe(24)


# ---------- acceso ----------
@app.get("/login")
def login_page(request: Request):
    return render(request, "login.html")


@app.post("/login")
def login_post(request: Request, username: str = Form(""), password: str = Form(""), csrf_token: str = Form("")):
    try:
        check_csrf(request, csrf_token)
    except PermissionError:
        flash(request, "Sesión caducada, inténtalo de nuevo.", "err"); return go("/login")
    ip, uname = client_ip(request), username.strip().lower()[:64]
    keys = [((ip, uname), 5), ((ip, "*"), 15), (("*", uname), 20)]
    if blocked(keys):
        flash(request, "Demasiados intentos. Espera 10 minutos.", "err"); return go("/login")
    u = one("SELECT * FROM users WHERE username=?", (uname,))
    try:
        if not u:
            raise VerifyMismatchError()
        ph.verify(u["pw_hash"], password)
    except VerifyMismatchError:
        register_fail([k for k, _ in keys])
        flash(request, "Usuario o contraseña incorrectos.", "err"); return go("/login")
    request.session.clear()
    request.session["uid"] = u["id"]
    return go("/")


@app.get("/registro")
def reg_page(request: Request):
    return render(request, "registro.html")


@app.post("/registro")
def reg_post(request: Request, username: str = Form(""), password: str = Form(""), invite: str = Form(""),
             csrf_token: str = Form("")):
    try:
        check_csrf(request, csrf_token)
    except PermissionError:
        flash(request, "Sesión caducada, inténtalo de nuevo.", "err"); return go("/registro")
    username = username.strip().lower()
    keys = [((client_ip(request), "registro"), 5), (("*", "registro"), 30)]
    if blocked(keys):
        flash(request, "Demasiados intentos. Espera 10 minutos.", "err"); return go("/registro")
    if not INVITE or not secrets.compare_digest(invite.strip().encode(), INVITE.encode()):
        register_fail([k for k, _ in keys])
        flash(request, "Código de invitación incorrecto.", "err"); return go("/registro")
    if not re.fullmatch(r"[a-z0-9_.-]{3,32}", username):
        flash(request, "Usuario: 3-32 caracteres (letras, números, . _ -).", "err"); return go("/registro")
    if len(password) < 10 or len(password) > 200:
        flash(request, "La contraseña debe tener entre 10 y 200 caracteres.", "err"); return go("/registro")
    if one("SELECT 1 FROM users WHERE username=?", (username,)):
        flash(request, "Ese usuario ya existe.", "err"); return go("/registro")
    uid, _ = ex("INSERT INTO users(username,pw_hash,ics_token,created) VALUES(?,?,?,?)",
                (username, ph.hash(password), new_token(), now().isoformat()))
    request.session.clear(); request.session["uid"] = uid
    flash(request, "Cuenta creada. Si quieres recibir avisos por email, añade tu correo aquí.")
    return go("/ajustes")


@app.post("/salir")
def logout(request: Request, csrf_token: str = Form("")):
    try:
        check_csrf(request, csrf_token)
    except PermissionError:
        return go("/")
    request.session.clear()
    return go("/login")


# ---------- panel ----------
@app.get("/")
def home(request: Request, meses: int = 3):
    u = getuser(request)
    if not u:
        return go("/login")
    meses = meses if meses in (3, 6, 12) else 3
    dash = dashboard(u, months=meses)
    mmax = max([v for _, v in dash["projection"]] + [Decimal(1)])
    cmax = max([v for _, v in dash["cats"]] + [Decimal(1)])
    return render(request, "index.html", dash=dash, mmax=mmax, cmax=cmax, meses_es=MESES_ES, donut=donut_data(dash["cats"]), info=rates_info(),
                  hoy_txt=f"{DIAS_ES[today().weekday()]}, {today().day} de {MESES_ES[today().month - 1].lower()}",
                  smtp_ok=alerts.smtp_configured())


# ---------- suscripciones ----------
def parse_sub(form):
    """Devuelve (datos, error)."""
    name = str(form.get("name", "")).strip()
    if not 1 <= len(name) <= 80:
        return None, "El nombre es obligatorio (máx. 80 caracteres)."
    category = str(form.get("category", ""))
    category = category if category in CATEGORIES else "Otros"
    cents = parse_amount(str(form.get("amount", "")))
    if cents is None:
        return None, "Importe no válido (ejemplo: 12,99)."
    cur = str(form.get("currency", "")).upper()
    if cur not in CURRENCIES:
        return None, "Moneda no válida."
    try:
        n = int(str(form.get("period_n", "1")))
    except ValueError:
        n = 0
    unit = str(form.get("period_unit", ""))
    if not 1 <= n <= 365 or unit not in UNITS:
        return None, "Periodicidad no válida."
    try:
        start = dt.date.fromisoformat(str(form.get("start_date", "")))
        if not 2000 <= start.year <= 2100:
            raise ValueError
    except ValueError:
        return None, "Fecha de cobro no válida."
    trial = None
    if str(form.get("trial_end", "")).strip():
        try:
            trial = dt.date.fromisoformat(str(form.get("trial_end")))
        except ValueError:
            return None, "Fecha de fin de prueba no válida."
    url = str(form.get("cancel_url", "")).strip()
    if url:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.netloc or len(url) > 300:
            return None, "El enlace para cancelar debe empezar por http:// o https://"
    return dict(name=name, category=category, amount_cents=cents, currency=cur, period_n=n, period_unit=unit,
                start_date=start.isoformat(), trial_end=trial.isoformat() if trial else None,
                payment_method=str(form.get("payment_method", "")).strip()[:60],
                notes=str(form.get("notes", "")).strip()[:500], cancel_url=url), None


def own_sub(u, sid):
    return one("SELECT * FROM subs WHERE id=? AND user_id=?", (sid, u["id"]))


@app.get("/suscripciones")
def subs_list(request: Request, estado: str = "activa"):
    u = getuser(request)
    if not u:
        return go("/login")
    subs, _ = user_subs(u)
    estado = estado if estado in ("activa", "pausada", "cancelada", "todas") else "activa"
    shown = subs if estado == "todas" else [s for s in subs if s["status"] == estado]
    shown.sort(key=lambda s: (s["next"] is None, s["next"] or dt.date.max, s["name"].lower()))
    counts = {k: len([s for s in subs if s["status"] == k]) for k in ("activa", "pausada", "cancelada")}
    return render(request, "lista.html", subs=shown, estado=estado, counts=counts, total=len(subs), base=u["base_currency"])


def form_ctx(sub=None, hist=None):
    return dict(sub=sub, cats=CATEGORIES, currencies=CURRENCIES, units=UNIT_ES, hist=hist or [])


@app.get("/suscripciones/nueva")
def sub_new(request: Request):
    u = getuser(request)
    if not u:
        return go("/login")
    return render(request, "form.html", **form_ctx(dict(currency=u["base_currency"], period_n=1, period_unit="month",
                                                       category="Streaming", start_date=today().isoformat(), amount_text="")))


@app.post("/suscripciones/nueva")
async def sub_create(request: Request):
    u = getuser(request)
    if not u:
        return go("/login")
    form = await post_form(request)
    if form is None:
        return go("/suscripciones/nueva")
    data, err = parse_sub(form)
    if err:
        flash(request, err, "err")
        return render(request, "form.html", **form_ctx({**{k: str(form.get(k, "")) for k in
                       ("name", "category", "currency", "period_unit", "start_date", "trial_end", "payment_method", "notes", "cancel_url")},
                       "amount_text": str(form.get("amount", "")), "period_n": str(form.get("period_n", "1"))}))
    if (one("SELECT COUNT(*) AS c FROM subs WHERE user_id=?", (u["id"],)) or {"c": 0})["c"] >= 500:
        flash(request, "Has alcanzado el máximo de 500 suscripciones.", "err"); return go("/suscripciones")
    sid, _ = ex("INSERT INTO subs(user_id,name,category,amount_cents,currency,period_n,period_unit,start_date,trial_end,"
                "payment_method,notes,cancel_url,status,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'activa',?)",
                (u["id"], data["name"], data["category"], data["amount_cents"], data["currency"], data["period_n"],
                 data["period_unit"], data["start_date"], data["trial_end"], data["payment_method"], data["notes"],
                 data["cancel_url"], now().isoformat()))
    ex("INSERT INTO price_history(sub_id,user_id,amount_cents,currency,changed_on) VALUES(?,?,?,?,?)",
       (sid, u["id"], data["amount_cents"], data["currency"], today().isoformat()))
    flash(request, f"«{data['name']}» añadida.")
    return go("/suscripciones")


@app.get("/suscripciones/{sid}/editar")
def sub_edit(request: Request, sid: int):
    u = getuser(request)
    if not u:
        return go("/login")
    s = own_sub(u, sid)
    if not s:
        flash(request, "Suscripción no encontrada.", "err"); return go("/suscripciones")
    s["amount_text"] = fmt_plain(s["amount_cents"]).replace(".", ",")
    hist = q("SELECT * FROM price_history WHERE sub_id=? AND user_id=? ORDER BY id DESC LIMIT 20", (sid, u["id"]))
    return render(request, "form.html", **form_ctx(s, hist))


@app.post("/suscripciones/{sid}/editar")
async def sub_update(request: Request, sid: int):
    u = getuser(request)
    if not u:
        return go("/login")
    form = await post_form(request)
    old = own_sub(u, sid)
    if form is None or not old:
        if not old:
            flash(request, "Suscripción no encontrada.", "err")
        return go(f"/suscripciones/{sid}/editar" if old else "/suscripciones")
    data, err = parse_sub(form)
    if err:
        flash(request, err, "err"); return go(f"/suscripciones/{sid}/editar")
    ex("UPDATE subs SET name=?,category=?,amount_cents=?,currency=?,period_n=?,period_unit=?,start_date=?,trial_end=?,"
       "payment_method=?,notes=?,cancel_url=? WHERE id=? AND user_id=?",
       (data["name"], data["category"], data["amount_cents"], data["currency"], data["period_n"], data["period_unit"],
        data["start_date"], data["trial_end"], data["payment_method"], data["notes"], data["cancel_url"], sid, u["id"]))
    if (old["amount_cents"], old["currency"]) != (data["amount_cents"], data["currency"]):
        ex("INSERT INTO price_history(sub_id,user_id,amount_cents,currency,changed_on) VALUES(?,?,?,?,?)",
           (sid, u["id"], data["amount_cents"], data["currency"], today().isoformat()))
    flash(request, "Cambios guardados.")
    return go("/suscripciones")


@app.post("/suscripciones/{sid}/estado")
async def sub_status(request: Request, sid: int):
    u = getuser(request)
    if not u:
        return go("/login")
    form = await post_form(request)
    if form is None:
        return go("/suscripciones")
    st = str(form.get("estado", ""))
    if st not in ("activa", "pausada", "cancelada"):
        return go("/suscripciones")
    _, n = ex("UPDATE subs SET status=? WHERE id=? AND user_id=?", (st, sid, u["id"]))
    flash(request, "Estado actualizado." if n else "Suscripción no encontrada.", "ok" if n else "err")
    return go("/suscripciones")


@app.post("/suscripciones/{sid}/borrar")
async def sub_delete(request: Request, sid: int):
    u = getuser(request)
    if not u:
        return go("/login")
    form = await post_form(request)
    if form is None:
        return go("/suscripciones")
    if own_sub(u, sid):
        ex("DELETE FROM sent_alerts WHERE sub_id=?", (sid,))
        ex("DELETE FROM price_history WHERE sub_id=? AND user_id=?", (sid, u["id"]))
        ex("DELETE FROM subs WHERE id=? AND user_id=?", (sid, u["id"]))
        flash(request, "Suscripción eliminada.")
    else:
        flash(request, "Suscripción no encontrada.", "err")
    return go("/suscripciones")


# ---------- ajustes ----------
EMAIL_RE = re.compile(r"[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}")


@app.get("/ajustes")
def settings(request: Request):
    u = getuser(request)
    if not u:
        return go("/login")
    base = str(request.base_url).rstrip("/")
    return render(request, "ajustes.html", currencies=CURRENCIES, smtp_ok=alerts.smtp_configured(),
                  ics_url=f"{base}/cal/{u['ics_token']}.ics", info=rates_info())


@app.post("/ajustes")
async def settings_post(request: Request):
    u = getuser(request)
    if not u:
        return go("/login")
    form = await post_form(request)
    if form is None:
        return go("/ajustes")
    email = str(form.get("email", "")).strip()[:120]
    if email and not EMAIL_RE.fullmatch(email):
        flash(request, "Email no válido.", "err"); return go("/ajustes")
    cur = str(form.get("base_currency", "EUR"))
    if cur not in CURRENCIES:
        cur = "EUR"
    try:
        days = min(30, max(0, int(str(form.get("alert_days", "3")))))
    except ValueError:
        days = 3
    ex("UPDATE users SET email=?, base_currency=?, alerts_on=?, alert_days=? WHERE id=?",
       (email, cur, 1 if form.get("alerts_on") else 0, days, u["id"]))
    flash(request, "Ajustes guardados.")
    return go("/ajustes")


@app.post("/ajustes/password")
async def settings_pw(request: Request):
    u = getuser(request)
    if not u:
        return go("/login")
    form = await post_form(request)
    if form is None:
        return go("/ajustes")
    keys = [(("pw", u["id"]), 5)]
    if blocked(keys):
        flash(request, "Demasiados intentos. Espera 10 minutos.", "err"); return go("/ajustes")
    new = str(form.get("new_password", ""))
    try:
        ph.verify(u["pw_hash"], str(form.get("old_password", "")))
    except VerifyMismatchError:
        register_fail([k for k, _ in keys])
        flash(request, "La contraseña actual no es correcta.", "err"); return go("/ajustes")
    if not 10 <= len(new) <= 200:
        flash(request, "La nueva contraseña debe tener entre 10 y 200 caracteres.", "err"); return go("/ajustes")
    ex("UPDATE users SET pw_hash=? WHERE id=?", (ph.hash(new), u["id"]))
    flash(request, "Contraseña cambiada.")
    return go("/ajustes")


@app.post("/ajustes/calendario")
async def settings_cal(request: Request):
    u = getuser(request)
    if not u:
        return go("/login")
    if await post_form(request) is None:
        return go("/ajustes")
    ex("UPDATE users SET ics_token=? WHERE id=?", (new_token(), u["id"]))
    flash(request, "Enlace del calendario regenerado. El anterior ya no funciona.")
    return go("/ajustes")


@app.post("/ajustes/probar-email")
async def settings_test_mail(request: Request):
    u = getuser(request)
    if not u:
        return go("/login")
    if await post_form(request) is None:
        return go("/ajustes")
    if not u["email"]:
        flash(request, "Primero guarda tu email.", "err"); return go("/ajustes")
    if not alerts.smtp_configured():
        flash(request, "El servidor aún no tiene el correo saliente configurado.", "err"); return go("/ajustes")
    if time.time() - MAIL_TEST.get(u["id"], 0) < 60:
        flash(request, "Espera un minuto entre pruebas.", "err"); return go("/ajustes")
    MAIL_TEST[u["id"]] = time.time()
    try:
        alerts.send_mail(u["email"], "Suscripciones: email de prueba", "Los avisos por email funcionan correctamente.\n")
        flash(request, "Email de prueba enviado. Revisa también la carpeta de spam.")
    except Exception:
        flash(request, "No se pudo enviar el email de prueba. Avisa al administrador.", "err")
    return go("/ajustes")


# ---------- exportar y calendario ----------
def csv_safe(v):
    v = str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v    # evita inyección de fórmulas en hojas de cálculo


@app.get("/exportar.csv")
def export_csv(request: Request):
    u = getuser(request)
    if not u:
        return go("/login")
    subs, _ = user_subs(u)
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["nombre", "categoria", "importe", "moneda", "periodicidad", "proximo_cobro", f"coste_anual_{u['base_currency']}",
                "estado", "metodo_pago", "notas"])
    for s in subs:
        w.writerow([csv_safe(s["name"]), s["category"], fmt_plain(s["amount_cents"]).replace(".", ","), s["currency"],
                    s["period_text"], s["next"].isoformat() if s["next"] else "",
                    fmt_plain(s["annual"]).replace(".", ",") if s["annual"] is not None else "", s["status"],
                    csv_safe(s["payment_method"]), csv_safe(s["notes"])])
    return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="suscripciones.csv"'})


def ics_escape(t):
    return str(t).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_fold(line):
    b, out = line.encode(), []
    while len(b) > 73:
        cut = 73
        while (b[cut] & 0xC0) == 0x80:      # no cortar un carácter UTF-8 a la mitad
            cut -= 1
        out.append(b[:cut].decode()); b = b[cut:]; b = b" " + b
    out.append(b.decode())
    return "\r\n".join(out)


@app.get("/cal/{token}.ics")
def calendar_feed(token: str):
    u = one("SELECT * FROM users WHERE ics_token=?", (token,)) if re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token) else None
    if not u:
        return PlainTextResponse("No encontrado", status_code=404)
    day = today()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Suscripciones//ES", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:Renovaciones de suscripciones"]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for s in q("SELECT * FROM subs WHERE user_id=? AND status='activa'", (u["id"],)):
        for o in occurrences_between(d(s["start_date"]), s["period_n"], s["period_unit"], day, day + dt.timedelta(days=366), limit=60):
            end = o + dt.timedelta(days=1)
            lines += ["BEGIN:VEVENT", f"UID:sub{s['id']}-{o.isoformat()}@suscripciones", f"DTSTAMP:{stamp}",
                      f"DTSTART;VALUE=DATE:{o.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}",
                      ics_fold("SUMMARY:" + ics_escape(f"{s['name']} · {fmt(s['amount_cents'], s['currency'])}")),
                      "TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return Response("\r\n".join(lines) + "\r\n", media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "private, max-age=3600"})


# ---------- PWA ----------
@app.get("/manifest.webmanifest")
def manifest():
    return Response(open(os.path.join(HERE, "static", "manifest.webmanifest"), "rb").read(),
                    media_type="application/manifest+json", headers={"Cache-Control": "public, max-age=3600"})


@app.get("/sw.js")
def sw():
    return FileResponse(os.path.join(HERE, "static", "sw.js"), media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/salud")
def health():
    return PlainTextResponse("ok")
