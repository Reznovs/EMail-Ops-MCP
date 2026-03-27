from __future__ import annotations

from typing import Any

from .models import ServerConfig


DEFAULT_FOLDER = "INBOX"
DEFAULT_LIMIT = 20
DEFAULT_SCAN = 200
CONFIG_VERSION = 2
KEYRING_SERVICE = "codex-mail"

PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "gmail": {
        "auth_mode": "app_password",
        "imap": ServerConfig(host="imap.gmail.com", port=993, security="ssl"),
        "smtp": ServerConfig(host="smtp.gmail.com", port=465, security="ssl"),
    },
    "qq": {
        "auth_mode": "auth_code",
        "imap": ServerConfig(host="imap.qq.com", port=993, security="ssl"),
        "smtp": ServerConfig(host="smtp.qq.com", port=465, security="ssl"),
    },
}

EXAMPLE_CONFIG: dict[str, Any] = {
    "version": CONFIG_VERSION,
    "accounts": {
        "work": {
            "provider": "gmail",
            "identity": {
                "email": "your.name@example.com",
                "login_user": "your.name@example.com",
                "display_name": "Your Name",
            },
            "auth": {
                "mode": "app_password",
                "storage": "config_file",
                "secret": "<app-password-or-auth-code>",
                "keyring_key": None,
            },
            "servers": {
                "imap": {"host": "imap.gmail.com", "port": 993, "security": "ssl"},
                "smtp": {"host": "smtp.gmail.com", "port": 465, "security": "ssl"},
            },
            "proxy": None,
        }
    },
}


def provider_advice(provider: str) -> str:
    if provider == "gmail":
        return "Use a Gmail app password after enabling 2-Step Verification. Add proxy settings only when your network requires it."
    if provider == "qq":
        return "Enable IMAP/SMTP in QQ Mail settings and generate an auth code."
    return "For custom providers, confirm the IMAP/SMTP host, port, and transport security mode."


def auth_secret_placeholder(auth_mode: str) -> str:
    if auth_mode == "app_password":
        return "<app-password>"
    if auth_mode == "auth_code":
        return "<auth-code>"
    return "<password-or-token>"


def is_placeholder_secret(value: str | None) -> bool:
    secret = (value or "").strip()
    return not secret or (secret.startswith("<") and secret.endswith(">"))
