"""
notifications.py — Email e push notifications.
"""

import smtplib, requests, logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import EMAIL_FROM, EMAIL_TO, EMAIL_PASSWORD, PUSHOVER_APP, PUSHOVER_USER

log = logging.getLogger(__name__)


def send_push_notification(message: str, title: str = "Trading Agent",
                            priority: int = 0):
    """Push notification via Pushover (gratuito até 10k/mês)."""
    if not PUSHOVER_APP or not PUSHOVER_USER:
        log.debug("Pushover não configurado — a saltar")
        return
    try:
        requests.post("https://api.pushover.net/1/messages.json", data={
            "token":    PUSHOVER_APP,
            "user":     PUSHOVER_USER,
            "title":    title,
            "message":  message,
            "priority": priority,
        }, timeout=5)
        log.debug("Push enviado")
    except Exception as e:
        log.warning(f"Push falhou: {e}")


def send_email_report(analysis: dict):
    """Email com oportunidades do research diário."""
    if not EMAIL_FROM or not EMAIL_TO:
        log.debug("Email não configurado — a saltar")
        return

    opps    = analysis.get("opportunities", [])
    summary = analysis.get("market_summary", "")

    opps_html = ""
    for o in opps:
        color = {"alta": "#ff4060", "média": "#f0a500",
                 "baixa": "#00d68f"}.get(o.get("urgency", "baixa"), "#8a96a0")
        cats  = "".join(f"<li>{c}</li>" for c in o.get("catalysts", []))
        risks = "".join(f"<li>{r}</li>" for r in o.get("risks", []))
        opps_html += f"""
        <div style="background:#0d1117;border:1px solid #1e2a3a;
                    border-radius:8px;padding:16px;margin-bottom:12px">
            <div style="display:flex;justify-content:space-between;margin-bottom:8px">
                <strong style="color:#dde4ec;font-size:16px">{o.get('ticker')}</strong>
                <span style="color:{color};font-size:11px;background:{color}22;
                             padding:2px 8px;border-radius:4px">
                    {o.get('urgency','').upper()} · {o.get('confidence',0)}%
                </span>
            </div>
            <p style="color:#7a8898;font-size:12px;margin:0 0 8px">
                {o.get('name','')} · {o.get('suggested_strategy','').replace('_',' ')}
            </p>
            <p style="color:#c0c8d0;font-size:13px;line-height:1.5;margin:0 0 10px">
                {o.get('thesis','')}
            </p>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:11px">
                <div><p style="color:#4a5560;margin:0 0 4px">Catalisadores</p>
                     <ul style="color:#7a8898;padding-left:14px;margin:0">{cats}</ul></div>
                <div><p style="color:#4a5560;margin:0 0 4px">Riscos</p>
                     <ul style="color:#7a8898;padding-left:14px;margin:0">{risks}</ul></div>
            </div>
        </div>"""

    html = f"""
    <div style="font-family:monospace;background:#07090d;padding:28px;
                max-width:600px;margin:0 auto">
        <h1 style="color:#00d68f;font-size:16px;margin:0 0 4px">
            Trading Agent · Research Diário
        </h1>
        <p style="color:#4a5560;font-size:11px;margin:0 0 20px">
            {__import__('datetime').date.today().strftime('%d/%m/%Y')}
        </p>
        <div style="background:#0c1118;border:1px solid #1e2a3a;
                    border-radius:8px;padding:14px;margin-bottom:20px">
            <p style="color:#c0c8d0;font-size:13px;line-height:1.5;margin:0">
                {summary}
            </p>
        </div>
        <h2 style="color:#dde4ec;font-size:12px;text-transform:uppercase;
                   letter-spacing:1px;margin:0 0 14px">
            {len(opps)} Oportunidades
        </h2>
        {opps_html}
        <p style="color:#1e2a3a;font-size:10px;text-align:center;margin-top:20px">
            Gerado automaticamente · Não é aconselhamento financeiro
        </p>
    </div>"""

    try:
        msg             = MIMEMultipart("alternative")
        msg["Subject"]  = f"[Agent] {len(opps)} oportunidades · {__import__('datetime').date.today().strftime('%d/%m')}"
        msg["From"]     = EMAIL_FROM
        msg["To"]       = EMAIL_TO
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(EMAIL_FROM, EMAIL_PASSWORD)
            s.send_message(msg)
        log.info(f"Email enviado para {EMAIL_TO}")
    except Exception as e:
        log.warning(f"Email falhou: {e}")
