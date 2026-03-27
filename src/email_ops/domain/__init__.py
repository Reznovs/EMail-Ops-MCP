from .errors import EmailOpsError, MigrationRequiredError
from .models import (
    AccountConfig,
    AttachmentInfo,
    AuthConfig,
    IdentityConfig,
    MessageSummary,
    ProxyConfig,
    ServerConfig,
)
from .providers import (
    CONFIG_VERSION,
    DEFAULT_FOLDER,
    DEFAULT_LIMIT,
    DEFAULT_SCAN,
    EXAMPLE_CONFIG,
    KEYRING_SERVICE,
    PROVIDER_PRESETS,
    auth_secret_placeholder,
    is_placeholder_secret,
    provider_advice,
)

__all__ = [
    "AccountConfig",
    "AttachmentInfo",
    "AuthConfig",
    "CONFIG_VERSION",
    "DEFAULT_FOLDER",
    "DEFAULT_LIMIT",
    "DEFAULT_SCAN",
    "EXAMPLE_CONFIG",
    "EmailOpsError",
    "IdentityConfig",
    "KEYRING_SERVICE",
    "MessageSummary",
    "MigrationRequiredError",
    "PROVIDER_PRESETS",
    "ProxyConfig",
    "ServerConfig",
    "auth_secret_placeholder",
    "is_placeholder_secret",
    "provider_advice",
]
