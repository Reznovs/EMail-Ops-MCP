from __future__ import annotations

from dataclasses import dataclass


SecurityMode = str
SecretStorage = str
ProxyType = str


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    security: SecurityMode = "ssl"

    @property
    def uses_ssl(self) -> bool:
        return self.security == "ssl"

    @property
    def uses_starttls(self) -> bool:
        return self.security == "starttls"


@dataclass(frozen=True)
class ProxyConfig:
    type: ProxyType
    host: str
    port: int
    username: str = ""
    password: str = ""
    remote_dns: bool = True


@dataclass(frozen=True)
class IdentityConfig:
    email: str
    login_user: str
    display_name: str


@dataclass(frozen=True)
class AuthConfig:
    mode: str
    storage: SecretStorage
    secret: str | None = None
    keyring_key: str | None = None


@dataclass(frozen=True)
class AccountConfig:
    name: str
    provider: str
    identity: IdentityConfig
    auth: AuthConfig
    imap: ServerConfig
    smtp: ServerConfig
    proxy: ProxyConfig | None = None

    @property
    def email(self) -> str:
        return self.identity.email

    @property
    def login_user(self) -> str:
        return self.identity.login_user

    @property
    def display_name(self) -> str:
        return self.identity.display_name

    @property
    def auth_mode(self) -> str:
        return self.auth.mode


@dataclass(frozen=True)
class MessageSummary:
    uid: str
    date: str
    sender: str
    subject: str
    preview: str = ""


@dataclass(frozen=True)
class AttachmentInfo:
    filename: str
    original_filename: str
    content_type: str
    size: int
