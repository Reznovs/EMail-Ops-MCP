from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Literal

from mcp.server.fastmcp import Context, FastMCP

from email_ops.application.account_service import (
    doctor_config_service,
    migrate_config_service,
    setup_account_service,
    test_login_service,
)
from email_ops.application.message_service import (
    download_attachments_service,
    get_message_service,
    list_messages_service,
    search_messages_service,
    send_email_service,
)
from email_ops.domain import DEFAULT_FOLDER, DEFAULT_LIMIT, DEFAULT_SCAN, EmailOpsError
from email_ops.infrastructure.config_store import DEFAULT_CONFIG


server = FastMCP(
    name="email-ops",
    instructions=(
        "Structured EMail-Ops tools for account setup, config migration, mailbox inspection, "
        "attachment download, and sending mail across Gmail, QQ, or custom IMAP/SMTP providers."
    ),
)


DEFAULT_TOOL_LOG = Path(os.environ.get("EMAIL_OPS_MCP_LOG", "/tmp/email-ops-mcp.log"))


def _append_tool_log(message: str) -> None:
    try:
        DEFAULT_TOOL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DEFAULT_TOOL_LOG.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        pass


def _emit_stderr_tool_log(tool_name: str, status: str) -> str:
    message = f"[email-ops] tool call: {tool_name} status={status}"
    print(message, file=sys.__stderr__, flush=True)
    _append_tool_log(message)
    return message


async def _emit_tool_log(tool_name: str, status: str, ctx: Context) -> None:
    message = _emit_stderr_tool_log(tool_name, status)
    if status.startswith("error:"):
        await ctx.warning(message)
        return
    await ctx.info(message)


async def _run_tool(tool_name: str, handler: Callable[[], dict[str, Any]], ctx: Context) -> dict[str, Any]:
    await _emit_tool_log(tool_name, "start", ctx)
    try:
        result = handler()
        await _emit_tool_log(tool_name, "ok", ctx)
        return result
    except EmailOpsError as exc:
        await _emit_tool_log(tool_name, f"error:{exc.code}", ctx)
        result = {
            "status": "error",
            "error_code": exc.code,
            "message": exc.message,
        }
        if exc.details:
            result["details"] = exc.details
        if exc.code == "migration_required":
            result["next_step"] = "run migrate_config before using mailbox operations."
        return result
    except Exception as exc:
        await _emit_tool_log(tool_name, "error:unexpected_error", ctx)
        return {
            "status": "error",
            "error_code": "unexpected_error",
            "message": str(exc),
        }


@server.tool(name="setup_account", description="Create or update a mailbox account config using schema v2.", structured_output=True)
async def setup_account(
    account: str,
    provider: str,
    email: str,
    ctx: Context,
    config_path: str = str(DEFAULT_CONFIG),
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
    return await _run_tool(
        "setup_account",
        lambda: setup_account_service(
            account=account,
            provider=provider,
            email=email,
            config_path=config_path,
            login_user=login_user,
            display_name=display_name,
            auth_mode=auth_mode,
            auth_secret=auth_secret,
            imap_host=imap_host,
            imap_port=imap_port,
            imap_no_ssl=imap_no_ssl,
            imap_starttls=imap_starttls,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_no_ssl=smtp_no_ssl,
            smtp_starttls=smtp_starttls,
            proxy_type=proxy_type,
            proxy_host=proxy_host,
            proxy_port=proxy_port,
            proxy_username=proxy_username,
            proxy_password=proxy_password,
            proxy_remote_dns=proxy_remote_dns,
            proxy_local_dns=proxy_local_dns,
            no_proxy=no_proxy,
        ),
        ctx,
    )


@server.tool(name="migrate_config", description="Migrate an old v1 accounts.json file to schema v2.", structured_output=True)
async def migrate_config(ctx: Context, config_path: str = str(DEFAULT_CONFIG)) -> dict[str, Any]:
    return await _run_tool("migrate_config", lambda: migrate_config_service(config_path=config_path), ctx)


@server.tool(name="doctor_account", description="Inspect the v2 mail account config and report setup issues.", structured_output=True)
async def doctor_account(ctx: Context, config_path: str = str(DEFAULT_CONFIG)) -> dict[str, Any]:
    return await _run_tool("doctor_account", lambda: doctor_config_service(config_path=config_path), ctx)


@server.tool(name="test_login", description="Test IMAP and SMTP login for a configured account.", structured_output=True)
async def test_login(
    account: str,
    ctx: Context,
    config_path: str = str(DEFAULT_CONFIG),
    imap_only: bool = False,
    smtp_only: bool = False,
) -> dict[str, Any]:
    return await _run_tool(
        "test_login",
        lambda: test_login_service(
            account_name=account,
            config_path=config_path,
            imap_only=imap_only,
            smtp_only=smtp_only,
        ),
        ctx,
    )


@server.tool(name="list_messages", description="List recent messages from a mailbox folder.", structured_output=True)
async def list_messages(
    account: str,
    ctx: Context,
    config_path: str = str(DEFAULT_CONFIG),
    folder: str = DEFAULT_FOLDER,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    return await _run_tool(
        "list_messages",
        lambda: list_messages_service(
            account_name=account,
            config_path=config_path,
            folder=folder,
            limit=limit,
        ),
        ctx,
    )


@server.tool(name="search_messages", description="Search recent messages by query across headers and body.", structured_output=True)
async def search_messages(
    account: str,
    query: str,
    ctx: Context,
    config_path: str = str(DEFAULT_CONFIG),
    folder: str = DEFAULT_FOLDER,
    scan: int = DEFAULT_SCAN,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    return await _run_tool(
        "search_messages",
        lambda: search_messages_service(
            account_name=account,
            query=query,
            config_path=config_path,
            folder=folder,
            scan=scan,
            limit=limit,
        ),
        ctx,
    )


@server.tool(name="get_message", description="Get a message body and metadata by UID.", structured_output=True)
async def get_message(
    account: str,
    uid: str,
    ctx: Context,
    config_path: str = str(DEFAULT_CONFIG),
    folder: str = DEFAULT_FOLDER,
) -> dict[str, Any]:
    return await _run_tool(
        "get_message",
        lambda: get_message_service(
            account_name=account,
            uid=uid,
            config_path=config_path,
            folder=folder,
        ),
        ctx,
    )


@server.tool(name="download_attachments", description="Download attachments from a message by UID.", structured_output=True)
async def download_attachments(
    account: str,
    uid: str,
    ctx: Context,
    mode: Literal["temp", "archive"] = "temp",
    config_path: str = str(DEFAULT_CONFIG),
    folder: str = DEFAULT_FOLDER,
) -> dict[str, Any]:
    return await _run_tool(
        "download_attachments",
        lambda: download_attachments_service(
            account_name=account,
            uid=uid,
            mode=mode,
            config_path=config_path,
            folder=folder,
        ),
        ctx,
    )


@server.tool(name="send_email", description="Send an email with optional HTML and file attachments.", structured_output=True)
async def send_email(
    account: str,
    to: list[str],
    subject: str,
    body: str,
    ctx: Context,
    config_path: str = str(DEFAULT_CONFIG),
    html_body: str | None = None,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    return await _run_tool(
        "send_email",
        lambda: send_email_service(
            account_name=account,
            to=to,
            subject=subject,
            body=body,
            config_path=config_path,
            html_body=html_body,
            attachments=attachments,
        ),
        ctx,
    )


def main() -> None:
    server.run(transport="stdio")
