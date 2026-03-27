from __future__ import annotations

import base64
import html
import imaplib
import json
import os
import re
import smtplib
import socket
import ssl
import tempfile
from datetime import date
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from pathlib import Path
from typing import Any

from email_ops.domain import AccountConfig, EmailOpsError, ProxyConfig


CONNECT_TIMEOUT = float(os.environ.get("CODEX_MAIL_CONNECT_TIMEOUT", "15"))
APPROVED_ATTACHMENTS_FILE = ".codex-mail-attachments.json"
TEMP_DOWNLOAD_PREFIX = "codex-mail-"


def decode_mime_header(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except Exception:
        return raw.strip()


def clean_html_text(raw: str) -> str:
    text = raw
    text = re.sub(r'(?i)\s+on\w+\s*=\s*["\'][^"\']*["\']', "", text)
    text = re.sub(r'(?i)\s+on\w+\s*=\s*[^\s>]+', "", text)
    text = re.sub(r'(?i)javascript\s*:', "", text)
    text = re.sub(r'(?i)data\s*:', "", text)
    text = re.sub(r'(?i)vbscript\s*:', "", text)
    text = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", text)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p\s*>", "\n", text)
    text = re.sub(r"(?is)</div\s*>", "\n", text)
    text = re.sub(r"(?is)</li\s*>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_body_text(msg: Message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_filename():
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            content = payload.decode(charset, errors="replace")
        except LookupError:
            content = payload.decode("utf-8", errors="replace")
        if part.get_content_type() == "text/plain":
            if content.strip():
                plain_parts.append(content.strip())
        elif part.get_content_type() == "text/html":
            cleaned = clean_html_text(content)
            if cleaned:
                html_parts.append(cleaned)
    if plain_parts:
        return "\n\n".join(plain_parts).strip()
    if html_parts:
        return "\n\n".join(html_parts).strip()
    return ""


def format_preview(text: str, limit: int = 140) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def safe_filename(name: str, fallback: str, max_length: int = 255) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_\u4e00-\u9fff-]+", "_", name.strip())
    cleaned = cleaned.lstrip(".")
    if len(cleaned) > max_length:
        if "." in cleaned:
            base, ext = cleaned.rsplit(".", 1)
            ext = ext[:20]
            cleaned = base[: max_length - len(ext) - 1] + "." + ext
        else:
            cleaned = cleaned[:max_length]
    return cleaned or fallback


def _attachment_manifest_path(target_dir: Path) -> Path:
    return target_dir / APPROVED_ATTACHMENTS_FILE


def _unique_attachment_name(target_dir: Path, filename: str, used_names: set[str]) -> str:
    candidate = filename
    stem = Path(filename).stem or "attachment"
    suffix = Path(filename).suffix
    counter = 2
    while candidate in used_names or (target_dir / candidate).exists():
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    used_names.add(candidate)
    return candidate


def _register_saved_attachments(target_dir: Path, saved: list[Path]) -> None:
    manifest = _attachment_manifest_path(target_dir)
    payload = {
        "version": 1,
        "approved_files": sorted(item.name for item in saved),
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest.chmod(0o600)


def _load_approved_attachment_names(target_dir: Path) -> set[str]:
    manifest = _attachment_manifest_path(target_dir)
    if not manifest.is_file():
        raise EmailOpsError("attachment is not in an approved download directory", code="invalid_request")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EmailOpsError("attachment approval manifest is invalid", code="invalid_request") from exc
    approved = payload.get("approved_files")
    if not isinstance(approved, list) or not all(isinstance(item, str) and item for item in approved):
        raise EmailOpsError("attachment approval manifest is invalid", code="invalid_request")
    return set(approved)


def _validate_send_attachment(path_value: str) -> Path:
    candidate = Path(path_value).expanduser()
    if candidate.is_symlink():
        raise EmailOpsError(f"attachment is not an approved file: {candidate}", code="invalid_request")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise EmailOpsError(f"attachment not found: {candidate}", code="invalid_request") from exc
    if not resolved.is_file():
        raise EmailOpsError(f"attachment is not a file: {candidate}", code="invalid_request")
    parent = resolved.parent
    approved = _load_approved_attachment_names(parent)
    try:
        resolved.relative_to(parent.resolve())
    except ValueError as exc:
        raise EmailOpsError(f"attachment is outside approved directory: {candidate}", code="invalid_request") from exc
    if resolved.name not in approved:
        raise EmailOpsError(f"attachment is not approved for sending: {candidate}", code="invalid_request")
    return resolved


def save_attachments(msg: Message, target_dir: Path) -> list[Path]:
    saved: list[Path] = []
    target_dir.mkdir(parents=True, exist_ok=True)
    target_dir.chmod(0o700)
    used_names: set[str] = set()
    for index, part in enumerate(msg.walk(), start=1):
        filename = part.get_filename()
        if not filename:
            continue
        decoded = decode_mime_header(filename) or f"attachment-{index}"
        final_name = safe_filename(decoded, f"attachment-{index}")
        final_name = _unique_attachment_name(target_dir, final_name, used_names)
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        path = target_dir / final_name
        try:
            path.resolve().relative_to(target_dir.resolve())
        except ValueError:
            continue
        path.write_bytes(payload)
        path.chmod(0o600)
        saved.append(path)
    _register_saved_attachments(target_dir, saved)
    return saved


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("proxy connection closed unexpectedly")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def create_direct_connection(host: str, port: int, timeout: float) -> socket.socket:
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    return sock


def resolve_proxy_destination(host: str, port: int, remote_dns: bool) -> tuple[int, bytes]:
    if remote_dns:
        encoded = host.encode("idna")
        if len(encoded) > 255:
            raise RuntimeError("proxy destination hostname is too long")
        return 0x03, bytes([len(encoded)]) + encoded
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    address = infos[0][4][0]
    if ":" in address:
        return 0x04, socket.inet_pton(socket.AF_INET6, address)
    return 0x01, socket.inet_aton(address)


def create_socks5_connection(host: str, port: int, proxy: ProxyConfig, timeout: float) -> socket.socket:
    sock = create_direct_connection(proxy.host, proxy.port, timeout)
    methods = [0x00]
    if proxy.username or proxy.password:
        methods.append(0x02)
    sock.sendall(bytes([0x05, len(methods), *methods]))
    greeting = recv_exact(sock, 2)
    if greeting[0] != 0x05:
        raise RuntimeError("invalid SOCKS5 proxy response")
    method = greeting[1]
    if method == 0xFF:
        raise RuntimeError("SOCKS5 proxy rejected all authentication methods")
    if method == 0x02:
        username = proxy.username.encode("utf-8")
        password = proxy.password.encode("utf-8")
        if len(username) > 255 or len(password) > 255:
            raise RuntimeError("SOCKS5 proxy credentials are too long")
        sock.sendall(bytes([0x01, len(username)]) + username + bytes([len(password)]) + password)
        auth_reply = recv_exact(sock, 2)
        if auth_reply[1] != 0x00:
            raise RuntimeError("SOCKS5 proxy authentication failed")

    atyp, address = resolve_proxy_destination(host, port, proxy.remote_dns)
    request = b"\x05\x01\x00" + bytes([atyp]) + address + port.to_bytes(2, "big")
    sock.sendall(request)
    reply = recv_exact(sock, 4)
    if reply[1] != 0x00:
        raise RuntimeError(f"SOCKS5 proxy connect failed with code {reply[1]}")
    bound_type = reply[3]
    if bound_type == 0x01:
        recv_exact(sock, 4)
    elif bound_type == 0x03:
        length = recv_exact(sock, 1)[0]
        recv_exact(sock, length)
    elif bound_type == 0x04:
        recv_exact(sock, 16)
    recv_exact(sock, 2)
    return sock


def create_http_connect_connection(host: str, port: int, proxy: ProxyConfig, timeout: float) -> socket.socket:
    sock = create_direct_connection(proxy.host, proxy.port, timeout)
    headers = [
        f"CONNECT {host}:{port} HTTP/1.1",
        f"Host: {host}:{port}",
        "Proxy-Connection: Keep-Alive",
    ]
    if proxy.username or proxy.password:
        token = base64.b64encode(f"{proxy.username}:{proxy.password}".encode("utf-8")).decode("ascii")
        headers.append(f"Proxy-Authorization: Basic {token}")
    payload = ("\r\n".join(headers) + "\r\n\r\n").encode("utf-8")
    sock.sendall(payload)

    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("HTTP proxy closed during CONNECT handshake")
        response += chunk
        if len(response) > 65536:
            raise RuntimeError("HTTP proxy response headers are too large")
    status_line = response.split(b"\r\n", 1)[0].decode("iso-8859-1", errors="replace")
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or parts[1] != "200":
        raise RuntimeError(f"HTTP CONNECT failed: {status_line}")
    return sock


def create_connection(host: str, port: int, proxy: ProxyConfig | None, timeout: float = CONNECT_TIMEOUT) -> socket.socket:
    if proxy is None:
        return create_direct_connection(host, port, timeout)
    if proxy.type == "socks5":
        return create_socks5_connection(host, port, proxy, timeout)
    if proxy.type == "http_connect":
        return create_http_connect_connection(host, port, proxy, timeout)
    raise RuntimeError(f"unsupported proxy type: {proxy.type}")


class ProxyIMAP4(imaplib.IMAP4):
    def __init__(self, host: str, port: int, *, proxy: ProxyConfig, timeout: float) -> None:
        self._proxy = proxy
        self._connect_timeout = timeout
        super().__init__(host, port, timeout)

    def open(self, host: str = "", port: int = imaplib.IMAP4_PORT, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.sock = create_connection(host, port, self._proxy, timeout or self._connect_timeout)
        self.file = self.sock.makefile("rb")


class ProxyIMAP4_SSL(imaplib.IMAP4_SSL):
    def __init__(self, host: str, port: int, *, proxy: ProxyConfig, ssl_context: ssl.SSLContext, timeout: float) -> None:
        self._proxy = proxy
        self._connect_timeout = timeout
        self._ssl_context = ssl_context
        super().__init__(host, port, ssl_context=ssl_context, timeout=timeout)

    def open(self, host: str = "", port: int = imaplib.IMAP4_SSL_PORT, timeout: float | None = None) -> None:
        raw_sock = create_connection(host, port, self._proxy, timeout or self._connect_timeout)
        self.host = host
        self.port = port
        self.sock = self._ssl_context.wrap_socket(raw_sock, server_hostname=host)
        self.sock.settimeout(timeout or self._connect_timeout)
        self.file = self.sock.makefile("rb")


class ProxySMTP(smtplib.SMTP):
    def __init__(
        self,
        host: str = "",
        port: int = 0,
        local_hostname: str | None = None,
        timeout: float = CONNECT_TIMEOUT,
        source_address: tuple[str, int] | None = None,
        *,
        proxy: ProxyConfig,
    ) -> None:
        self._proxy = proxy
        super().__init__(host=host, port=port, local_hostname=local_hostname, timeout=timeout, source_address=source_address)

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        return create_connection(host, port, self._proxy, timeout)


class ProxySMTP_SSL(smtplib.SMTP_SSL):
    def __init__(
        self,
        host: str = "",
        port: int = 0,
        local_hostname: str | None = None,
        timeout: float = CONNECT_TIMEOUT,
        source_address: tuple[str, int] | None = None,
        context: ssl.SSLContext | None = None,
        *,
        proxy: ProxyConfig,
    ) -> None:
        self._proxy = proxy
        super().__init__(
            host=host,
            port=port,
            local_hostname=local_hostname,
            timeout=timeout,
            source_address=source_address,
            context=context,
        )

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        raw_sock = create_connection(host, port, self._proxy, timeout)
        wrapped = self.context.wrap_socket(raw_sock, server_hostname=host)
        wrapped.settimeout(timeout)
        return wrapped


def create_imap_client(account: AccountConfig) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
    context = ssl.create_default_context()
    if account.imap.uses_ssl:
        if account.proxy:
            return ProxyIMAP4_SSL(
                account.imap.host,
                account.imap.port,
                proxy=account.proxy,
                ssl_context=context,
                timeout=CONNECT_TIMEOUT,
            )
        return imaplib.IMAP4_SSL(account.imap.host, account.imap.port, ssl_context=context, timeout=CONNECT_TIMEOUT)

    if account.proxy:
        client: imaplib.IMAP4 | imaplib.IMAP4_SSL = ProxyIMAP4(
            account.imap.host,
            account.imap.port,
            proxy=account.proxy,
            timeout=CONNECT_TIMEOUT,
        )
    else:
        client = imaplib.IMAP4(account.imap.host, account.imap.port, CONNECT_TIMEOUT)
    if account.imap.uses_starttls:
        client.starttls(ssl_context=context)
    return client


class MailClient:
    def __init__(self, account: AccountConfig) -> None:
        self.account = account
        self.imap: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> "MailClient":
        self.imap = create_imap_client(self.account)
        self.imap.login(self.account.login_user, self.account.auth.secret or "")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.imap is None:
            return
        try:
            self.imap.logout()
        except Exception:
            pass

    def _require_imap(self) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
        if self.imap is None:
            raise RuntimeError("IMAP is not connected")
        return self.imap

    def select_folder(self, folder: str) -> None:
        imap = self._require_imap()
        mailbox = folder
        if " " in mailbox and not (mailbox.startswith('"') and mailbox.endswith('"')):
            mailbox = f'"{mailbox}"'
        status, _ = imap.select(mailbox, readonly=True)
        if status != "OK":
            raise RuntimeError(f"failed to open mailbox folder: {folder}")

    def search_all_uids(self) -> list[bytes]:
        imap = self._require_imap()
        status, data = imap.uid("search", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []
        return data[0].split()

    def fetch_headers(self, uid: bytes) -> dict[str, str]:
        imap = self._require_imap()
        status, data = imap.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
        if status != "OK" or not data or not data[0]:
            raise RuntimeError(f"failed to read message headers: {uid.decode()}")
        msg = message_from_bytes(data[0][1])
        return {
            "uid": uid.decode(),
            "subject": decode_mime_header(msg.get("Subject")),
            "from": decode_mime_header(msg.get("From")),
            "date": decode_mime_header(msg.get("Date")),
        }

    def fetch_message(self, uid: bytes) -> Message:
        imap = self._require_imap()
        status, data = imap.uid("fetch", uid, "(RFC822)")
        if status != "OK" or not data or not data[0]:
            raise RuntimeError(f"failed to read message body: {uid.decode()}")
        return message_from_bytes(data[0][1])


def archive_root() -> Path:
    return Path.home() / "Documents" / "CodexMail" / "attachments"


def build_download_dir(account: AccountConfig, uid: str, mode: str) -> Path:
    if mode == "temp":
        return Path(tempfile.mkdtemp(prefix=TEMP_DOWNLOAD_PREFIX))
    stamp = date.today().isoformat()
    root = archive_root().resolve()
    account_dir = safe_filename(account.name, "account")
    uid_dir = safe_filename(uid, "message")
    target = (root / account_dir / stamp / uid_dir).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise EmailOpsError("archive path escaped the attachment root", code="invalid_request") from exc
    return target


def list_message_attachments(msg: Message) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for index, part in enumerate(msg.walk(), start=1):
        filename = part.get_filename()
        if not filename:
            continue
        decoded = decode_mime_header(filename) or f"attachment-{index}"
        payload = part.get_payload(decode=True)
        attachments.append(
            {
                "filename": safe_filename(decoded, f"attachment-{index}"),
                "original_filename": decoded,
                "content_type": part.get_content_type(),
                "size": len(payload) if payload is not None else 0,
            }
        )
    return attachments


def build_message_detail(uid: str, msg: Message) -> dict[str, Any]:
    return {
        "uid": uid,
        "date": decode_mime_header(msg.get("Date")),
        "from": decode_mime_header(msg.get("From")),
        "to": decode_mime_header(msg.get("To")),
        "cc": decode_mime_header(msg.get("Cc")),
        "subject": decode_mime_header(msg.get("Subject")),
        "body_text": get_body_text(msg),
        "attachments": list_message_attachments(msg),
    }


def normalize_recipients(raw: str | list[str]) -> list[str]:
    if isinstance(raw, str):
        parts = re.split(r"[,;\n]", raw)
    else:
        parts = raw
    recipients = [str(item).strip() for item in parts if str(item).strip()]
    if not recipients:
        raise RuntimeError("at least one recipient is required")
    return recipients


def send_email(account: AccountConfig, *, to: str | list[str], subject: str, body: str, html_body: str | None = None, attachments: list[str] | None = None) -> dict[str, Any]:
    recipients = normalize_recipients(to)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{account.display_name} <{account.email}>"
    msg["To"] = ", ".join(recipients)
    msg.set_content(body, charset="utf-8")

    if html_body:
        msg.add_alternative(html_body, subtype="html", charset="utf-8")

    attached_files: list[str] = []
    for attachment in attachments or []:
        path = _validate_send_attachment(attachment)
        data = path.read_bytes()
        msg.add_attachment(
            data,
            maintype="application",
            subtype="octet-stream",
            filename=path.name,
        )
        attached_files.append(str(path))

    context = ssl.create_default_context()
    if account.smtp.uses_ssl:
        server_cls = ProxySMTP_SSL if account.proxy else smtplib.SMTP_SSL
        kwargs: dict[str, Any] = {"context": context, "timeout": CONNECT_TIMEOUT}
        if account.proxy:
            kwargs["proxy"] = account.proxy
        with server_cls(account.smtp.host, account.smtp.port, **kwargs) as server:
            server.login(account.login_user, account.auth.secret or "")
            server.send_message(msg)
    else:
        server_cls = ProxySMTP if account.proxy else smtplib.SMTP
        kwargs = {"timeout": CONNECT_TIMEOUT}
        if account.proxy:
            kwargs["proxy"] = account.proxy
        with server_cls(account.smtp.host, account.smtp.port, **kwargs) as server:
            server.ehlo()
            if account.smtp.uses_starttls:
                server.starttls(context=context)
                server.ehlo()
            server.login(account.login_user, account.auth.secret or "")
            server.send_message(msg)

    return {
        "account": account.name,
        "to": recipients,
        "subject": subject,
        "attachments": attached_files,
        "status": "sent",
    }


def test_imap_login(account: AccountConfig) -> None:
    client = create_imap_client(account)
    try:
        client.login(account.login_user, account.auth.secret or "")
    finally:
        try:
            client.logout()
        except Exception:
            pass


def test_smtp_login(account: AccountConfig) -> None:
    context = ssl.create_default_context()
    if account.smtp.uses_ssl:
        server_cls = ProxySMTP_SSL if account.proxy else smtplib.SMTP_SSL
        kwargs: dict[str, Any] = {"context": context, "timeout": CONNECT_TIMEOUT}
        if account.proxy:
            kwargs["proxy"] = account.proxy
        with server_cls(account.smtp.host, account.smtp.port, **kwargs) as server:
            server.login(account.login_user, account.auth.secret or "")
            return

    server_cls = ProxySMTP if account.proxy else smtplib.SMTP
    kwargs = {"timeout": CONNECT_TIMEOUT}
    if account.proxy:
        kwargs["proxy"] = account.proxy
    with server_cls(account.smtp.host, account.smtp.port, **kwargs) as server:
        server.ehlo()
        if account.smtp.uses_starttls:
            server.starttls(context=context)
            server.ehlo()
        server.login(account.login_user, account.auth.secret or "")


__all__ = [
    "CONNECT_TIMEOUT",
    "MailClient",
    "build_download_dir",
    "build_message_detail",
    "format_preview",
    "get_body_text",
    "save_attachments",
    "send_email",
    "test_imap_login",
    "test_smtp_login",
]
