# Email Client Skill

支持 Claude Code、OpenAI Codex 的邮件处理工具。可配置邮箱账号、读取邮件、下载附件、起草和发送邮件。

## 支持邮箱

| 类型 | 服务商 |
|------|--------|
| 预设 | Gmail, QQ |
| 自定义 | 任意 IMAP/SMTP |

## 快速开始

### 1. 安装

```bash
git clone https://github.com/Reznovs/EMail-Client-Skill.git ~/.codex/skills/user/email-client-skill
```

### 2. 配置账号

```bash
python3 scripts/mail_tools.py setup_account \
  --input-json '{
    "account": "默认账号",
    "provider": "qq",
    "email": "你的邮箱@qq.com",
    "auth_secret": "授权码"
  }'
```

配置保存至 `~/.config/codex-mail/accounts.json`

### 3. 使用

```bash
# 发送邮件
python3 scripts/mail_tools.py send_email \
  --input-json '{
    "account": "默认账号",
    "to": "收件人@qq.com",
    "subject": "主题",
    "body": "正文"
  }'

# 查看最新邮件
python3 scripts/mail_tools.py list_messages \
  --input-json '{"account": "默认账号", "limit": 10}'

# 搜索邮件
python3 scripts/mail_tools.py search_messages \
  --input-json '{"account": "默认账号", "query": "关键词"}'
```

## 全部命令

| 命令 | 用途 |
|------|------|
| `doctor_account` | 检查配置 |
| `test_login` | 测试登录 |
| `setup_account` | 配置账号 |
| `list_messages` | 列出邮件 |
| `search_messages` | 搜索邮件 |
| `get_message` | 读取邮件详情 |
| `download_attachments` | 下载附件 |
| `draft_email` | 生成邮件草稿 |
| `send_email` | 发送邮件 |

## AI 平台适配

已配置 Claude Code 和 OpenAI Codex 的适配文件，位于 `agents/` 目录。

## 目录说明

```
email-client-skill/
├── agents/           # AI 平台配置
├── references/       # 详细文档
├── scripts/          # 核心脚本
│   ├── mail_tools.py    # 机器接口
│   └── mail_client.py   # 人工接口
└── tests/            # 测试
```
