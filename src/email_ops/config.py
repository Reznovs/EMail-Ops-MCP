"""Minimal config-facing exports for EMail-Ops."""

from email_ops.domain import (
    CONFIG_VERSION,
    DEFAULT_FOLDER,
    DEFAULT_LIMIT,
    DEFAULT_SCAN,
    EXAMPLE_CONFIG,
    KEYRING_SERVICE,
    PROVIDER_PRESETS,
)
from email_ops.infrastructure.config_store import DEFAULT_CONFIG, render_example_config, resolve_config_path

__all__ = [
    "CONFIG_VERSION",
    "DEFAULT_CONFIG",
    "DEFAULT_FOLDER",
    "DEFAULT_LIMIT",
    "DEFAULT_SCAN",
    "EXAMPLE_CONFIG",
    "KEYRING_SERVICE",
    "PROVIDER_PRESETS",
    "render_example_config",
    "resolve_config_path",
]
