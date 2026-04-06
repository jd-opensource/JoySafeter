"""
Email service.
"""

from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader
from loguru import logger

from app.core.settings import settings

_template_dir = Path(__file__).resolve().parent.parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_template_dir)), autoescape=True)

# Validate templates exist at import time (fail-fast, like prompts.py).
_EMAIL_TEMPLATES = ("email/password_reset.html", "email/email_verification.html")
for _tpl in _EMAIL_TEMPLATES:
    _jinja_env.get_template(_tpl)


def _render(template_name: str, **kwargs: object) -> str:
    """Render a Jinja2 email template with common variables."""
    kwargs.setdefault("year", datetime.now(tz=timezone.utc).year)
    return _jinja_env.get_template(template_name).render(**kwargs)


class EmailService:
    """Email service."""

    def __init__(self):
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_password = settings.smtp_password
        self.from_email = settings.from_email
        self.from_name = settings.from_name
        self.frontend_url = settings.frontend_url

        # development mode
        self.is_dev = settings.environment == "development"

    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        """Send an email."""
        if self.is_dev:
            # in development mode, only log
            logger.info(f"[DEV] Email to: {to_email}")
            logger.info(f"[DEV] Subject: {subject}")
            logger.info(f"[DEV] Content: {html_content[:200]}...")
            return True

        # production mode — use SMTP
        if not self.smtp_host or not self.smtp_user:
            logger.warning("SMTP not configured, email not sent")
            return False

        try:
            import aiosmtplib

            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = f"{self.from_name} <{self.from_email}>"
            message["To"] = to_email

            if text_content:
                message.attach(MIMEText(text_content, "plain"))
            message.attach(MIMEText(html_content, "html"))

            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                start_tls=True,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    async def send_password_reset_email(
        self,
        to_email: str,
        username: str,
        reset_token: str,
        frontend_url: Optional[str] = None,
    ) -> bool:
        """Send a password reset email."""
        url = frontend_url or self.frontend_url
        reset_link = f"{url}/reset-password?token={reset_token}"

        subject = "[JoySafeter] Password Reset Request"
        html_content = _render("email/password_reset.html", username=username, reset_link=reset_link)
        text_content = f"""\
Hello, {username}!

We received a request to reset your password.

Click the link below to reset your password:
{reset_link}

This link will expire in 24 hours.

If you did not request a password reset, please ignore this email.

---
JoySafeter Team"""

        return await self.send_email(to_email, subject, html_content, text_content)

    async def send_email_verification(
        self,
        to_email: str,
        username: str,
        verify_token: str,
        frontend_url: Optional[str] = None,
    ) -> bool:
        """Send an email verification email."""
        url = frontend_url or self.frontend_url
        verify_link = f"{url}/verify-email?token={verify_token}"

        subject = "[JoySafeter] Verify Your Email"
        html_content = _render("email/email_verification.html", username=username, verify_link=verify_link)
        text_content = f"""\
Welcome to JoySafeter!

Hello, {username}! Thanks for signing up.

Click the link below to verify your email:
{verify_link}

This link will expire in 72 hours.

---
JoySafeter Team"""

        return await self.send_email(to_email, subject, html_content, text_content)


email_service = EmailService()
