# EMail-Ops-MCP

EMail-Ops-MCP is a packaged stdio MCP server for mailbox setup, config migration, inbox search, attachment download, and sending mail across Gmail, QQ, or custom IMAP/SMTP providers.

## Standard MCP Shape

The MCP server lives in `src/email_ops/interfaces/mcp_server.py`.

- Transport: `stdio`
- Server name: `email-ops`
- Installed entrypoint:
  ```bash
  email-ops-mcp
  ```
- Python module entrypoint:
  ```bash
  python3 -m email_ops
  ```
- Structured tools:
  - `migrate_config`
  - `setup_account`
  - `doctor_account`
  - `test_login`
  - `list_messages`
  - `search_messages`
  - `get_message`
  - `download_attachments`
  - `send_email`

Anything about how a specific client stores MCP config is client-specific, not part of the MCP protocol itself.

## Install

```bash
cd /root/EMail-Ops
python3 -m pip install -e .
```

Optional secure credential storage:

```bash
python3 -m pip install -e '.[secure-storage]'
```

Runtime requirements:

- `python3`
- Mail account config at `~/.config/codex-mail/accounts.json`, unless `CODEX_MAIL_ACCOUNTS` points elsewhere
- Config schema is `v2`; old `v1` files must be migrated first

Optional:

- `CODEX_MAIL_CONNECT_TIMEOUT` to override the default connect timeout

## Config Migration

This project now treats the versioned `v2` config as the only writable schema.

- If your existing `accounts.json` is old `v1`, run `migrate_config` first.
- Migration writes a sibling backup file: `accounts.json.v1.bak`.
- Other mailbox tools return a structured `migration_required` error until migration is complete.

Minimal `v2` example:

```json
{
  "version": 2,
  "accounts": {
    "work": {
      "provider": "gmail",
      "identity": {
        "email": "your.name@example.com",
        "login_user": "your.name@example.com",
        "display_name": "Your Name"
      },
      "auth": {
        "mode": "app_password",
        "storage": "config_file",
        "secret": "<app-password-or-auth-code>",
        "keyring_key": null
      },
      "servers": {
        "imap": {"host": "imap.gmail.com", "port": 993, "security": "ssl"},
        "smtp": {"host": "smtp.gmail.com", "port": 465, "security": "ssl"}
      },
      "proxy": null
    }
  }
}
```

## Generic Client Wiring

Any MCP host that supports stdio servers only needs the equivalent of:

- command: `email-ops-mcp`
- args: `[]`
- cwd: optional
- env: optional, only needed if you want to override `CODEX_MAIL_ACCOUNTS` or timeout settings

This shape is not an MCP protocol standard by itself. It is the common host-side information needed to launch a stdio MCP server.

## Minimal Validation

You can verify that the server is a working MCP server with a generic MCP client, not a product-specific integration.

Example Python check:

```python
import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    server = StdioServerParameters(
        command="email-ops-mcp",
        args=[],
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            print(init.serverInfo.name)
            print([tool.name for tool in tools.tools])


anyio.run(main)
```

Expected result:

- server name is `email-ops`
- 9 tools are returned

## Notes

MCP only tells a host what tools exist and how to call them.

If you want an AI agent to use those tools well and consistently, the host side still needs its own prompt, workflow rules, and send-mail safety policy. Those usage rules are outside the MCP protocol itself.
