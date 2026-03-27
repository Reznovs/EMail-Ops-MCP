#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import email_ops.interfaces.mcp_server as email_ops_mcp
from email_ops.application.account_service import doctor_config_service, migrate_config_service, setup_account_service
from email_ops.application.message_service import send_email_service
import email_ops.infrastructure.config_store as config_store
import email_ops.infrastructure.mail_transport as mail_transport


class DummyKeyring:
    store: dict[tuple[str, str], str] = {}

    @classmethod
    def set_password(cls, service: str, name: str, secret: str) -> None:
        cls.store[(service, name)] = secret

    @classmethod
    def get_password(cls, service: str, name: str) -> str | None:
        return cls.store.get((service, name))

    @classmethod
    def delete_password(cls, service: str, name: str) -> None:
        cls.store.pop((service, name), None)


class DummyContext:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def info(self, message: str, **extra) -> None:
        self.messages.append(("info", message))

    async def warning(self, message: str, **extra) -> None:
        self.messages.append(("warning", message))


class EmailOpsTests(unittest.TestCase):
    def setUp(self) -> None:
        DummyKeyring.store = {}

    def test_setup_account_writes_v2_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "accounts.json"
            with mock.patch("email_ops.application.account_service.store_secret_secure", return_value=False):
                result = setup_account_service(
                    account="work",
                    provider="gmail",
                    email="user@example.com",
                    config_path=config_path,
                    display_name="User",
                    auth_secret="real-secret",
                )

            written = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(result["config_version"], 2)
            self.assertEqual(written["version"], 2)
            self.assertIn("work", written["accounts"])
            self.assertEqual(written["accounts"]["work"]["identity"]["email"], "user@example.com")
            self.assertEqual(written["accounts"]["work"]["auth"]["storage"], "config_file")

    def test_keyring_backed_account_update_stays_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "accounts.json"
            with mock.patch.object(config_store, "KEYRING_AVAILABLE", True), mock.patch.object(config_store, "keyring", DummyKeyring):
                setup_account_service(
                    account="work",
                    provider="gmail",
                    email="user@example.com",
                    config_path=config_path,
                    auth_secret="real-secret",
                )
                result = setup_account_service(
                    account="work",
                    provider="gmail",
                    email="user@example.com",
                    config_path=config_path,
                    display_name="New Name",
                )
                doctor = doctor_config_service(config_path=config_path)

            written = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(result["secret_storage"], "keyring")
            self.assertEqual(doctor["doctor_status"], "ok")
            self.assertEqual(written["accounts"]["work"]["auth"]["storage"], "keyring")
            self.assertEqual(written["accounts"]["work"]["auth"]["secret"], None)

    def test_setup_account_preserves_existing_server_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "accounts.json"
            with mock.patch("email_ops.application.account_service.store_secret_secure", return_value=False):
                setup_account_service(
                    account="work",
                    provider="gmail",
                    email="user@example.com",
                    config_path=config_path,
                    auth_secret="secret1",
                    smtp_host="smtp.alt.example.com",
                )
                setup_account_service(
                    account="work",
                    provider="gmail",
                    email="user@example.com",
                    config_path=config_path,
                    display_name="Updated User",
                )

            written = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(written["accounts"]["work"]["servers"]["smtp"]["host"], "smtp.alt.example.com")

    def test_migrate_config_creates_backup_and_v2_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "accounts.json"
            config_path.write_text(
                json.dumps(
                    {
                        "accounts": [
                            {
                                "name": "work",
                                "provider": "gmail",
                                "email": "user@example.com",
                                "login_user": "user@example.com",
                                "display_name": "User",
                                "auth_mode": "app_password",
                                "auth_secret": "real-secret",
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            result = migrate_config_service(config_path=config_path)
            written = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(result["migration_status"], "migrated")
            self.assertTrue((config_path.parent / "accounts.json.v1.bak").exists())
            self.assertEqual(written["version"], 2)
            self.assertIn("work", written["accounts"])
            self.assertEqual(written["accounts"]["work"]["servers"]["imap"]["security"], "ssl")

    def test_doctor_reports_migration_required_for_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "accounts.json"
            config_path.write_text(json.dumps({"accounts": []}), encoding="utf-8")
            doctor = doctor_config_service(config_path=config_path)

            self.assertTrue(doctor["migration_required"])
            self.assertEqual(doctor["doctor_status"], "needs_attention")

    def test_mcp_tool_returns_structured_migration_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "accounts.json"
            config_path.write_text(json.dumps({"accounts": []}), encoding="utf-8")
            result = asyncio.run(
                email_ops_mcp.list_messages(account="work", ctx=DummyContext(), config_path=str(config_path))
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "migration_required")

    def test_mcp_tool_logs_tool_name_via_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "accounts.json"
            config_path.write_text(json.dumps({"version": 2, "accounts": {}}), encoding="utf-8")
            ctx = DummyContext()
            asyncio.run(email_ops_mcp.doctor_account(ctx=ctx, config_path=str(config_path)))

        self.assertIn(("info", "[email-ops] tool call: doctor_account status=start"), ctx.messages)
        self.assertIn(("info", "[email-ops] tool call: doctor_account status=ok"), ctx.messages)

    def test_mcp_tool_appends_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "accounts.json"
            log_path = Path(tmpdir) / "email-ops-mcp.log"
            config_path.write_text(json.dumps({"version": 2, "accounts": {}}), encoding="utf-8")
            with mock.patch.object(email_ops_mcp, "DEFAULT_TOOL_LOG", log_path):
                asyncio.run(email_ops_mcp.doctor_account(ctx=DummyContext(), config_path=str(config_path)))

            log_output = log_path.read_text(encoding="utf-8")

        self.assertIn("[email-ops] tool call: doctor_account status=start", log_output)
        self.assertIn("[email-ops] tool call: doctor_account status=ok", log_output)

    def test_send_email_service_uses_v2_account_and_shared_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "accounts.json"
            attachment_path = Path(tmpdir) / "note.txt"
            attachment_path.write_text("hello", encoding="utf-8")
            with mock.patch("email_ops.application.account_service.store_secret_secure", return_value=False):
                setup_account_service(
                    account="work",
                    provider="gmail",
                    email="user@example.com",
                    config_path=config_path,
                    display_name="User",
                    auth_secret="real-secret",
                )

            class FakeSMTP:
                sent_messages = []

                def __init__(self, host: str, port: int, **kwargs) -> None:
                    self.host = host
                    self.port = port
                    self.kwargs = kwargs

                def __enter__(self) -> "FakeSMTP":
                    return self

                def __exit__(self, exc_type, exc, tb) -> None:
                    return None

                def login(self, user: str, secret: str) -> None:
                    self.user = user
                    self.secret = secret

                def send_message(self, msg) -> None:
                    self.__class__.sent_messages.append(msg)

            with mock.patch.object(mail_transport.smtplib, "SMTP_SSL", FakeSMTP):
                result = send_email_service(
                    account_name="work",
                    to=["a@example.com", "b@example.com"],
                    subject="Status",
                    body="Body text",
                    config_path=config_path,
                    attachments=[str(attachment_path)],
                )

            self.assertEqual(result["status"], "sent")
            self.assertEqual(result["to"], ["a@example.com", "b@example.com"])
            self.assertEqual(len(FakeSMTP.sent_messages), 1)
            message = FakeSMTP.sent_messages[0]
            self.assertEqual(message["Subject"], "Status")
            self.assertEqual(message["To"], "a@example.com, b@example.com")
            self.assertEqual(len(list(message.iter_attachments())), 1)

    def test_search_messages_mcp_tool_delegates_to_service(self) -> None:
        expected = {"account": "work", "folder": "INBOX", "query": "hello", "messages": []}
        with mock.patch.object(email_ops_mcp, "search_messages_service", return_value=expected) as mocked:
            result = asyncio.run(
                email_ops_mcp.search_messages(
                    account="work",
                    query="hello",
                    ctx=DummyContext(),
                    config_path="/tmp/accounts.json",
                    folder="INBOX",
                    scan=50,
                    limit=5,
                )
            )

        self.assertEqual(result, expected)
        mocked.assert_called_once_with(
            account_name="work",
            query="hello",
            config_path="/tmp/accounts.json",
            folder="INBOX",
            scan=50,
            limit=5,
        )

    def test_mcp_server_name_is_stable(self) -> None:
        self.assertEqual(email_ops_mcp.server.name, "email-ops")


if __name__ == "__main__":
    unittest.main()
