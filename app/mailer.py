import logging
import smtplib
import time
from email.message import EmailMessage

from .config import get_settings

log = logging.getLogger("ott.mail")


def send_mail(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not s.smtp_host:
        if s.is_prod:
            log.error("SMTP not configured; email not sent (subject=%s)", subject)
        else:  # development convenience only: surface the link in the server log
            log.warning("DEV MAIL to=%s subject=%s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    for attempt in range(3):  # transient SMTP failures (timeouts, 4xx greylisting) are retried with backoff
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
            return
        except smtplib.SMTPAuthenticationError:
            log.error("SMTP rejected the configured credentials; email not sent (subject=%s)", subject)
            return
        except Exception:
            if attempt == 2:
                log.exception("failed to send email after 3 attempts (subject=%s)", subject)
            else:
                time.sleep(2 ** attempt)
