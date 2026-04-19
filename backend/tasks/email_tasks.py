"""
Celery email tasks — all outbound email goes through here so HTTP
request handlers return immediately and email delivery happens in
the background worker process.

Tasks
-----
send_otp_email            signup / resend OTP
send_password_reset_email password reset OTP
"""

import asyncio
import logging

from celery import Task
from celery.utils.log import get_task_logger

from backend.worker import celery_app

log = get_task_logger(__name__)


class _AsyncTask(Task):
    """Base task that runs async functions in a fresh event loop."""

    def run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# ── OTP email ─────────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=_AsyncTask,
    name="backend.tasks.email_tasks.send_otp_email",
    max_retries=3,
    default_retry_delay=10,   # seconds between retries
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def send_otp_email(self, *, email: str, username: str, otp: str) -> dict:
    """
    Send signup / resend-OTP email.
    Retried up to 3 times with exponential back-off on any failure.
    """
    from backend.services.email_service import EmailService

    log.info("Sending OTP email to %s (attempt %d)", email, self.request.retries + 1)

    self.run_async(EmailService.send_otp(email=email, username=username, otp=otp))

    log.info("OTP email delivered to %s", email)
    return {"status": "sent", "email": email}


# ── Password reset email ──────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=_AsyncTask,
    name="backend.tasks.email_tasks.send_password_reset_email",
    max_retries=3,
    default_retry_delay=10,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def send_password_reset_email(self, *, email: str, username: str, otp: str) -> dict:
    """
    Send password-reset OTP email.
    """
    from backend.services.email_service import EmailService

    log.info(
        "Sending password-reset email to %s (attempt %d)",
        email,
        self.request.retries + 1,
    )

    self.run_async(
        EmailService.send_password_reset(email=email, username=username, otp=otp)
    )

    log.info("Password-reset email delivered to %s", email)
    return {"status": "sent", "email": email}