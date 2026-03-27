from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from email_ops.domain import (
    AccountConfig,
    AuthConfig,
    CONFIG_VERSION,
    EXAMPLE_CONFIG,
    IdentityConfig,
    KEYRING_SERVICE,
    PROVIDER_PRESETS,
    ProxyConfig,
    ServerConfig,
    EmailOpsError,
    MigrationRequiredError,
    auth_secret_placeholder,
    is_placeholder_secret,
)

try:
    import keyring

    KEYRING_AVAILABLE = True
except ImportError:
    keyring = None
    KEYRING_AVAILABLE = False


DEFAULT_CONFIG = Path(
    os.environ.get("CODEX_MAIL_ACCOUNTS", "~/.config/codex-mail/accounts.json")
).expanduser()


def resolve_config_path(config: str | Path | None = None) -> Path:
    if config is None:
        return DEFAULT_CONFIG
    if isinstance(config, Path):
        return config.expanduser()
    return Path(config).expanduser()


def render_config(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def render_example_config() -> str:
    return render_config(EXAMPLE_CONFIG)


def security_from_flags(*, ssl_enabled: bool = True, starttls: bool = False) -> str:
    if ssl_enabled:
        return "ssl"
    if starttls:
        return "starttls"
    return "plain"


def security_to_flags(mode: str) -> tuple[bool, bool]:
    if mode == "ssl":
        return True, False
    if mode == "starttls":
        return False, True
    return False, False


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def secret_keyring_name(account_name: str) -> str:
    return f"account:{account_name}"


def store_secret_secure(account_name: str, secret: str) -> bool:
    if not KEYRING_AVAILABLE:
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, secret_keyring_name(account_name), secret)
        return True
    except Exception:
        return False


def retrieve_secret_secure(keyring_key: str) -> str | None:
    if not KEYRING_AVAILABLE:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, keyring_key)
    except Exception:
        return None


def delete_secret_secure(keyring_key: str) -> bool:
    if not KEYRING_AVAILABLE:
        return False
    try:
        keyring.delete_password(KEYRING_SERVICE, keyring_key)
        return True
    except Exception:
        return False


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise EmailOpsError(
            f"account config not found: {path}\nCreate accounts.json first, or set CODEX_MAIL_ACCOUNTS to point to your config file.",
            code="config_not_found",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EmailOpsError(f"failed to parse config file {path}: {exc}", code="invalid_config") from exc
    if not isinstance(data, dict):
        raise EmailOpsError("config file root must be a JSON object", code="invalid_config")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        os.chmod(temp_path, 0o600)
        handle.write(render_config(data))
    os.replace(temp_path, path)
    os.chmod(path, 0o600)


def _blank_v2() -> dict[str, Any]:
    return {"version": CONFIG_VERSION, "accounts": {}}


def _normalize_proxy(raw: Any, *, context: str) -> ProxyConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise EmailOpsError(f"{context} has an invalid proxy config shape", code="invalid_config")

    proxy_type = str(raw.get("type") or "").strip().lower()
    host = str(raw.get("host") or "").strip()
    port = raw.get("port")
    if proxy_type not in {"socks5", "http_connect"}:
        raise EmailOpsError(f"{context} has an unsupported proxy type: {proxy_type or '<missing>'}", code="invalid_config")
    if not host:
        raise EmailOpsError(f"{context} is missing proxy.host", code="invalid_config")
    if port in (None, ""):
        raise EmailOpsError(f"{context} is missing proxy.port", code="invalid_config")

    return ProxyConfig(
        type=proxy_type,
        host=host,
        port=int(port),
        username=str(raw.get("username") or ""),
        password=str(raw.get("password") or ""),
        remote_dns=bool(raw.get("remote_dns", True)),
    )


def _server_from_v2(raw: Any, *, context: str) -> ServerConfig:
    if not isinstance(raw, dict):
        raise EmailOpsError(f"{context} is missing server settings", code="invalid_config")
    host = str(raw.get("host") or "").strip()
    port = raw.get("port")
    security = str(raw.get("security") or "").strip().lower()
    if not host or port in (None, ""):
        raise EmailOpsError(f"{context} is missing host/port", code="invalid_config")
    if security not in {"ssl", "starttls", "plain"}:
        raise EmailOpsError(f"{context} has invalid security mode: {security or '<missing>'}", code="invalid_config")
    return ServerConfig(host=host, port=int(port), security=security)


def _account_from_v2(name: str, raw: Any) -> AccountConfig:
    if not isinstance(raw, dict):
        raise EmailOpsError(f"account {name} must be a JSON object", code="invalid_config")
    provider = str(raw.get("provider") or "custom").strip().lower()
    identity_raw = raw.get("identity")
    auth_raw = raw.get("auth")
    servers_raw = raw.get("servers")
    if not isinstance(identity_raw, dict):
        raise EmailOpsError(f"account {name} is missing identity", code="invalid_config")
    if not isinstance(auth_raw, dict):
        raise EmailOpsError(f"account {name} is missing auth", code="invalid_config")
    if not isinstance(servers_raw, dict):
        raise EmailOpsError(f"account {name} is missing servers", code="invalid_config")

    identity = IdentityConfig(
        email=str(identity_raw.get("email") or "").strip(),
        login_user=str(identity_raw.get("login_user") or "").strip(),
        display_name=str(identity_raw.get("display_name") or "").strip(),
    )
    auth = AuthConfig(
        mode=str(auth_raw.get("mode") or "password").strip(),
        storage=str(auth_raw.get("storage") or "config_file").strip(),
        secret=str(auth_raw.get("secret") or "").strip() or None,
        keyring_key=str(auth_raw.get("keyring_key") or "").strip() or None,
    )
    if auth.storage not in {"config_file", "keyring"}:
        raise EmailOpsError(f"account {name} has invalid auth.storage", code="invalid_config")
    if auth.storage == "keyring":
        if not auth.keyring_key:
            raise EmailOpsError(f"account {name} is missing auth.keyring_key", code="invalid_config")
        secret = retrieve_secret_secure(auth.keyring_key)
        if not secret:
            raise EmailOpsError(
                f"account {name}: credential stored in keyring but keyring access failed",
                code="keyring_unavailable",
            )
        auth = AuthConfig(mode=auth.mode, storage=auth.storage, secret=secret, keyring_key=auth.keyring_key)
    elif not auth.secret:
        raise EmailOpsError(f"account {name} is missing auth.secret", code="invalid_config")

    if not identity.email or not identity.login_user or not identity.display_name:
        raise EmailOpsError(f"account {name} has incomplete identity fields", code="invalid_config")

    return AccountConfig(
        name=name,
        provider=provider,
        identity=identity,
        auth=auth,
        imap=_server_from_v2(servers_raw.get("imap"), context=f"account {name}.servers.imap"),
        smtp=_server_from_v2(servers_raw.get("smtp"), context=f"account {name}.servers.smtp"),
        proxy=_normalize_proxy(raw.get("proxy"), context=f"account {name}"),
    )


def serialize_account(account: AccountConfig) -> dict[str, Any]:
    auth_secret = account.auth.secret if account.auth.storage == "config_file" else None
    return {
        "provider": account.provider,
        "identity": {
            "email": account.email,
            "login_user": account.login_user,
            "display_name": account.display_name,
        },
        "auth": {
            "mode": account.auth.mode,
            "storage": account.auth.storage,
            "secret": auth_secret,
            "keyring_key": account.auth.keyring_key,
        },
        "servers": {
            "imap": {
                "host": account.imap.host,
                "port": account.imap.port,
                "security": account.imap.security,
            },
            "smtp": {
                "host": account.smtp.host,
                "port": account.smtp.port,
                "security": account.smtp.security,
            },
        },
        "proxy": (
            {
                "type": account.proxy.type,
                "host": account.proxy.host,
                "port": account.proxy.port,
                "username": account.proxy.username or None,
                "password": account.proxy.password or None,
                "remote_dns": account.proxy.remote_dns,
            }
            if account.proxy
            else None
        ),
    }


def load_v2_document(path: Path) -> dict[str, Any]:
    raw = _load_json(path)
    version = raw.get("version")
    if version != CONFIG_VERSION:
        raise MigrationRequiredError(str(path))
    accounts = raw.get("accounts")
    if not isinstance(accounts, dict):
        raise EmailOpsError("config file must include an accounts object", code="invalid_config")
    return raw


def load_v2_for_update(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _blank_v2()
    return load_v2_document(path)


def load_account(name: str, config_path: str | Path | None = None) -> AccountConfig:
    path = resolve_config_path(config_path)
    raw = load_v2_document(path)
    accounts = raw["accounts"]
    account_raw = accounts.get(name)
    if account_raw is None:
        raise EmailOpsError(f"account not found: {name}", code="account_not_found")
    return _account_from_v2(name, account_raw)


def upsert_account(account: AccountConfig, config_path: str | Path | None = None) -> None:
    path = resolve_config_path(config_path)
    raw = load_v2_for_update(path)
    accounts = raw.setdefault("accounts", {})
    accounts[account.name] = serialize_account(account)
    _write_json(path, raw)


def delete_account_secret(name: str, config_path: str | Path | None = None) -> None:
    account = load_account(name, config_path)
    if account.auth.storage == "keyring" and account.auth.keyring_key:
        delete_secret_secure(account.auth.keyring_key)


def read_config_version(config_path: str | Path | None = None) -> int | None:
    path = resolve_config_path(config_path)
    if not path.exists():
        return None
    raw = _load_json(path)
    version = raw.get("version")
    return int(version) if isinstance(version, int) else 1


def _preset_values(provider: str) -> tuple[str, ServerConfig | None, ServerConfig | None]:
    preset = PROVIDER_PRESETS.get(provider, {})
    return (
        str(preset.get("auth_mode") or "password"),
        preset.get("imap"),
        preset.get("smtp"),
    )


def migrate_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = resolve_config_path(config_path)
    raw = _load_json(path)
    version = raw.get("version")
    if version == CONFIG_VERSION:
        return {
            "config": str(path),
            "backup_written": "",
            "migration_status": "already_current",
            "config_version": CONFIG_VERSION,
        }
    accounts_raw = raw.get("accounts")
    if not isinstance(accounts_raw, list):
        raise EmailOpsError("v1 config file must include an accounts array", code="invalid_config")

    migrated: dict[str, Any] = _blank_v2()
    migrated_accounts: dict[str, Any] = {}
    for index, item in enumerate(accounts_raw, start=1):
        if not isinstance(item, dict):
            raise EmailOpsError(f"account entry {index} must be a JSON object", code="invalid_config")
        name = str(item.get("name") or "").strip()
        if not name:
            raise EmailOpsError(f"account entry {index} is missing name", code="invalid_config")
        provider = str(item.get("provider") or "custom").strip().lower()
        preset_auth_mode, preset_imap, preset_smtp = _preset_values(provider)
        merged = deep_merge(
            {
                "auth_mode": preset_auth_mode,
                "imap": (
                    {"host": preset_imap.host, "port": preset_imap.port, "security": preset_imap.security}
                    if preset_imap
                    else {}
                ),
                "smtp": (
                    {"host": preset_smtp.host, "port": preset_smtp.port, "security": preset_smtp.security}
                    if preset_smtp
                    else {}
                ),
            },
            item,
        )

        auth_secret = str(merged.get("auth_secret") or "").strip()
        auth_mode = str(merged.get("auth_mode") or preset_auth_mode).strip()
        if auth_secret == "<stored-in-keyring>":
            auth_storage = "keyring"
            auth_value = None
            keyring_key = secret_keyring_name(name)
        else:
            auth_storage = "config_file"
            auth_value = auth_secret or auth_secret_placeholder(auth_mode)
            keyring_key = None

        imap_raw = merged.get("imap") or {}
        smtp_raw = merged.get("smtp") or {}
        imap_host = str(imap_raw.get("host") or "").strip()
        smtp_host = str(smtp_raw.get("host") or "").strip()
        imap_port = imap_raw.get("port")
        smtp_port = smtp_raw.get("port")
        if not imap_host or imap_port in (None, ""):
            raise EmailOpsError(f"account {name} is missing imap host/port during migration", code="invalid_config")
        if not smtp_host or smtp_port in (None, ""):
            raise EmailOpsError(f"account {name} is missing smtp host/port during migration", code="invalid_config")
        imap_security = str(imap_raw.get("security") or "").strip().lower() or security_from_flags(
            ssl_enabled=bool(imap_raw.get("ssl", True)),
            starttls=bool(imap_raw.get("starttls", False)),
        )
        smtp_security = str(smtp_raw.get("security") or "").strip().lower() or security_from_flags(
            ssl_enabled=bool(smtp_raw.get("ssl", True)),
            starttls=bool(smtp_raw.get("starttls", False)),
        )

        migrated_accounts[name] = {
            "provider": provider,
            "identity": {
                "email": str(merged.get("email") or "").strip(),
                "login_user": str(merged.get("login_user") or merged.get("email") or "").strip(),
                "display_name": str(merged.get("display_name") or merged.get("email") or "").strip(),
            },
            "auth": {
                "mode": auth_mode,
                "storage": auth_storage,
                "secret": auth_value,
                "keyring_key": keyring_key,
            },
            "servers": {
                "imap": {
                    "host": imap_host,
                    "port": int(imap_port),
                    "security": imap_security,
                },
                "smtp": {
                    "host": smtp_host,
                    "port": int(smtp_port),
                    "security": smtp_security,
                },
            },
            "proxy": item.get("proxy"),
        }
    migrated["accounts"] = migrated_accounts

    backup_path = path.with_name(path.name + ".v1.bak")
    shutil.copy2(path, backup_path)
    _write_json(path, migrated)
    return {
        "config": str(path),
        "backup_written": str(backup_path),
        "migration_status": "migrated",
        "config_version": CONFIG_VERSION,
        "account_count": len(migrated_accounts),
    }


def doctor_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = resolve_config_path(config_path)
    result: dict[str, Any] = {"config": str(path), "accounts": []}
    if not path.exists():
        result["doctor_status"] = "needs_attention"
        result["issues"] = ["account config does not exist"]
        result["next_step"] = "run setup_account to create a v2 config."
        return result

    raw = _load_json(path)
    version = raw.get("version")
    if version != CONFIG_VERSION:
        result["doctor_status"] = "needs_attention"
        result["config_version"] = 1
        result["migration_required"] = True
        result["issues"] = ["config file is still using schema v1"]
        result["next_step"] = "run migrate_config before using mailbox operations."
        return result

    accounts = raw.get("accounts")
    if not isinstance(accounts, dict):
        raise EmailOpsError("config file must include an accounts object", code="invalid_config")

    any_issues = False
    for name, account_raw in accounts.items():
        issues: list[str] = []
        notes: list[str] = []
        try:
            account = _account_from_v2(name, account_raw)
            if account.auth.storage == "config_file" and is_placeholder_secret(account.auth.secret):
                issues.append("auth.secret is missing or still uses a placeholder")
            notes.append(f"auth_mode: {account.auth.mode}")
            notes.append(f"secret_storage: {account.auth.storage}")
            if account.proxy:
                notes.append(
                    f"proxy: {account.proxy.type}://{account.proxy.host}:{account.proxy.port} (remote_dns={account.proxy.remote_dns})"
                )
        except EmailOpsError as exc:
            issues.append(exc.message)
        result["accounts"].append(
            {
                "name": name,
                "status": "needs_attention" if issues else "ok",
                "issues": issues,
                "notes": notes,
            }
        )
        if issues:
            any_issues = True

    result["config_version"] = CONFIG_VERSION
    result["account_count"] = len(accounts)
    result["doctor_status"] = "needs_attention" if any_issues else "ok"
    return result


__all__ = [
    "DEFAULT_CONFIG",
    "KEYRING_AVAILABLE",
    "delete_secret_secure",
    "doctor_config",
    "load_account",
    "load_v2_document",
    "load_v2_for_update",
    "migrate_config",
    "read_config_version",
    "render_example_config",
    "render_config",
    "resolve_config_path",
    "retrieve_secret_secure",
    "secret_keyring_name",
    "security_to_flags",
    "store_secret_secure",
    "upsert_account",
]
