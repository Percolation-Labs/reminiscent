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

    Deployment Patterns:
    --------------------

    **Production (Cluster Phoenix)** - RECOMMENDED:
    REM typically runs on Kubernetes alongside Phoenix in the observability namespace.
    Experiments run directly on the cluster where Phoenix is deployed:

        # 1. Deploy experiment as K8s Job or run from rem-api pod
        kubectl exec -it deployment/rem-api -- rem experiments run my-experiment

        # 2. Phoenix accessible via service DNS
        export PHOENIX_BASE_URL=http://phoenix-svc.observability.svc.cluster.local:6006
        export PHOENIX_API_KEY=<your-key>

    **Development (Port-Forward)** - For local testing:
    Port-forward Phoenix from cluster to local machine:

        # 1. Port-forward Phoenix service
        kubectl port-forward -n observability svc/phoenix-svc 6006:6006

        # 2. Set API key
        export PHOENIX_API_KEY=<your-key>

        # 3. Run experiments locally
        rem experiments run my-experiment
        # Connects to localhost:6006 → cluster Phoenix

    **Local Development (Local Phoenix)** - For offline work:
    Run Phoenix locally without cluster connection:

        # 1. Start local Phoenix
        python -m phoenix.server.main serve

        # 2. Run experiments (no API key needed)
        rem experiments run my-experiment
        # Connects to localhost:6006 → local Phoenix

    Override Defaults:
    ------------------
    Commands respect PHOENIX_BASE_URL and PHOENIX_API_KEY environment variables.
    Default is localhost:6006 for local development compatibility.
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
