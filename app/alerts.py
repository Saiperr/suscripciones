"""Avisos por email (renovaciones y fin de pruebas gratuitas) y planificador en segundo plano."""
import os, ssl, smtplib, threading, time, logging, datetime as dt
from email.message import EmailMessage
from .core import q, one, ex, today, now, TZ
from .calc import user_subs, d
from .money import fmt, refresh_rates

log = logging.getLogger("suscripciones")
SEND_FROM_HOUR = 8     # los avisos salen a partir de las 8:00 (hora de Madrid)


def smtp_configured():
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def send_mail(to, subject, body):
    """Lanza excepción si falla. Requiere SMTP_HOST/PORT/USER/PASS/FROM en el entorno."""
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = os.environ["SMTP_FROM"], to, subject
    msg.set_content(body)
    host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))
    user, pw = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASS", "")
    ctx = ssl.create_default_context()
    if port == 465:
        s = smtplib.SMTP_SSL(host, port, timeout=20, context=ctx)
    else:
        s = smtplib.SMTP(host, port, timeout=20)
        s.starttls(context=ctx)
    with s:
        if user:
            s.login(user, pw)
        s.send_message(msg)


def when(days):
    return "hoy" if days == 0 else "mañana" if days == 1 else f"en {days} días"


def pending_for_user(user, day):
    """[(sub_id, ref_date, kind, línea de texto)] de lo que toca avisar hoy a este usuario."""
    subs, _ = user_subs(user, day)
    out = []
    for s in subs:
        if s["status"] != "activa":
            continue
        if s["next"] and s["days_left"] <= user["alert_days"]:
            out.append((s["id"], s["next"].isoformat(), "renovacion",
                        f"• {s['name']}: {fmt(s['amount_cents'], s['currency'])} se cobra {when(s['days_left'])} ({s['next'].strftime('%d/%m/%Y')})"))
        t = d(s["trial_end"])
        if t and 0 <= (t - day).days <= user["alert_days"]:
            out.append((s["id"], t.isoformat(), "prueba",
                        f"• {s['name']}: la prueba gratuita termina {when((t - day).days)} ({t.strftime('%d/%m/%Y')}). "
                        f"Si no la quieres, cancélala antes."))
    return out


def run_alerts(day=None, hour=None):
    """Envía los avisos pendientes. Cada aviso se reserva en `sent_alerts` antes de enviar (no se repite aunque
    el proceso se reinicie); si el envío falla, se libera la reserva para reintentarlo."""
    day = day or today()
    hour = now().hour if hour is None else hour
    if hour < SEND_FROM_HOUR:
        return 0
    sent = 0
    for u in q("SELECT * FROM users WHERE alerts_on=1 AND email<>''"):
        todo = []
        for sub_id, ref, kind, line in pending_for_user(u, day):
            if one("SELECT 1 FROM sent_alerts WHERE sub_id=? AND ref_date=? AND kind=?", (sub_id, ref, kind)):
                continue
            todo.append((sub_id, ref, kind, line))
        if not todo:
            continue
        if not smtp_configured():
            log.warning("SMTP sin configurar: %d aviso(s) pendiente(s) para %s", len(todo), u["username"])
            continue
        claimed = []
        for sub_id, ref, kind, line in todo:
            try:
                ex("INSERT INTO sent_alerts(sub_id,ref_date,kind,sent) VALUES(?,?,?,?)", (sub_id, ref, kind, now().isoformat()))
                claimed.append((sub_id, ref, kind, line))
            except Exception:
                pass   # otro hilo lo reservó primero
        if not claimed:
            continue
        body = "Hola,\n\nRecordatorio de tus suscripciones:\n\n" + "\n".join(l for *_, l in claimed) + \
               "\n\n— Suscripciones\n(Puedes cambiar o desactivar los avisos en Ajustes.)\n"
        try:
            send_mail(u["email"], f"Suscripciones: {len(claimed)} aviso(s)", body)
            sent += len(claimed)
        except Exception as e:
            log.error("fallo enviando email a %s: %s", u["username"], e)
            for sub_id, ref, kind, _ in claimed:
                ex("DELETE FROM sent_alerts WHERE sub_id=? AND ref_date=? AND kind=?", (sub_id, ref, kind))
    return sent


def _loop():
    time.sleep(5)
    while True:
        try:
            refresh_rates()
            run_alerts()
            ex("DELETE FROM sent_alerts WHERE ref_date < ?", ((today() - dt.timedelta(days=60)).isoformat(),))
        except Exception:
            log.exception("error en el planificador")
        time.sleep(900)


def start():
    threading.Thread(target=_loop, daemon=True, name="planificador").start()
