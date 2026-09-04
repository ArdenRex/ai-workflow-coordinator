"""
Signup & billing notification dispatcher.

Channel: Gmail SMTP — sends an email to NOTIFY_EMAIL.

Required .env vars:
  GMAIL_USER         = wahajkashan456@gmail.com
  GMAIL_APP_PASSWORD = <16-char app password from myaccount.google.com/apppasswords>
  NOTIFY_EMAIL       = wahajkashan456@gmail.com
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import get_settings

logger = logging.getLogger(__name__)


def _send_gmail(subject: str, body_html: str, body_text: str) -> None:
    """Send an email via Gmail SMTP using an App Password."""
    s = get_settings()

    # Detailed config check — errors will appear in Railway logs
    if not s.gmail_user:
        logger.error("NOTIFY: GMAIL_USER is not set — skipping email.")
        return
    if not s.gmail_app_password:
        logger.error("NOTIFY: GMAIL_APP_PASSWORD is not set — skipping email.")
        return
    if not s.notify_email:
        logger.error("NOTIFY: NOTIFY_EMAIL is not set — skipping email.")
        return

    logger.info("NOTIFY: Sending email to %s from %s", s.notify_email, s.gmail_user)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"AI Workflow Coordinator <{s.gmail_user}>"
    msg["To"]      = s.notify_email

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(s.gmail_user, s.gmail_app_password)
            server.sendmail(s.gmail_user, s.notify_email, msg.as_string())
        logger.info("Notification email sent to %s | subject: %s", s.notify_email, subject)
    except Exception as exc:
        logger.error("Failed to send notification email: %s", exc)


def _send_gmail_to(to_email: str, subject: str, body_html: str, body_text: str) -> bool:
    """
    Send an email via Gmail SMTP to an arbitrary recipient (unlike _send_gmail,
    which always sends to the site owner's NOTIFY_EMAIL). Used for password
    reset emails, which must land in the *user's* inbox.

    Returns True on success, False otherwise (never raises).
    """
    s = get_settings()

    if not s.gmail_user:
        logger.error("NOTIFY: GMAIL_USER is not set — skipping email.")
        return False
    if not s.gmail_app_password:
        logger.error("NOTIFY: GMAIL_APP_PASSWORD is not set — skipping email.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"AI Workflow Coordinator <{s.gmail_user}>"
    msg["To"]      = to_email

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(s.gmail_user, s.gmail_app_password)
            server.sendmail(s.gmail_user, to_email, msg.as_string())
        logger.info("Email sent to %s | subject: %s", to_email, subject)
        return True
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to_email, exc)
        return False


def send_password_reset_email(name: str, to_email: str, reset_link: str) -> bool:
    """
    Sends the "reset your password" email directly to the user who requested it.
    Link expires in 60 minutes (see crud.RESET_TOKEN_EXPIRE_MINUTES).
    """
    subject = "Reset your AI Workflow Coordinator password"

    body_html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto;padding:24px;
                border:1px solid #e2e8f0;border-radius:8px;">
      <h2 style="color:#1a202c;margin-top:0;">Reset your password</h2>
      <p style="color:#4a5568;font-size:14px;line-height:1.6;">
        Hi {name or 'there'}, we received a request to reset the password for your
        AI Workflow Coordinator account.
      </p>
      <p style="text-align:center;margin:28px 0;">
        <a href="{reset_link}"
           style="background:#c81f30;color:#ffffff;text-decoration:none;
                  padding:12px 28px;border-radius:8px;font-weight:600;
                  font-size:14px;display:inline-block;">
          Reset Password
        </a>
      </p>
      <p style="color:#718096;font-size:12px;line-height:1.6;">
        This link expires in 60 minutes. If you didn't request this, you can
        safely ignore this email — your password will not be changed.
      </p>
      <p style="color:#a0aec0;font-size:11px;word-break:break-all;">
        Or copy this link: {reset_link}
      </p>
    </div>
    """

    body_text = (
        f"Hi {name or 'there'},\n\n"
        f"We received a request to reset the password for your AI Workflow "
        f"Coordinator account.\n\n"
        f"Reset your password here (expires in 60 minutes):\n{reset_link}\n\n"
        f"If you didn't request this, you can safely ignore this email.\n"
    )

    return _send_gmail_to(to_email, subject, body_html, body_text)


def notify_new_signup(name: str, email: str) -> None:
    """
    Called immediately after a user registers.
    Card status is always 'No card on file' at this point —
    a separate notify_card_added() fires when billing webhook confirms payment.
    """
    subject = f"🆕 New Signup — {name}"

    body_html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto;padding:24px;
                border:1px solid #e2e8f0;border-radius:8px;">
      <h2 style="color:#1a202c;margin-top:0;">New User Registered</h2>
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <tr>
          <td style="padding:8px 0;color:#718096;width:140px;">Name</td>
          <td style="padding:8px 0;color:#1a202c;font-weight:600;">{name}</td>
        </tr>
        <tr style="background:#f7fafc;">
          <td style="padding:8px 6px;color:#718096;">Email</td>
          <td style="padding:8px 6px;color:#1a202c;">{email}</td>
        </tr>
        <tr>
          <td style="padding:8px 0;color:#718096;">Card</td>
          <td style="padding:8px 0;color:#e53e3e;font-weight:600;">❌ No card on file</td>
        </tr>
        <tr style="background:#f7fafc;">
          <td style="padding:8px 6px;color:#718096;">Trial</td>
          <td style="padding:8px 6px;color:#1a202c;">7-day free trial started</td>
        </tr>
      </table>
    </div>
    """

    body_text = (
        f"New signup on AI Workflow Coordinator\n"
        f"Name:  {name}\n"
        f"Email: {email}\n"
        f"Card:  No card on file\n"
        f"Trial: 7-day free trial started\n"
    )

    _send_gmail(subject, body_html, body_text)


def notify_card_added(name: str, email: str, plan: str = "Pro") -> None:
    """
    Called when Polar fires subscription.created — user has entered card details
    and activated a paid subscription.
    """
    subject = f"💳 Card Added & Subscribed — {name}"

    body_html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto;padding:24px;
                border:1px solid #e2e8f0;border-radius:8px;">
      <h2 style="color:#1a202c;margin-top:0;">User Subscribed 🎉</h2>
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <tr>
          <td style="padding:8px 0;color:#718096;width:140px;">Name</td>
          <td style="padding:8px 0;color:#1a202c;font-weight:600;">{name}</td>
        </tr>
        <tr style="background:#f7fafc;">
          <td style="padding:8px 6px;color:#718096;">Email</td>
          <td style="padding:8px 6px;color:#1a202c;">{email}</td>
        </tr>
        <tr>
          <td style="padding:8px 0;color:#718096;">Card</td>
          <td style="padding:8px 0;color:#38a169;font-weight:600;">✅ Card on file</td>
        </tr>
        <tr style="background:#f7fafc;">
          <td style="padding:8px 6px;color:#718096;">Plan</td>
          <td style="padding:8px 6px;color:#1a202c;font-weight:600;">{plan}</td>
        </tr>
      </table>
    </div>
    """

    body_text = (
        f"User subscribed on AI Workflow Coordinator\n"
        f"Name:  {name}\n"
        f"Email: {email}\n"
        f"Card:  Card on file\n"
        f"Plan:  {plan}\n"
    )

    _send_gmail(subject, body_html, body_text)
