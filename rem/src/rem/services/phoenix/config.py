"""Phoenix configuration for REM.

Loads connection settings from environment variables with sensible defaults.
"""

import os
from loguru import logger


class PhoenixConfig:
    """Phoenix connection configuration.

    Environment Variables:
    - PHOENIX_BASE_URL: Phoenix server URL (default: http://localhost:6006)
    - PHOENIX_API_KEY: API key for authentication (required for cluster Phoenix)

    Standard Setup:
    --------------
    1. Port-forward Phoenix service (if on Kubernetes):
       kubectl port-forward -n observability svc/phoenix-svc 6006:6006

    2. Set API key in environment:
       export PHOENIX_API_KEY=<your-key>

    3. Phoenix will be accessible at http://localhost:6006

    Local Development:
    ------------------
    For local Phoenix instance without K8s:
        python -m phoenix.server.main serve
        # Phoenix at http://localhost:6006 (no API key needed)
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        """Initialize Phoenix configuration.

        Args:
            base_url: Phoenix server URL (overrides env var)
            api_key: API key for authentication (overrides env var)
        """
        self.base_url = base_url or os.getenv(
            "PHOENIX_BASE_URL", "http://localhost:6006"
        )
        self.api_key = api_key or os.getenv("PHOENIX_API_KEY")

        logger.debug(f"Phoenix config: base_url={self.base_url}, api_key={'***' if self.api_key else 'None'}")

    @classmethod
    def from_settings(cls) -> "PhoenixConfig":
        """Load Phoenix configuration from REM settings.

        Returns:
            PhoenixConfig with values from settings

        Note: Currently loads from env vars. Could be extended to use
        rem.settings.Settings if Phoenix settings are added there.
        """
        return cls()
