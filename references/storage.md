# Attachment Storage

## Modes

- `temp`: download into a temporary directory for short-lived processing
- `archive`: download into a fixed cross-platform archive directory

## Archive Root

The archive root is:

- macOS: `~/Documents/CodexMail/attachments`
- Linux: `~/Documents/CodexMail/attachments`
- Windows: `%USERPROFILE%\\Documents\\CodexMail\\attachments`

The script creates dated subdirectories automatically:

```text
<archive-root>/<account>/<YYYY-MM-DD>/<uid>/
```

## Temp Handling

- Temp downloads use a system temp directory with a `codex-mail-` prefix.
- The script prints the actual temp path so the caller can process files and then clean them through normal local file-management workflow.

## Reporting

Always tell the user:

- whether the download was temp or archived
- the full directory path
- each saved filename

If there are no attachments, say so explicitly.
