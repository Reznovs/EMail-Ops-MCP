# Provider Notes

## Config Location

Default account file:

```text
~/.config/codex-mail/accounts.json
```

Override with:

```bash
export CODEX_MAIL_ACCOUNTS=/custom/path/accounts.json
```

The active writable schema is `v2`. If an old `v1` file already exists at this path, run MCP `migrate_config` first. Migration creates a sibling backup file named `accounts.json.v1.bak`.

## First-Time Setup Checklist

Before the skill can read or send mail, the user usually needs all of the following:

- a mailbox provider, such as `gmail`, `qq`, or a custom host
- the email address
- the login username if it differs from the email address
- a display name for sent mail
- an app password or auth code
- proxy settings when the mailbox provider must be reached through a proxy

If any of these are missing, guide the user to finish setup before attempting mailbox actions.

Recommended setup sequence:

1. Run MCP `migrate_config` when the config file is still `v1`.
2. Run MCP `setup_account` to create or update the account entry.
3. Run MCP `doctor_account` to inspect the config.
4. Replace any placeholder secret by rerunning `setup_account` with a real `auth_secret`.
5. Run MCP `test_login` for that account.
6. Only then move on to `list_messages`, `search_messages`, `get_message`, or `send_email`.

## Account Schema

```json
{
  "version": 2,
  "accounts": {
    "work": {
      "provider": "gmail",
      "identity": {
        "email": "name@example.com",
        "login_user": "name@example.com",
        "display_name": "Your Name"
      },
      "auth": {
        "mode": "app_password",
        "storage": "config_file",
        "secret": "xxxx xxxx xxxx xxxx",
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

This minimal example is enough for the built-in `gmail` preset:

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

Optional provider overrides:

```json
{
  "servers": {
    "imap": {
      "host": "imap.example.com",
      "port": 993,
      "security": "ssl"
    },
    "smtp": {
      "host": "smtp.example.com",
      "port": 465,
      "security": "ssl"
    }
  }
}
```

## Recommended Presets

Current recommended presets for this repository:

- `gmail`
- `qq`

These are the presets the project is currently optimized and documented for.

## Proxy Guidance

- Gmail: add a proxy when direct access to Google mail servers is blocked or unreliable in the current network.
- QQ: use direct access by default. Only add a proxy if the user explicitly says QQ Mail also needs one.
- Supported proxy types in this skill:
  - `socks5`
  - `http_connect`

Proxy schema:

```json
{
  "proxy": {
    "type": "socks5",
    "host": "127.0.0.1",
    "port": 7890,
    "remote_dns": true
  }
}
```

## Built-In Presets

The repository contains these presets:

- `gmail`
  - IMAP: `imap.gmail.com:993`
  - SMTP: `smtp.gmail.com:465`
  - Preferred auth: `app_password`
- `qq`
  - IMAP: `imap.qq.com:993`
  - SMTP: `smtp.qq.com:465`
  - Preferred auth: `auth_code`

## Auth Guidance

- Gmail personal account: use app password when the account has 2-Step Verification enabled.
- Gmail Google Workspace account: do not assume app password will work. Modern OAuth-based sign-in is increasingly required.
- QQ: expect the user to enable IMAP/SMTP in mailbox settings and generate an auth code before using the skill.
- If a provider does not support an auth code or app password, switch to custom settings or a different auth flow outside this skill.

## Setup Examples

Create a Gmail account entry with a placeholder secret and a SOCKS5 proxy through MCP `setup_account`:

```json
{
  "account": "work",
  "provider": "gmail",
  "email": "your.name@example.com",
  "display_name": "Your Name",
  "proxy_type": "socks5",
  "proxy_host": "127.0.0.1",
  "proxy_port": 7890,
  "proxy_remote_dns": true
}
```

Create a QQ account entry with the auth code already provided. QQ usually does not need a proxy:

```json
{
  "account": "qq-mail",
  "provider": "qq",
  "email": "123456789@qq.com",
  "display_name": "Your Name",
  "auth_secret": "<real-auth-code>"
}
```

Create a custom account:

```json
{
  "account": "custom",
  "provider": "custom",
  "email": "name@example.com",
  "imap_host": "imap.example.com",
  "imap_port": 993,
  "smtp_host": "smtp.example.com",
  "smtp_port": 465,
  "auth_secret": "<real-secret>"
}
```
