from __future__ import annotations

from pathlib import Path
from typing import Any

from email_ops.domain import (
    AccountConfig,
    AuthConfig,
    IdentityConfig,
    PROVIDER_PRESETS,
    ProxyConfig,
    ServerConfig,
    DEFAULT_FOLDER,
    DEFAULT_LIMIT,
    DEFAULT_SCAN,
    EmailOpsError,
    auth_secret_placeholder,
    is_placeholder_secret,
    provider_advice,
)
from email_ops.infrastructure.config_store import (
    delete_secret_secure,
    doctor_config,
    load_account,
    load_v2_for_update,
    migrate_config,
    resolve_config_path,
    secret_keyring_name,
    store_secret_secure,
    upsert_account,
)
from email_ops.infrastructure.mail_transport import test_imap_login, test_smtp_login


def _server_from_raw(raw: Any, *, fallback: ServerConfig | None = None) -> ServerConfig | None:
    if not isinstance(raw, dict):
        return fallback
    host = str(raw.get("host") or "").strip()
    port = raw.get("port")
    security = str(raw.get("security") or "").strip().lower()
    if not host or port in (None, "") or security not in {"ssl", "starttls", "plain"}:
        return fallback
    return ServerConfig(host=host, port=int(port), security=security)


def _merge_server(
    base: ServerConfig | None,
    *,
    host: str | None,
    port: int | None,
    disable_ssl: bool,
    starttls: bool,
    required_name: str,
) -> ServerConfig:
    default_security = base.security if base else "ssl"
    security = default_security
    if disable_ssl and starttls:
        security = "starttls"
    elif disable_ssl:
        security = "plain"
    elif starttls:
        security = "starttls"

    final_host = (host or (base.host if base else "")).strip()
    final_port = port if port is not None else (base.port if base else None)
    if not final_host or final_port in (None, ""):
        raise EmailOpsError(f"{required_name} host and port are required", code="invalid_setup")
    return ServerConfig(host=final_host, port=int(final_port), security=security)


def _proxy_from_raw(raw: Any) -> ProxyConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise EmailOpsError("proxy configuration must be a JSON object", code="invalid_setup")
    proxy_type = str(raw.get("type") or "").strip().lower()
    host = str(raw.get("host") or "").strip()
    port = raw.get("port")
    if proxy_type not in {"socks5", "http_connect"}:
        raise EmailOpsError("proxy.type must be socks5 or http_connect", code="invalid_setup")
    if not host or port in (None, ""):
        raise EmailOpsError("proxy.host and proxy.port are required", code="invalid_setup")
    return ProxyConfig(
        type=proxy_type,
        host=host,
        port=int(port),
        username=str(raw.get("username") or ""),
        password=str(raw.get("password") or ""),
        remote_dns=bool(raw.get("remote_dns", True)),
    )


def _merge_proxy(
    existing_raw: Any,
    *,
    proxy_type: str | None,
    proxy_host: str | None,
    proxy_port: int | None,
    proxy_username: str | None,
    proxy_password: str | None,
    proxy_remote_dns: bool,
    proxy_local_dns: bool,
    no_proxy: bool,
) -> ProxyConfig | None:
    if no_proxy:
        return None
    current = _proxy_from_raw(existing_raw)
    has_proxy_args = any(
        [
            proxy_type,
            proxy_host,
            proxy_port is not None,
            proxy_username is not None,
            proxy_password is not None,
            proxy_remote_dns,
            proxy_local_dns,
        ]
    )
    if not has_proxy_args:
        return current

    final_type = str(proxy_type or (current.type if current else "")).strip().lower()
    final_host = str(proxy_host or (current.host if current else "")).strip()
    final_port = proxy_port if proxy_port is not None else (current.port if current else None)
    final_username = proxy_username if proxy_username is not None else (current.username if current else "")
    final_password = proxy_password if proxy_password is not None else (current.password if current else "")
    remote_dns = current.remote_dns if current else True
    if proxy_remote_dns:
        remote_dns = True
    if proxy_local_dns:
        remote_dns = False
    if final_type not in {"socks5", "http_connect"}:
        raise EmailOpsError("proxy_type must be socks5 or http_connect", code="invalid_setup")
    if not final_host or final_port in (None, ""):
        raise EmailOpsError("proxy_host and proxy_port are required when proxy is enabled", code="invalid_setup")
    return ProxyConfig(
        type=final_type,
        host=final_host,
        port=int(final_port),
        username=final_username or "",
        password=final_password or "",
        remote_dns=remote_dns,
    )


def setup_account_service(
    *,
    account: str,
    provider: str,
    email: str,
    config_path: str | Path | None = None,
    login_user: str | None = None,
    display_name: str | None = None,
    auth_mode: str | None = None,
    auth_secret: str | None = None,
    imap_host: str | None = None,
    imap_port: int | None = None,
    imap_no_ssl: bool = False,
    imap_starttls: bool = False,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_no_ssl: bool = False,
    smtp_starttls: bool = False,
    proxy_type: str | None = None,
    proxy_host: str | None = None,
    proxy_port: int | None = None,
    proxy_username: str | None = None,
    proxy_password: str | None = None,
    proxy_remote_dns: bool = False,
    proxy_local_dns: bool = False,
    no_proxy: bool = False,
) -> dict[str, Any]:
    name = account.strip()
    provider_name = provider.strip().lower()
    mailbox_email = email.strip()
    if not name:
        raise EmailOpsError("account is required", code="invalid_setup")
    if not provider_name:
        raise EmailOpsError("provider is required", code="invalid_setup")
    if not mailbox_email:
        raise EmailOpsError("email is required", code="invalid_setup")

    config = resolve_config_path(config_path)
    document = load_v2_for_update(config)
    existing_raw = document["accounts"].get(name)
    existing_provider = str(existing_raw.get("provider") or "").strip().lower() if isinstance(existing_raw, dict) else ""
    existing_identity = existing_raw.get("identity") if isinstance(existing_raw, dict) else {}
    existing_auth = existing_raw.get("auth") if isinstance(existing_raw, dict) else {}
    existing_servers = existing_raw.get("servers") if isinstance(existing_raw, dict) else {}
    provider_changed = bool(existing_provider and existing_provider != provider_name)
    email_changed = bool(isinstance(existing_identity, dict) and str(existing_identity.get("email") or "").strip() and str(existing_identity.get("email") or "").strip() != mailbox_email)
    preserve_defaults = bool(existing_raw) and not provider_changed and not email_changed

    preset = PROVIDER_PRESETS.get(provider_name, {})
    base_imap = _server_from_raw(existing_servers.get("imap") if isinstance(existing_servers, dict) else None, fallback=preset.get("imap"))
    base_smtp = _server_from_raw(existing_servers.get("smtp") if isinstance(existing_servers, dict) else None, fallback=preset.get("smtp"))

    final_auth_mode = (auth_mode or (existing_auth.get("mode") if preserve_defaults and isinstance(existing_auth, dict) else None) or preset.get("auth_mode") or "password").strip()
    final_login_user = (login_user or (existing_identity.get("login_user") if preserve_defaults and isinstance(existing_identity, dict) else None) or mailbox_email).strip()
    final_display_name = (display_name or (existing_identity.get("display_name") if preserve_defaults and isinstance(existing_identity, dict) else None) or mailbox_email).strip()

    previous_storage = str(existing_auth.get("storage") or "config_file") if isinstance(existing_auth, dict) else "config_file"
    previous_keyring_key = str(existing_auth.get("keyring_key") or "").strip() if isinstance(existing_auth, dict) else ""
    previous_secret = str(existing_auth.get("secret") or "").strip() if isinstance(existing_auth, dict) else ""
    secret_status = "provided"
    secret_storage = previous_storage
    stored_securely = False
    keyring_key = previous_keyring_key or secret_keyring_name(name)
    secret_value: str | None = None

    if auth_secret is not None:
        candidate = auth_secret.strip()
        if is_placeholder_secret(candidate):
            secret_status = "placeholder"
            secret_storage = "config_file"
            secret_value = auth_secret_placeholder(final_auth_mode)
            if previous_storage == "keyring" and previous_keyring_key:
                delete_secret_secure(previous_keyring_key)
                keyring_key = None
        else:
            if store_secret_secure(name, candidate):
                secret_storage = "keyring"
                stored_securely = True
                secret_value = candidate
                keyring_key = secret_keyring_name(name)
                if previous_storage == "keyring" and previous_keyring_key and previous_keyring_key != keyring_key:
                    delete_secret_secure(previous_keyring_key)
            else:
                secret_storage = "config_file"
                secret_value = candidate
                keyring_key = None
                if previous_storage == "keyring" and previous_keyring_key:
                    delete_secret_secure(previous_keyring_key)
    elif existing_raw:
        if previous_storage == "keyring":
            secret_storage = "keyring"
            keyring_key = previous_keyring_key or secret_keyring_name(name)
            secret_value = None
        else:
            secret_storage = "config_file"
            secret_value = previous_secret or auth_secret_placeholder(final_auth_mode)
            secret_status = "placeholder" if is_placeholder_secret(secret_value) else "provided"
            keyring_key = None
    else:
        secret_storage = "config_file"
        secret_status = "placeholder"
        secret_value = auth_secret_placeholder(final_auth_mode)
        keyring_key = None

    if provider_name in PROVIDER_PRESETS:
        final_imap = _merge_server(
            base_imap or preset.get("imap"),
            host=imap_host,
            port=imap_port,
            disable_ssl=imap_no_ssl,
            starttls=imap_starttls,
            required_name="imap",
        )
        final_smtp = _merge_server(
            base_smtp or preset.get("smtp"),
            host=smtp_host,
            port=smtp_port,
            disable_ssl=smtp_no_ssl,
            starttls=smtp_starttls,
            required_name="smtp",
        )
    else:
        final_imap = _merge_server(
            base_imap,
            host=imap_host,
            port=imap_port,
            disable_ssl=imap_no_ssl,
            starttls=imap_starttls,
            required_name="custom imap",
        )
        final_smtp = _merge_server(
            base_smtp,
            host=smtp_host,
            port=smtp_port,
            disable_ssl=smtp_no_ssl,
            starttls=smtp_starttls,
            required_name="custom smtp",
        )

    final_proxy = _merge_proxy(
        existing_raw.get("proxy") if isinstance(existing_raw, dict) else None,
        proxy_type=proxy_type,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        proxy_username=proxy_username,
        proxy_password=proxy_password,
        proxy_remote_dns=proxy_remote_dns,
        proxy_local_dns=proxy_local_dns,
        no_proxy=no_proxy,
    )

    final_account = AccountConfig(
        name=name,
        provider=provider_name,
        identity=IdentityConfig(
            email=mailbox_email,
            login_user=final_login_user,
            display_name=final_display_name,
        ),
        auth=AuthConfig(
            mode=final_auth_mode,
            storage=secret_storage,
            secret=secret_value,
            keyring_key=keyring_key if secret_storage == "keyring" else None,
        ),
        imap=final_imap,
        smtp=final_smtp,
        proxy=final_proxy,
    )

    upsert_account(final_account, config)
    return {
        "setup_action": "updated" if existing_raw else "created",
        "config_written": str(config),
        "config_version": 2,
        "account": name,
        "provider": provider_name,
        "auth_mode": final_auth_mode,
        "auth_secret_status": secret_status,
        "secret_storage": "keyring" if stored_securely or secret_storage == "keyring" else "config_file",
        "provider_hint": provider_advice(provider_name),
        "next_step": (
            "replace auth.secret with a real secret by rerunning setup_account, then run doctor_account or test_login."
            if secret_status == "placeholder"
            else "run doctor_account or test_login to validate the account."
        ),
    }


def doctor_config_service(*, config_path: str | Path | None = None) -> dict[str, Any]:
    return doctor_config(config_path)


def migrate_config_service(*, config_path: str | Path | None = None) -> dict[str, Any]:
    return migrate_config(config_path)


def test_login_service(
    *,
    account_name: str,
    config_path: str | Path | None = None,
    imap_only: bool = False,
    smtp_only: bool = False,
) -> dict[str, Any]:
    account = load_account(account_name, config_path)
    run_imap = not smtp_only
    run_smtp = not imap_only
    success = True
    result: dict[str, Any] = {
        "account": account.name,
        "provider": account.provider,
        "imap": {"tested": run_imap, "ok": None, "error": ""},
        "smtp": {"tested": run_smtp, "ok": None, "error": ""},
    }
    if run_imap:
        try:
            test_imap_login(account)
            result["imap"]["ok"] = True
        except Exception as exc:
            success = False
            result["imap"]["ok"] = False
            result["imap"]["error"] = str(exc)
    if run_smtp:
        try:
            test_smtp_login(account)
            result["smtp"]["ok"] = True
        except Exception as exc:
            success = False
            result["smtp"]["ok"] = False
            result["smtp"]["error"] = str(exc)
    result["test_login_status"] = "ok" if success else "failed"
    return result


__all__ = [
    "DEFAULT_FOLDER",
    "DEFAULT_LIMIT",
    "DEFAULT_SCAN",
    "doctor_config_service",
    "migrate_config_service",
    "setup_account_service",
    "test_login_service",
]
