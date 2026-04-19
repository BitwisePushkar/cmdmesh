import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import aiosmtplib
from backend.config import get_settings

log = logging.getLogger(__name__)

class EmailError(Exception):
    pass

class EmailService:
    @staticmethod
    async def send_otp(*, email: str, username: str, otp: str) -> None:
        settings = get_settings()
        ttl_minutes = settings.otp_ttl_seconds // 60
        await EmailService._send(
            to=email,
            subject="Your cmdmesh verification code",
            body_text=_otp_plain(username, otp, ttl_minutes),
            body_html=_otp_html(username, otp, ttl_minutes),
        )

    @staticmethod
    async def send_password_reset(*, email: str, username: str, otp: str) -> None:
        settings = get_settings()
        ttl_minutes = settings.password_reset_otp_ttl_seconds // 60
        await EmailService._send(
            to=email,
            subject="Reset your cmdmesh password",
            body_text=_reset_plain(username, otp, ttl_minutes),
            body_html=_reset_html(username, otp, ttl_minutes),
        )

    @staticmethod
    async def _send(*, to: str, subject: str, body_text: str, body_html: str) -> None:
        settings = get_settings()
        msg = MIMEMultipart("alternative")
        msg["From"] = settings.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        try:
            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username or None,
                password=settings.smtp_password or None,
                use_tls=settings.smtp_tls,
                start_tls=settings.smtp_starttls,
            )
            log.info("Email sent to %s (subject=%r)", to, subject)
        except aiosmtplib.SMTPException as exc:
            log.error("SMTP error sending to %s: %s", to, exc)
            raise EmailError(f"Failed to send email: {exc}") from exc

def _otp_plain(username: str, otp: str, ttl_minutes: int) -> str:
    return (
        f"Hi {username},\n\n"
        f"Your cmdmesh verification code is:\n\n"
        f"  {otp}\n\n"
        f"This code expires in {ttl_minutes} minutes.\n"
        f"If you did not request this, you can safely ignore this email.\n\n"
        f"-- cmdmesh"
    )

def _otp_html(username: str, otp: str, ttl_minutes: int) -> str:
    return f"""<!DOCTYPE html>
<html>
<body style="font-family:monospace;max-width:480px;margin:40px auto;color:#1a1a1a">
  <h2>cmdmesh</h2>
  <p>Hi <strong>{username}</strong>,</p>
  <p>Your verification code is:</p>
  <div style="font-size:2rem;letter-spacing:.3em;background:#f4f4f4;
              padding:16px 24px;border-radius:8px;display:inline-block;
              font-weight:bold">{otp}</div>
  <p style="color:#666;font-size:.875rem">
    Expires in {ttl_minutes} minutes. If you did not sign up, ignore this email.
  </p>
</body>
</html>"""

def _reset_plain(username: str, otp: str, ttl_minutes: int) -> str:
    return (
        f"Hi {username},\n\n"
        f"You requested a password reset for your cmdmesh account.\n\n"
        f"Your reset code is:\n\n"
        f"  {otp}\n\n"
        f"This code expires in {ttl_minutes} minutes.\n\n"
        f"If you did not request a password reset, your account may be at risk.\n"
        f"Please log in and change your password immediately.\n\n"
        f"-- cmdmesh"
    )

def _reset_html(username: str, otp: str, ttl_minutes: int) -> str:
    return f"""<!DOCTYPE html>
<html>
<body style="font-family:monospace;max-width:480px;margin:40px auto;color:#1a1a1a">
  <h2>cmdmesh</h2>
  <p>Hi <strong>{username}</strong>,</p>
  <p>You requested a password reset. Enter this code in your terminal:</p>
  <div style="font-size:2rem;letter-spacing:.3em;background:#fff3cd;
              padding:16px 24px;border-radius:8px;display:inline-block;
              font-weight:bold;border:1px solid #ffc107">{otp}</div>
  <p style="color:#666;font-size:.875rem">Expires in {ttl_minutes} minutes.</p>
  <p style="color:#d32f2f;font-size:.875rem">
    If you did not request this, log in and change your password immediately.
  </p>
</body>
</html>"""