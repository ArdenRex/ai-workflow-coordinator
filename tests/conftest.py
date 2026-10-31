"""Test env — must run before anything imports app.config (settings are cached)."""
import os

for k, v in {
    "DATABASE_URL": "postgresql://awc:awc@localhost:5432/awc_test",
    "GROQ_API_KEY": "test",
    "SLACK_BOT_TOKEN": "xoxb-test",
    "SLACK_SIGNING_SECRET": "test",
    "APP_SECRET_KEY": "test-secret-key-for-local-testing-only",
    "WHATSAPP_VERIFY_TOKEN": "verify-me",
    "WHATSAPP_APP_SECRET": "meta-app-secret",
    "WHATSAPP_APP_ID": "1234567890",
    "WHATSAPP_CONFIG_ID": "9876543210",
    "WHATSAPP_REGISTRATION_PIN": "123456",
    "ADMIN_EMAILS": "boss@example.com",
}.items():
    os.environ.setdefault(k, v)
