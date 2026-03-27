from __future__ import annotations

from pathlib import Path
from typing import Any

from email_ops.domain import DEFAULT_FOLDER, DEFAULT_LIMIT, DEFAULT_SCAN, EmailOpsError
from email_ops.infrastructure.config_store import load_account
from email_ops.infrastructure.mail_transport import (
    MailClient,
    build_download_dir,
    build_message_detail,
    format_preview,
    get_body_text,
    save_attachments,
    send_email,
)


def list_messages_service(
    *,
    account_name: str,
    config_path: str | Path | None = None,
    folder: str = DEFAULT_FOLDER,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    account = load_account(account_name, config_path)
    messages: list[dict[str, Any]] = []
    with MailClient(account) as client:
        client.select_folder(folder)
        uids = client.search_all_uids()
        target = list(reversed(uids[-limit:]))
        for uid in target:
            header = client.fetch_headers(uid)
            messages.append(
                {
                    "uid": header["uid"],
                    "date": header["date"],
                    "from": header["from"],
                    "subject": header["subject"],
                }
            )
    return {"account": account.name, "folder": folder, "messages": messages}


def search_messages_service(
    *,
    account_name: str,
    query: str = "",
    config_path: str | Path | None = None,
    folder: str = DEFAULT_FOLDER,
    scan: int = DEFAULT_SCAN,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    account = load_account(account_name, config_path)
    keyword = query.lower()
    messages: list[dict[str, Any]] = []
    with MailClient(account) as client:
        client.select_folder(folder)
        uids = client.search_all_uids()
        scanned = list(reversed(uids[-scan:]))
        matched = 0
        for uid in scanned:
            header = client.fetch_headers(uid)
            haystack = " ".join([header["subject"], header["from"], header["date"]]).lower()
            if keyword and keyword not in haystack:
                msg = client.fetch_message(uid)
                body = get_body_text(msg).lower()
                if keyword not in body:
                    continue
                preview = format_preview(body)
            else:
                msg = client.fetch_message(uid)
                preview = format_preview(get_body_text(msg))
            messages.append(
                {
                    "uid": header["uid"],
                    "date": header["date"],
                    "from": header["from"],
                    "subject": header["subject"],
                    "preview": preview,
                }
            )
            matched += 1
            if matched >= limit:
                break
    return {
        "account": account.name,
        "folder": folder,
        "query": query,
        "messages": messages,
    }


def get_message_service(
    *,
    account_name: str,
    uid: str,
    config_path: str | Path | None = None,
    folder: str = DEFAULT_FOLDER,
) -> dict[str, Any]:
    account = load_account(account_name, config_path)
    with MailClient(account) as client:
        client.select_folder(folder)
        msg = client.fetch_message(uid.encode())
    return {"account": account.name, "folder": folder, "message": build_message_detail(uid, msg)}


def download_attachments_service(
    *,
    account_name: str,
    uid: str,
    mode: str = "temp",
    config_path: str | Path | None = None,
    folder: str = DEFAULT_FOLDER,
) -> dict[str, Any]:
    if mode not in {"temp", "archive"}:
        raise EmailOpsError("mode must be temp or archive", code="invalid_request")
    account = load_account(account_name, config_path)
    with MailClient(account) as client:
        client.select_folder(folder)
        msg = client.fetch_message(uid.encode())
        target_dir = build_download_dir(account, uid, mode)
        saved = save_attachments(msg, target_dir)
    return {
        "account": account.name,
        "uid": uid,
        "mode": mode,
        "target_dir": str(target_dir),
        "files": [str(item) for item in saved],
    }


def send_email_service(
    *,
    account_name: str,
    to: str | list[str],
    subject: str,
    body: str,
    config_path: str | Path | None = None,
    html_body: str | None = None,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    account = load_account(account_name, config_path)
    return send_email(account, to=to, subject=subject, body=body, html_body=html_body, attachments=attachments)


__all__ = [
    "download_attachments_service",
    "get_message_service",
    "list_messages_service",
    "search_messages_service",
    "send_email_service",
]
