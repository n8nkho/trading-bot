"""
Notification utility — SMS via Twilio (if configured) or log-only fallback.
Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM, NOTIFY_PHONE in .env
"""
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def send_alert(message: str, level: str = "INFO") -> bool:
    """
    Send an alert notification.
    Falls back gracefully if Twilio is not configured.

    Args:
        message: Alert message text
        level: INFO | WARNING | CRITICAL

    Returns:
        True if sent/logged successfully
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M ET")
    full_message = f"[{level}] Trading Bot {timestamp}:\n{message}"

    log_fn = logger.info if level == "INFO" else logger.warning if level == "WARNING" else logger.error
    log_fn(f"ALERT: {message}")

    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_num = os.getenv("TWILIO_FROM")
    to_num = os.getenv("NOTIFY_PHONE")

    if all([sid, token, from_num, to_num]):
        try:
            from twilio.rest import Client
            client = Client(sid, token)
            msg = client.messages.create(body=full_message[:1600], from_=from_num, to=to_num)
            logger.info(f"SMS sent: {msg.sid}")
            return True
        except ImportError:
            logger.warning("twilio not installed — SMS disabled. Run: pip install twilio")
        except Exception as e:
            logger.error(f"SMS send failed: {e}")
    else:
        logger.debug("Twilio not configured — alert logged only. Set TWILIO_* env vars to enable SMS.")

    return True  # logging always works


def alert_trade_executed(ticker: str, action: str, shares: int, price: float, strategy: str = ""):
    strat = f" ({strategy})" if strategy else ""
    send_alert(
        f"Trade{strat}: {action} {shares}x {ticker} @ ${price:.2f} = ${shares * price:.0f}",
        level="INFO"
    )


def alert_circuit_breaker(consecutive_losses: int):
    send_alert(
        f"CIRCUIT BREAKER: {consecutive_losses} consecutive losses — trading HALTED",
        level="CRITICAL"
    )


def alert_daily_loss_limit(loss_pct: float):
    send_alert(
        f"DAILY LOSS LIMIT: Down {loss_pct:.1%} today — new entries paused",
        level="CRITICAL"
    )
