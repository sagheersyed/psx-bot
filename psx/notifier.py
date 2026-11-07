"""
psx/notifier.py: Multi-Channel Instant Notification Engine
Dispatches real-time alerts to Telegram (Phone Push), Email (SMTP), and Web Terminal.
Equipped with volume metrics and institutional trade plan formatting.
"""
import os
import json
import threading
import urllib.request
import urllib.parse
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import load_dotenv

import config

load_dotenv(config.BASE_DIR / ".env")

# In-memory storage for the latest 60 real-time alerts for the Web Terminal
RECENT_ALERTS = []
MAX_SAVED_ALERTS = 60

LAST_DELIVERY_STATUS = {
    "telegram": {"enabled": False, "last_sent": None, "error": None},
    "email": {"enabled": False, "last_sent": None, "error": None},
    "web": {"count": 0}
}


def send_telegram_alert(text: str) -> bool:
    """Send instant push notification to user's phone via Telegram."""
    load_dotenv(config.BASE_DIR / ".env", override=True)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        LAST_DELIVERY_STATUS["telegram"] = {"enabled": False, "last_sent": None, "error": "Token ya Chat ID missing (.env mein paste karein)"}
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            ok = resp.status == 200
            LAST_DELIVERY_STATUS["telegram"] = {
                "enabled": True, 
                "last_sent": datetime.now(ZoneInfo(config.TZ)).strftime("%H:%M:%S") if ok else None, 
                "error": None if ok else f"HTTP {resp.status}"
            }
            return ok
    except Exception as e:
        LAST_DELIVERY_STATUS["telegram"] = {"enabled": True, "last_sent": None, "error": str(e)}
        print(f"Telegram alert error: {e}")
        return False


def send_email_alert(subject: str, html_content: str) -> bool:
    """Send formatted alert email to user's inbox."""
    load_dotenv(config.BASE_DIR / ".env", override=True)
    server_host = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    server_port = int(os.getenv("SMTP_PORT", "587"))
    sender = os.getenv("SMTP_EMAIL", "").strip()
    pwd = os.getenv("SMTP_PASSWORD", "").strip()
    recipient = os.getenv("ALERT_RECIPIENT_EMAIL", "").strip()

    if not sender or not pwd or not recipient:
        LAST_DELIVERY_STATUS["email"] = {"enabled": False, "last_sent": None, "error": "SMTP Credentials missing in .env"}
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"PSX Eagle-Eye Alert <{sender}>"
        msg["To"] = recipient
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(server_host, server_port, timeout=8) as server:
            server.starttls()
            server.login(sender, pwd)
            server.sendmail(sender, recipient, msg.as_string())
        
        now = datetime.now(ZoneInfo(config.TZ)).strftime("%H:%M:%S")
        LAST_DELIVERY_STATUS["email"] = {"enabled": True, "last_sent": now, "error": None}
        return True
    except Exception as e:
        err_msg = str(e)
        if "550" in err_msg and "Daily user sending limit exceeded" in err_msg:
            err_msg = "Gmail Daily sending limit exceeded (550). Telegram push recommended."
        LAST_DELIVERY_STATUS["email"] = {"enabled": True, "last_sent": None, "error": err_msg}
        print(f"Email alert error: {err_msg}")
        return False


def _dispatch_external(alert_event: dict, now: str):
    """Dispatches Telegram and Email asynchronously so scanner is never blocked."""
    sym = alert_event.get("symbol", "")
    price = alert_event.get("price", 0)
    trigger = alert_event.get("trigger", "")
    details = alert_event.get("details", "")
    badge = alert_event.get("badge", "ALERT")
    rvol = alert_event.get("rvol")
    turnover_m = alert_event.get("turnover_m")
    trap_status = alert_event.get("anti_fakeout_status", "PASSED")

    is_danger = any(k in badge.upper() for k in ("CRASH", "DUMP", "LIQUIDATION", "AVOID", "REJECTION", "TRAP", "WARNING"))
    is_poi = any(k in badge.upper() for k in ("PULSE", "SUPPORT", "OTE", "WAIT", "CEILING"))
    theme_hex = "#ef4444" if is_danger else ("#f59e0b" if is_poi else "#00c087")

    # 1. Telegram Formatted Message
    tg_msg = (
        f"🦅 <b>PSX EAGLE-EYE SENTINEL</b>\n"
        f"<b>Stock:</b> #{sym} | <b>Price:</b> Rs. {price:.2f}\n"
        f"<b>Signal:</b> {badge}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if rvol:
        tg_msg += f"📊 <b>Volume:</b> {rvol}x 20D Avg" + (f" (Rs. {turnover_m}M)" if turnover_m else "") + "\n"
    if trap_status and trap_status != "NORMAL":
        tg_msg += f"🛡️ <b>Trap Shield:</b> <code>{trap_status}</code>\n"
    
    tg_msg += f"\n{details}\n"
    
    if alert_event.get("buy_zone") and not is_danger:
        tg_msg += f"\n🎯 <b>Zone:</b> {alert_event['buy_zone']}\n"
    if alert_event.get("stop_loss") and not is_danger:
        tg_msg += f"🛑 <b>Stop Loss:</b> Rs. {alert_event['stop_loss']}\n"
    if alert_event.get("target_1") and not is_danger:
        tg_msg += f"🚀 <b>TP1:</b> Rs. {alert_event['target_1']} | <b>TP2:</b> Rs. {alert_event.get('target_2', '—')}\n"
    
    tg_msg += f"\n<i>⏱ {now} PKT · PSX Autonomous Sentinel</i>"

    send_telegram_alert(tg_msg)

    # 2. Email HTML Message
    email_html = f"""
    <div style="font-family: Arial, sans-serif; background-color: #0b0e14; color: #e2e8f0; padding: 22px; border-radius: 12px; border: 1px solid #1e293b; max-width: 600px;">
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1e293b; padding-bottom: 12px; margin-bottom: 16px;">
            <h2 style="color: {theme_hex}; margin: 0; font-size: 20px;">🦅 PSX Sentinel: {sym}</h2>
            <span style="background-color: #1e293b; color: #94a3b8; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-family: monospace;">Rs. {price:.2f}</span>
        </div>
        
        <div style="background-color: #11151f; padding: 14px 16px; border-radius: 8px; border-left: 4px solid {theme_hex}; margin-bottom: 16px;">
            <h3 style="color: #ffffff; margin-top: 0; margin-bottom: 6px; font-size: 15px;">{badge}</h3>
            <p style="margin: 0; font-size: 14px; line-height: 1.5; color: #cbd5e1;">{details}</p>
        </div>
    """
    if rvol or trap_status:
        email_html += f"""
        <div style="background-color: #11151f; padding: 12px; border-radius: 8px; margin-bottom: 16px; font-size: 13px;">
            <div style="margin-bottom: 4px;"><b>Volume Expansion:</b> {rvol or '—'}x 20D Average (Value: Rs. {turnover_m or '—'}M)</div>
            <div><b>Anti-Fakeout Verification:</b> <span style="color: {theme_hex}; font-family: monospace;">{trap_status}</span></div>
        </div>
        """
    if alert_event.get("stop_loss") and not is_danger:
        email_html += f"""
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 16px; font-size: 13px;">
            <tr style="background-color: #161b26;">
                <td style="padding: 8px 12px; color: #94a3b8;"><b>Actionable Buy Zone:</b></td>
                <td style="padding: 8px 12px; color: #00c087;">{alert_event.get('buy_zone', '—')}</td>
            </tr>
            <tr style="background-color: #11151f;">
                <td style="padding: 8px 12px; color: #94a3b8;"><b>Strict Stop Loss:</b></td>
                <td style="padding: 8px 12px; color: #ef4444;">Rs. {alert_event.get('stop_loss', '—')}</td>
            </tr>
            <tr style="background-color: #161b26;">
                <td style="padding: 8px 12px; color: #94a3b8;"><b>Target 1 / Target 2:</b></td>
                <td style="padding: 8px 12px; color: #38bdf8;">Rs. {alert_event.get('target_1', '—')} / Rs. {alert_event.get('target_2', '—')}</td>
            </tr>
        </table>
        """
    email_html += f"""
        <div style="font-size: 11px; color: #64748b; border-top: 1px solid #1e293b; padding-top: 10px;">
            Trigger: {trigger} | Time: {now} PKT | PSX Autonomous Sentinel Engine
        </div>
    </div>
    """
    send_email_alert(f"PSX Alert: {sym} - {badge}", email_html)


_RECENT_LOCK = threading.Lock()


def broadcast_alert(alert_event: dict):
    """
    Broadcasts the alert event across all enabled channels:
    - Web Dashboard Live Stream (Instant)
    - Telegram Phone Push (Async background)
    - Email Notification (Async background)
    """
    now = datetime.now(ZoneInfo(config.TZ)).strftime("%H:%M:%S")
    alert_event["time"] = now
    sym = alert_event.get("symbol")
    trig = alert_event.get("trigger")
    
    # 1. Thread-safe save to in-memory buffer with deduplication
    with _RECENT_LOCK:
        # Prevent rapid duplicates for the same symbol & trigger within RECENT_ALERTS top items
        for existing in RECENT_ALERTS[:5]:
            if existing.get("symbol") == sym and existing.get("trigger") == trig:
                return  # already recorded
        RECENT_ALERTS.insert(0, alert_event)
        if len(RECENT_ALERTS) > MAX_SAVED_ALERTS:
            RECENT_ALERTS.pop()
        LAST_DELIVERY_STATUS["web"]["count"] += 1

    # 2. Dispatch Telegram & Email in background thread
    threading.Thread(target=_dispatch_external, args=(alert_event, now), daemon=True).start()


def get_recent_alerts() -> list:
    """Returns the most recent alerts for the Web UI."""
    return RECENT_ALERTS


def get_delivery_status() -> dict:
    """Returns status of alert channels."""
    return LAST_DELIVERY_STATUS
