from __future__ import annotations


class EmailOpsError(RuntimeError):
    """项目统一错误基类。"""

    def __init__(self, message: str, *, code: str = "runtime_error", details: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details


class MigrationRequiredError(EmailOpsError):
    """配置文件仍是旧版本，必须先迁移。"""

    def __init__(self, config_path: str) -> None:
        super().__init__(
            f"config migration required before using mailbox operations: {config_path}",
            code="migration_required",
        )
