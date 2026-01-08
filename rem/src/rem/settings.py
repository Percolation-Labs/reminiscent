"""
REM Settings and Configuration.

Pydantic settings with environment variable support:
- Nested settings with env_prefix for organization
- Environment variables use double underscore delimiter (ENV__NESTED__VAR)
- Sensitive defaults (auth disabled, OTEL disabled for local dev)
- Global settings singleton

Example .env file:
    # API Server
    API__HOST=0.0.0.0
    API__PORT=8000
    API__RELOAD=true
    API__LOG_LEVEL=info

    # LLM
    LLM__DEFAULT_MODEL=openai:gpt-4.1
    LLM__DEFAULT_TEMPERATURE=0.5
    LLM__MAX_RETRIES=10
    LLM__OPENAI_API_KEY=sk-...
    LLM__ANTHROPIC_API_KEY=sk-ant-...

    # Database (port 5051 for Docker Compose prebuilt, 5050 for local dev)
    POSTGRES__CONNECTION_STRING=postgresql://rem:rem@localhost:5051/rem
    POSTGRES__POOL_MIN_SIZE=5
    POSTGRES__POOL_MAX_SIZE=20
    POSTGRES__STATEMENT_TIMEOUT=30000

    # Auth (disabled by default)
    AUTH__ENABLED=false
    AUTH__OIDC_ISSUER_URL=https://accounts.google.com
    AUTH__OIDC_CLIENT_ID=your-client-id
    AUTH__SESSION_SECRET=your-secret-key

    # OpenTelemetry (disabled by default - enable via env var when collector available)
    # Standard OTLP collector ports: 4317 (gRPC), 4318 (HTTP)
    OTEL__ENABLED=false
    OTEL__SERVICE_NAME=rem-api
    OTEL__COLLECTOR_ENDPOINT=http://localhost:4317
    OTEL__PROTOCOL=grpc

    # Arize Phoenix (enabled by default - can be disabled via env var)
    PHOENIX__ENABLED=true
    PHOENIX__COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces
    PHOENIX__PROJECT_NAME=rem

    # S3 Storage
    S3__BUCKET_NAME=rem-storage
    S3__REGION=us-east-1
    S3__ENDPOINT_URL=http://localhost:9000  # For MinIO
    S3__ACCESS_KEY_ID=minioadmin
    S3__SECRET_ACCESS_KEY=minioadmin

    # Environment
    ENVIRONMENT=development
    TEAM=rem
"""

import os
import hashlib
from pydantic import Field, field_validator, ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict
from loguru import logger


class LLMSettings(BaseSettings):
    """
    LLM provider settings for Pydantic AI agents.

    Environment variables (accepts both prefixed and unprefixed):
        LLM__DEFAULT_MODEL or DEFAULT_MODEL - Default model (format: provider:model-id)
        LLM__DEFAULT_TEMPERATURE or DEFAULT_TEMPERATURE - Temperature for generation
        LLM__MAX_RETRIES or MAX_RETRIES - Max agent request retries
        LLM__EVALUATOR_MODEL or EVALUATOR_MODEL - Model for LLM-as-judge evaluation
        LLM__OPENAI_API_KEY or OPENAI_API_KEY - OpenAI API key
        LLM__ANTHROPIC_API_KEY or ANTHROPIC_API_KEY - Anthropic API key
        LLM__EMBEDDING_PROVIDER or EMBEDDING_PROVIDER - Default embedding provider (openai)
        LLM__EMBEDDING_MODEL or EMBEDDING_MODEL - Default embedding model name
        LLM__DEFAULT_STRUCTURED_OUTPUT - Default structured output mode (False = streaming text)
    """

    model_config = SettingsConfigDict(
        env_prefix="LLM__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    default_model: str = Field(
        default="openai:gpt-4.1",
        description="Default LLM model (format: provider:model-id)",
    )

    default_temperature: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Default temperature (0.0-0.3: analytical, 0.7-1.0: creative)",
    )

    max_retries: int = Field(
        default=10,
        description="Maximum agent request retries (prevents infinite loops from tool errors)",
    )

    default_max_iterations: int = Field(
        default=20,
        description="Default max iterations for agentic calls (limits total LLM requests per agent.run())",
    )

    evaluator_model: str = Field(
        default="gpt-4.1",
        description="Model for LLM-as-judge evaluators (separate from generation model)",
    )

    query_agent_model: str = Field(
        default="cerebras:qwen-3-32b",
        description="Model for REM Query Agent (natural language to REM query). Cerebras Qwen 3-32B provides ultra-fast inference (1.2s reasoning, 2400 tok/s). Alternative: cerebras:llama-3.3-70b, gpt-4o-mini, or claude-sonnet-4.5",
    )

    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API key for GPT models (reads from LLM__OPENAI_API_KEY or OPENAI_API_KEY)",
    )

    anthropic_api_key: str | None = Field(
        default=None,
        description="Anthropic API key for Claude models (reads from LLM__ANTHROPIC_API_KEY or ANTHROPIC_API_KEY)",
    )

    embedding_provider: str = Field(
        default="openai",
        description="Default embedding provider (currently only openai supported)",
    )

    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Default embedding model (provider-specific model name)",
    )

    default_structured_output: bool = Field(
        default=False,
        description="Default structured output mode for agents. False = streaming text (easier), True = JSON schema validation",
    )

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def validate_openai_api_key(cls, v):
        """Fallback to OPENAI_API_KEY if LLM__OPENAI_API_KEY not set (LLM__ takes precedence)."""
        if v is None:
            return os.getenv("OPENAI_API_KEY")
        return v

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def validate_anthropic_api_key(cls, v):
        """Fallback to ANTHROPIC_API_KEY if LLM__ANTHROPIC_API_KEY not set (LLM__ takes precedence)."""
        if v is None:
            return os.getenv("ANTHROPIC_API_KEY")
        return v


class MCPSettings(BaseSettings):
    """
    MCP server settings.

    MCP server is mounted at /api/v1/mcp with FastMCP.
    Can be accessed via:
    - HTTP transport (production): /api/v1/mcp
    - SSE transport (compatible with Claude Desktop)

    Environment variables:
        MCP_SERVER_{NAME} - Server URLs for MCP client connections
    """

    model_config = SettingsConfigDict(
        env_prefix="MCP__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @staticmethod
    def get_server_url(server_name: str) -> str | None:
        """
        Get MCP server URL from environment variable.

        Args:
            server_name: Server name (e.g., "test", "prod")

        Returns:
            Server URL or None if not configured

        Example:
            MCP_SERVER_TEST=http://localhost:8000/api/v1/mcp
        """
        import os

        env_key = f"MCP_SERVER_{server_name.upper()}"
        return os.getenv(env_key)


class OTELSettings(BaseSettings):
    """
    OpenTelemetry observability settings.

    Integrates with OpenTelemetry Collector for distributed tracing.
    Uses OTLP protocol to export to Arize Phoenix or other OTLP backends.

    Environment variables:
        OTEL__ENABLED - Enable instrumentation (default: false for local dev)
        OTEL__SERVICE_NAME - Service name for traces
        OTEL__COLLECTOR_ENDPOINT - OTLP endpoint (gRPC: 4317, HTTP: 4318)
        OTEL__PROTOCOL - Protocol to use (grpc or http)
        OTEL__EXPORT_TIMEOUT - Export timeout in milliseconds
    """

    model_config = SettingsConfigDict(
        env_prefix="OTEL__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=False,
        description="Enable OpenTelemetry instrumentation (disabled by default for local dev)",
    )

    service_name: str = Field(
        default="rem-api",
        description="Service name for traces",
    )

    collector_endpoint: str = Field(
        default="http://localhost:4318",
        description="OTLP collector endpoint (HTTP: 4318, gRPC: 4317)",
    )

    protocol: str = Field(
        default="http",
        description="OTLP protocol (http or grpc)",
    )

    export_timeout: int = Field(
        default=10000,
        description="Export timeout in milliseconds",
    )

    insecure: bool = Field(
        default=True,
        description="Use insecure (non-TLS) gRPC connection (default: True for local dev)",
    )


class PhoenixSettings(BaseSettings):
    """
    Arize Phoenix settings for LLM observability and evaluation.

    Phoenix provides:
    - OpenTelemetry-based LLM tracing (OpenInference conventions)
    - Experiment tracking
    - Evaluation feedback

    Environment variables:
        PHOENIX__ENABLED - Enable Phoenix integration
        PHOENIX__BASE_URL - Phoenix base URL (for client connections)
        PHOENIX__API_KEY - Phoenix API key (cloud instances)
        PHOENIX__COLLECTOR_ENDPOINT - Phoenix OTLP endpoint
        PHOENIX__PROJECT_NAME - Phoenix project name for trace organization
    """

    model_config = SettingsConfigDict(
        env_prefix="PHOENIX__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=True,
        description="Enable Phoenix integration (enabled by default)",
    )

    base_url: str = Field(
        default="http://localhost:6006",
        description="Phoenix base URL for client connections (default local Phoenix port)",
    )

    api_key: str | None = Field(
        default=None,
        description="Arize Phoenix API key for cloud instances",
    )

    collector_endpoint: str = Field(
        default="http://localhost:6006/v1/traces",
        description="Phoenix OTLP endpoint for traces (default local Phoenix port)",
    )

    project_name: str = Field(
        default="rem",
        description="Phoenix project name for trace organization",
    )


class GoogleOAuthSettings(BaseSettings):
    """
    Google OAuth settings.

    Environment variables:
        AUTH__GOOGLE__CLIENT_ID - Google OAuth client ID
        AUTH__GOOGLE__CLIENT_SECRET - Google OAuth client secret
        AUTH__GOOGLE__REDIRECT_URI - OAuth callback URL
        AUTH__GOOGLE__HOSTED_DOMAIN - Restrict to Google Workspace domain
    """

    model_config = SettingsConfigDict(
        env_prefix="AUTH__GOOGLE__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    client_id: str = Field(default="", description="Google OAuth client ID")
    client_secret: str = Field(default="", description="Google OAuth client secret")
    redirect_uri: str = Field(
        default="http://localhost:8000/api/auth/google/callback",
        description="OAuth redirect URI",
    )
    hosted_domain: str | None = Field(
        default=None, description="Restrict to Google Workspace domain (e.g., example.com)"
    )


class MicrosoftOAuthSettings(BaseSettings):
    """
    Microsoft Entra ID OAuth settings.

    Environment variables:
        AUTH__MICROSOFT__CLIENT_ID - Application (client) ID
        AUTH__MICROSOFT__CLIENT_SECRET - Client secret
        AUTH__MICROSOFT__REDIRECT_URI - OAuth callback URL
        AUTH__MICROSOFT__TENANT - Tenant ID or common/organizations/consumers
    """

    model_config = SettingsConfigDict(
        env_prefix="AUTH__MICROSOFT__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    client_id: str = Field(default="", description="Microsoft Application ID")
    client_secret: str = Field(default="", description="Microsoft client secret")
    redirect_uri: str = Field(
        default="http://localhost:8000/api/auth/microsoft/callback",
        description="OAuth redirect URI",
    )
    tenant: str = Field(
        default="common",
        description="Tenant ID or common/organizations/consumers",
    )


class AuthSettings(BaseSettings):
    """
    Authentication settings for OAuth 2.1 / OIDC.

    Supports multiple providers:
    - Google OAuth
    - Microsoft Entra ID
    - Custom OIDC provider

    Environment variables:
        AUTH__ENABLED - Enable authentication (default: true)
        AUTH__ALLOW_ANONYMOUS - Allow rate-limited anonymous access (default: true)
        AUTH__SESSION_SECRET - Secret for session cookie signing
        AUTH__GOOGLE__* - Google OAuth settings
        AUTH__MICROSOFT__* - Microsoft OAuth settings

    Access modes:
    - enabled=true, allow_anonymous=true: Auth available, anonymous gets rate-limited access
    - enabled=true, allow_anonymous=false: Auth required for all requests
    - enabled=false: No auth, all requests treated as default user (dev mode)
    """

    model_config = SettingsConfigDict(
        env_prefix="AUTH__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=True,
        description="Enable authentication (OAuth endpoints and middleware)",
    )

    allow_anonymous: bool = Field(
        default=True,
        description=(
            "Allow anonymous (unauthenticated) access with rate limits. "
            "When true, requests without auth get ANONYMOUS tier rate limits. "
            "When false, all requests require authentication."
        ),
    )

    mcp_requires_auth: bool = Field(
        default=True,
        description=(
            "Require authentication for MCP endpoints. "
            "MCP is a protected service and should always require login in production. "
            "Set to false only for local development/testing."
        ),
    )

    session_secret: str = Field(
        default="",
        description="Secret key for session cookie signing (generate with secrets.token_hex(32))",
    )

    # OAuth provider settings
    google: GoogleOAuthSettings = Field(default_factory=GoogleOAuthSettings)
    microsoft: MicrosoftOAuthSettings = Field(default_factory=MicrosoftOAuthSettings)

    # Pre-approved login codes (bypass email verification)
    # Format: comma-separated codes with prefix A=admin, B=normal user
    # Example: "A12345,A67890,B11111,B22222"
    preapproved_codes: str = Field(
        default="",
        description=(
            "Comma-separated list of pre-approved login codes. "
            "Prefix A = admin user, B = normal user. "
            "Example: 'A12345,A67890,B11111'. "
            "Users can login with these codes without email verification."
        ),
    )

    def check_preapproved_code(self, code: str) -> dict | None:
        """
        Check if a code is in the pre-approved list.

        Args:
            code: The code to check (including prefix)

        Returns:
            Dict with 'role' key if valid, None if not found.
            - A prefix -> role='admin'
            - B prefix -> role='user'
        """
        if not self.preapproved_codes:
            return None

        codes = [c.strip().upper() for c in self.preapproved_codes.split(",") if c.strip()]
        code_upper = code.strip().upper()

        if code_upper not in codes:
            return None

        # Parse prefix to determine role
        if code_upper.startswith("A"):
            return {"role": "admin", "code": code_upper}
        elif code_upper.startswith("B"):
            return {"role": "user", "code": code_upper}
        else:
            # Unknown prefix, treat as user
            return {"role": "user", "code": code_upper}

    @field_validator("session_secret", mode="before")
    @classmethod
    def generate_dev_secret(cls, v: str | None, info: ValidationInfo) -> str:
        # Only generate if not already set and not in production
        if not v and info.data.get("environment") != "production":
            # Deterministic secret for development
            seed_string = f"{info.data.get('team', 'rem')}-{info.data.get('environment', 'development')}-auth-secret-salt"
            logger.warning(
                "AUTH__SESSION_SECRET not set. Generating deterministic secret for non-production environment. "
                "DO NOT use in production."
            )
            return hashlib.sha256(seed_string.encode()).hexdigest()
        elif not v and info.data.get("environment") == "production":
            raise ValueError("AUTH__SESSION_SECRET must be set in production environment.")
        return v


class PostgresSettings(BaseSettings):
    """
    PostgreSQL settings for CloudNativePG.

    Connects to PostgreSQL 18 with pgvector extension running on CloudNativePG.

    Environment variables:
        POSTGRES__ENABLED - Enable database connection (default: true)
        POSTGRES__CONNECTION_STRING - PostgreSQL connection string
        POSTGRES__POOL_SIZE - Connection pool size
        POSTGRES__POOL_MIN_SIZE - Minimum pool size
        POSTGRES__POOL_MAX_SIZE - Maximum pool size
        POSTGRES__POOL_TIMEOUT - Connection timeout in seconds
        POSTGRES__STATEMENT_TIMEOUT - Statement timeout in milliseconds
    """

    model_config = SettingsConfigDict(
        env_prefix="POSTGRES__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=True,
        description="Enable database connection (set to false for testing without DB)",
    )

    connection_string: str = Field(
        default="postgresql://rem:rem@localhost:5051/rem",
        description="PostgreSQL connection string (default uses Docker Compose prebuilt port 5051)",
    )


    pool_size: int = Field(
        default=10,
        description="Connection pool size (deprecated, use pool_min_size/pool_max_size)",
    )

    pool_min_size: int = Field(
        default=5,
        description="Minimum number of connections in pool",
    )

    pool_max_size: int = Field(
        default=20,
        description="Maximum number of connections in pool",
    )

    pool_timeout: int = Field(
        default=30,
        description="Connection timeout in seconds",
    )

    statement_timeout: int = Field(
        default=30000,
        description="Statement timeout in milliseconds (30 seconds default)",
    )

    @property
    def user(self) -> str:
        from urllib.parse import urlparse
        return urlparse(self.connection_string).username or "postgres"

    @property
    def password(self) -> str | None:
        from urllib.parse import urlparse
        return urlparse(self.connection_string).password

    @property
    def database(self) -> str:
        from urllib.parse import urlparse
        return urlparse(self.connection_string).path.lstrip("/")

    @property
    def host(self) -> str:
        from urllib.parse import urlparse
        return urlparse(self.connection_string).hostname or "localhost"

    @property
    def port(self) -> int:
        from urllib.parse import urlparse
        return urlparse(self.connection_string).port or 5432


class MigrationSettings(BaseSettings):
    """
    Migration settings.

    Environment variables:
        MIGRATION__AUTO_UPGRADE - Automatically run migrations on startup
        MIGRATION__MODE - Migration safety mode (permissive, additive, strict)
        MIGRATION__ALLOW_DROP_COLUMNS - Allow DROP COLUMN operations
        MIGRATION__ALLOW_DROP_TABLES - Allow DROP TABLE operations
        MIGRATION__ALLOW_ALTER_COLUMNS - Allow ALTER COLUMN TYPE operations
        MIGRATION__ALLOW_RENAME_COLUMNS - Allow RENAME COLUMN operations
        MIGRATION__ALLOW_RENAME_TABLES - Allow RENAME TABLE operations
        MIGRATION__UNSAFE_ALTER_WARNING - Warn on unsafe ALTER operations
    """

    model_config = SettingsConfigDict(
        env_prefix="MIGRATION__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    auto_upgrade: bool = Field(
        default=True,
        description="Automatically run database migrations on startup",
    )
    
    mode: str = Field(
        default="permissive",
        description="Migration safety mode: permissive, additive, strict",
    )

    allow_drop_columns: bool = Field(
        default=False,
        description="Allow DROP COLUMN operations (unsafe)",
    )

    allow_drop_tables: bool = Field(
        default=False,
        description="Allow DROP TABLE operations (unsafe)",
    )

    allow_alter_columns: bool = Field(
        default=True,
        description="Allow ALTER COLUMN TYPE operations (can be unsafe)",
    )

    allow_rename_columns: bool = Field(
        default=True,
        description="Allow RENAME COLUMN operations (can be unsafe)",
    )

    allow_rename_tables: bool = Field(
        default=True,
        description="Allow RENAME TABLE operations (can be unsafe)",
    )

    unsafe_alter_warning: bool = Field(
        default=True,
        description="Emit warning on potentially unsafe ALTER operations",
    )


class StorageSettings(BaseSettings):
    """
    Storage provider settings.

    Controls which storage backend to use for file uploads and artifacts.

    Environment variables:
        STORAGE__PROVIDER - Storage provider (local or s3, default: local)
        STORAGE__BASE_PATH - Base path for local filesystem storage (default: ~/.rem/fs)
    """

    model_config = SettingsConfigDict(
        env_prefix="STORAGE__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: str = Field(
        default="local",
        description="Storage provider: 'local' for filesystem, 's3' for AWS S3",
    )

    base_path: str = Field(
        default="~/.rem/fs",
        description="Base path for local filesystem storage (only used when provider='local')",
    )


class S3Settings(BaseSettings):
    """
    S3 storage settings for file uploads and artifacts.

    Uses IRSA (IAM Roles for Service Accounts) for AWS permissions in EKS.
    For local development, can use MinIO or provide access keys.

    Bucket Naming Convention:
        - Default: rem-io-{environment} (e.g., rem-io-development, rem-io-staging, rem-io-production)
        - Matches Kubernetes manifest convention for consistency
        - Override with S3__BUCKET_NAME environment variable

    Path Convention:
        Uploads: s3://{bucket}/{version}/uploads/{user_id}/{yyyy}/{mm}/{dd}/{filename}
        Parsed:  s3://{bucket}/{version}/parsed/{user_id}/{yyyy}/{mm}/{dd}/{filename}/{resource}

    Environment variables:
        S3__BUCKET_NAME - S3 bucket name (default: rem-io-development)
        S3__VERSION - API version for paths (default: v1)
        S3__UPLOADS_PREFIX - Uploads directory prefix (default: uploads)
        S3__PARSED_PREFIX - Parsed content directory prefix (default: parsed)
        S3__REGION - AWS region
        S3__ENDPOINT_URL - Custom endpoint (for MinIO, LocalStack)
        S3__ACCESS_KEY_ID - AWS access key (not needed with IRSA)
        S3__SECRET_ACCESS_KEY - AWS secret key (not needed with IRSA)
        S3__USE_SSL - Use SSL for connections (default: true)
    """

    model_config = SettingsConfigDict(
        env_prefix="S3__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bucket_name: str = Field(
        default="rem-io-development",
        description="S3 bucket name (convention: rem-io-{environment})",
    )

    version: str = Field(
        default="v1",
        description="API version for S3 path structure",
    )

    uploads_prefix: str = Field(
        default="uploads",
        description="Prefix for uploaded files (e.g., 'uploads' -> bucket/v1/uploads/...)",
    )

    parsed_prefix: str = Field(
        default="parsed",
        description="Prefix for parsed content (e.g., 'parsed' -> bucket/v1/parsed/...)",
    )

    region: str = Field(
        default="us-east-1",
        description="AWS region",
    )

    endpoint_url: str | None = Field(
        default=None,
        description="Custom S3 endpoint (for MinIO, LocalStack)",
    )

    access_key_id: str | None = Field(
        default=None,
        description="AWS access key ID (not needed with IRSA in EKS)",
    )

    secret_access_key: str | None = Field(
        default=None,
        description="AWS secret access key (not needed with IRSA in EKS)",
    )

    use_ssl: bool = Field(
        default=True,
        description="Use SSL for S3 connections",
    )


class DataLakeSettings(BaseSettings):
    """
    Data lake settings for experiment and dataset storage.

    Data Lake Convention:
        The data lake provides a standardized structure for storing datasets,
        experiments, and calibration data in S3. Users bring their own bucket
        and the version is pinned by default to v0 in the path.

    S3 Path Structure:
        s3://{bucket}/{version}/datasets/
        ├── raw/                        # Raw source data + transformers
        │   └── {dataset_name}/         # e.g., cns_drugs, codes, care
        ├── tables/                     # Database table data (JSONL)
        │   ├── resources/              # → resources table
        │   │   ├── drugs/{category}/   # Psychotropic drugs
        │   │   ├── care/stages/        # Treatment stages
        │   │   └── crisis/             # Crisis resources
        │   └── codes/                  # → codes table
        │       ├── icd10/{category}/   # ICD-10 codes
        │       └── cpt/                # CPT codes
        └── calibration/                # Agent calibration
            ├── experiments/            # Experiment configs + results
            │   └── {agent}/{task}/     # e.g., siggy/risk-assessment
            └── datasets/               # Shared evaluation datasets

    Experiment Storage:
        - Local: experiments/{agent}/{task}/experiment.yaml
        - S3: s3://{bucket}/{version}/datasets/calibration/experiments/{agent}/{task}/

    Environment variables:
        DATA_LAKE__BUCKET_NAME - S3 bucket for data lake (required)
        DATA_LAKE__VERSION - Path version prefix (default: v0)
        DATA_LAKE__DATASETS_PREFIX - Datasets directory (default: datasets)
        DATA_LAKE__EXPERIMENTS_PREFIX - Experiments subdirectory (default: experiments)
    """

    model_config = SettingsConfigDict(
        env_prefix="DATA_LAKE__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bucket_name: str | None = Field(
        default=None,
        description="S3 bucket for data lake storage (user-provided)",
    )

    version: str = Field(
        default="v0",
        description="API version for data lake paths",
    )

    datasets_prefix: str = Field(
        default="datasets",
        description="Root directory for datasets in the bucket",
    )

    experiments_prefix: str = Field(
        default="experiments",
        description="Subdirectory within calibration for experiments",
    )

    def get_base_uri(self) -> str | None:
        """Get the base S3 URI for the data lake."""
        if not self.bucket_name:
            return None
        return f"s3://{self.bucket_name}/{self.version}/{self.datasets_prefix}"

    def get_experiment_uri(self, agent: str, task: str = "general") -> str | None:
        """Get the S3 URI for an experiment."""
        base = self.get_base_uri()
        if not base:
            return None
        return f"{base}/calibration/{self.experiments_prefix}/{agent}/{task}"

    def get_tables_uri(self, table: str = "resources") -> str | None:
        """Get the S3 URI for a table directory."""
        base = self.get_base_uri()
        if not base:
            return None
        return f"{base}/tables/{table}"


class ChunkingSettings(BaseSettings):
    """
    Document chunking settings for semantic text splitting.

    Uses semchunk for semantic-aware text chunking that respects document structure.
    Generous chunk sizes (couple paragraphs) with reasonable overlaps for context.

    Environment variables:
        CHUNKING__CHUNK_SIZE - Target chunk size in characters
        CHUNKING__OVERLAP - Overlap between chunks in characters
        CHUNKING__MIN_CHUNK_SIZE - Minimum chunk size (avoid tiny chunks)
        CHUNKING__MAX_CHUNK_SIZE - Maximum chunk size (hard limit)
    """

    model_config = SettingsConfigDict(
        env_prefix="CHUNKING__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    chunk_size: int = Field(
        default=1500,
        description="Target chunk size in characters (couple paragraphs, ~300-400 words)",
    )

    overlap: int = Field(
        default=200,
        description="Overlap between chunks in characters for context preservation",
    )

    min_chunk_size: int = Field(
        default=100,
        description="Minimum chunk size to avoid tiny fragments",
    )

    max_chunk_size: int = Field(
        default=2500,
        description="Maximum chunk size (hard limit, prevents oversized chunks)",
    )


class ContentSettings(BaseSettings):
    """
    Content provider settings for file processing.

    Defines supported file types for each provider type.
    Allows override of specific extensions via register_provider().

    Environment variables:
        CONTENT__SUPPORTED_TEXT_TYPES - Comma-separated text extensions
        CONTENT__SUPPORTED_DOC_TYPES - Comma-separated document extensions
        CONTENT__SUPPORTED_AUDIO_TYPES - Comma-separated audio extensions
        CONTENT__SUPPORTED_IMAGE_TYPES - Comma-separated image extensions
        CONTENT__IMAGE_VLLM_SAMPLE_RATE - Sampling rate for vision LLM analysis (0.0-1.0)
        CONTENT__IMAGE_VLLM_PROVIDER - Vision provider (anthropic, gemini, openai)
        CONTENT__IMAGE_VLLM_MODEL - Vision model name (provider default if not set)
        CONTENT__CLIP_PROVIDER - CLIP embedding provider (jina, self-hosted)
        CONTENT__CLIP_MODEL - CLIP model name (jina-clip-v1, jina-clip-v2)
        CONTENT__JINA_API_KEY - Jina AI API key for CLIP embeddings
    """

    model_config = SettingsConfigDict(
        env_prefix="CONTENT__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supported_text_types: list[str] = Field(
        default_factory=lambda: [
            # Plain text
            ".txt",
            ".md",
            ".markdown",
            # Data formats
            ".json",
            ".yaml",
            ".yml",
            ".csv",
            ".tsv",
            ".log",
            # Code files
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".java",
            ".c",
            ".cpp",
            ".h",
            ".rs",
            ".go",
            ".rb",
            ".php",
            ".sh",
            ".bash",
            ".sql",
            # Web files
            ".html",
            ".css",
            ".xml",
        ],
        description="File extensions handled by TextProvider (plain text, code, data files)",
    )

    supported_doc_types: list[str] = Field(
        default_factory=lambda: [
            # Documents
            ".pdf",
            ".docx",
            ".pptx",
            ".xlsx",
            # Images (OCR text extraction)
            ".png",
            ".jpg",
            ".jpeg",
        ],
        description="File extensions handled by DocProvider (Kreuzberg: PDFs, Office docs, images with OCR)",
    )

    supported_audio_types: list[str] = Field(
        default_factory=lambda: [
            ".wav",
            ".mp3",
            ".m4a",
            ".flac",
            ".ogg",
        ],
        description="File extensions handled by AudioProvider (Whisper API transcription)",
    )

    supported_image_types: list[str] = Field(
        default_factory=lambda: [
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
        ],
        description="File extensions handled by ImageProvider (vision LLM + CLIP embeddings)",
    )

    image_vllm_sample_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Sampling rate for vision LLM analysis (0.0 = never, 1.0 = always, 0.1 = 10% of images). Gold tier users always get vision analysis.",
    )

    image_vllm_provider: str = Field(
        default="anthropic",
        description="Vision LLM provider: anthropic, gemini, or openai",
    )

    image_vllm_model: str | None = Field(
        default=None,
        description="Vision model name (uses provider default if None)",
    )

    clip_provider: str = Field(
        default="jina",
        description="CLIP embedding provider (jina for API, self-hosted for future KEDA pods)",
    )

    clip_model: str = Field(
        default="jina-clip-v2",
        description="CLIP model for image embeddings (jina-clip-v1, jina-clip-v2, or custom)",
    )

    jina_api_key: str | None = Field(
        default=None,
        description="Jina AI API key for CLIP embeddings (https://jina.ai/embeddings/)",
    )


class SQSSettings(BaseSettings):
    """
    SQS queue settings for file processing.

    Uses IRSA (IAM Roles for Service Accounts) for AWS permissions in EKS.
    For local development, can use access keys.

    Environment variables:
        SQS__QUEUE_URL - SQS queue URL (from Pulumi output)
        SQS__REGION - AWS region
        SQS__MAX_MESSAGES - Max messages per receive (1-10)
        SQS__WAIT_TIME_SECONDS - Long polling wait time
        SQS__VISIBILITY_TIMEOUT - Message visibility timeout
    """

    model_config = SettingsConfigDict(
        env_prefix="SQS__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    queue_url: str = Field(
        default="",
        description="SQS queue URL for file processing events",
    )

    region: str = Field(
        default="us-east-1",
        description="AWS region",
    )

    max_messages: int = Field(
        default=10,
        ge=1,
        le=10,
        description="Maximum messages to receive per batch (1-10)",
    )

    wait_time_seconds: int = Field(
        default=20,
        ge=0,
        le=20,
        description="Long polling wait time in seconds (0-20, 20 recommended)",
    )

    visibility_timeout: int = Field(
        default=300,
        description="Visibility timeout in seconds (should match processing time)",
    )


class ChatSettings(BaseSettings):
    """
    Chat and session context settings.

    Environment variables:
        CHAT__AUTO_INJECT_USER_CONTEXT - Automatically inject user profile into every request (default: false)

    Design Philosophy:
    - Session history is ALWAYS loaded (required for multi-turn conversations)
    - Compression with REM LOOKUP hints keeps session history efficient
    - User context is on-demand by default (agents receive REM LOOKUP hints)
    - When auto_inject_user_context enabled, user profile is loaded and injected

    Session History (always loaded with compression):
    - Each chat request is a single message, so history MUST be recovered
    - Long assistant responses stored as separate Message entities
    - Compressed versions include REM LOOKUP hints: "... [REM LOOKUP session-{id}-msg-{index}] ..."
    - Agent can retrieve full content on-demand using REM LOOKUP
    - Prevents context window bloat while maintaining conversation continuity

    User Context (on-demand by default):
    - Agent system prompt includes: "User: {email}. To load user profile: Use REM LOOKUP \"{email}\""
    - Agent decides whether to load profile based on query
    - More efficient for queries that don't need personalization

    User Context (auto-inject when enabled):
    - Set CHAT__AUTO_INJECT_USER_CONTEXT=true
    - User profile automatically loaded and injected into system message
    - Simpler for basic chatbots that always need context
    """

    model_config = SettingsConfigDict(
        env_prefix="CHAT__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    auto_inject_user_context: bool = Field(
        default=False,
        description="Automatically inject user profile into every request (default: false, use REM LOOKUP hint instead)",
    )


class APISettings(BaseSettings):
    """
    API server settings.

    Environment variables:
        API__HOST - Host to bind to (0.0.0.0 for Docker, 127.0.0.1 for local)
        API__PORT - Port to listen on
        API__RELOAD - Enable auto-reload for development
        API__WORKERS - Number of worker processes (production)
        API__LOG_LEVEL - Logging level (debug, info, warning, error)
        API__API_KEY_ENABLED - Enable X-API-Key header authentication
        API__API_KEY - API key for X-API-Key authentication
    """

    model_config = SettingsConfigDict(
        env_prefix="API__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(
        default="0.0.0.0",
        description="Host to bind to (0.0.0.0 for Docker, 127.0.0.1 for local only)",
    )

    port: int = Field(
        default=8000,
        description="Port to listen on",
    )

    reload: bool = Field(
        default=True,
        description="Enable auto-reload for development (disable in production)",
    )

    workers: int = Field(
        default=1,
        description="Number of worker processes (use >1 in production)",
    )

    log_level: str = Field(
        default="info",
        description="Logging level (debug, info, warning, error, critical)",
    )

    api_key_enabled: bool = Field(
        default=False,
        description=(
            "Enable X-API-Key header authentication for API endpoints. "
            "When enabled, requests must include X-API-Key header with valid key. "
            "This provides simple API key auth independent of OAuth."
        ),
    )

    api_key: str | None = Field(
        default=None,
        description=(
            "API key for X-API-Key authentication. Required when api_key_enabled=true. "
            "Generate with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        ),
    )

    rate_limit_enabled: bool = Field(
        default=True,
        description=(
            "Enable rate limiting for API endpoints. "
            "Set to false to disable rate limiting entirely (useful for development)."
        ),
    )


class ModelsSettings(BaseSettings):
    """
    Custom model registration settings for downstream applications.

    Allows downstream apps to specify Python modules containing custom models
    that should be imported (and thus registered) before schema generation.

    This enables `rem db schema generate` to discover models registered with
    `@rem.register_model` in downstream applications.

    Environment variables:
        MODELS__IMPORT_MODULES - Semicolon-separated list of Python modules to import
                                 Example: "models;myapp.entities;myapp.custom_models"

    Example:
        # In downstream app's .env
        MODELS__IMPORT_MODULES=models

        # In downstream app's models/__init__.py
        import rem
        from rem.models.core import CoreModel

        @rem.register_model
        class MyCustomEntity(CoreModel):
            name: str

        # Then run schema generation
        rem db schema generate  # Includes MyCustomEntity
    """

    model_config = SettingsConfigDict(
        env_prefix="MODELS__",
        extra="ignore",
    )

    import_modules: str = Field(
        default="",
        description=(
            "Semicolon-separated list of Python modules to import for model registration. "
            "These modules are imported before schema generation to ensure custom models "
            "decorated with @rem.register_model are discovered. "
            "Example: 'models;myapp.entities'"
        ),
    )

    @property
    def module_list(self) -> list[str]:
        """
        Get modules as a list, filtering empty strings.

        Auto-detects ./models folder if it exists and is importable.
        """
        modules = []
        if self.import_modules:
            modules = [m.strip() for m in self.import_modules.split(";") if m.strip()]

        # Auto-detect ./models if it exists and is a Python package (convention over configuration)
        from pathlib import Path

        models_path = Path("./models")
        if models_path.exists() and models_path.is_dir():
            # Check if it's a Python package (has __init__.py)
            if (models_path / "__init__.py").exists():
                if "models" not in modules:
                    modules.insert(0, "models")

        return modules


class SchemaSettings(BaseSettings):
    """
    Schema search path settings for agent and evaluator schemas.

    Allows extending REM's schema search with custom directories.
    Custom paths are searched BEFORE built-in package schemas.

    Environment variables:
        SCHEMA__PATHS - Semicolon-separated list of directories to search
                        Example: "/app/schemas;/shared/agents;./local-schemas"

    Search Order:
    1. Exact path (if file exists)
    2. Custom paths from SCHEMA__PATHS (in order)
    3. Built-in package schemas (schemas/agents/, schemas/evaluators/, etc.)
    4. Database LOOKUP (if enabled)

    Example:
        # In .env or environment
        SCHEMA__PATHS=/app/custom-agents;/shared/evaluators

        # Then in code
        from rem.utils.schema_loader import load_agent_schema
        schema = load_agent_schema("my-custom-agent")  # Found in /app/custom-agents/
    """

    model_config = SettingsConfigDict(
        env_prefix="SCHEMA__",
        extra="ignore",
    )

    paths: str = Field(
        default="",
        description=(
            "Semicolon-separated list of directories to search for schemas. "
            "These paths are searched BEFORE built-in package schemas. "
            "Example: '/app/schemas;/shared/agents'"
        ),
    )

    @property
    def path_list(self) -> list[str]:
        """Get paths as a list, filtering empty strings."""
        if not self.paths:
            return []
        return [p.strip() for p in self.paths.split(";") if p.strip()]


class GitSettings(BaseSettings):
    """
    Git repository provider settings for versioned schema/experiment syncing.

    Enables syncing of agent schemas, evaluators, and experiments from Git repositories
    using either SSH or HTTPS authentication. Designed for cluster environments where
    secrets are provided via Kubernetes Secrets or similar mechanisms.

    **Use Cases**:
    - Sync agent schemas from versioned repos (repo/schemas/)
    - Sync experiments and evaluation datasets (repo/experiments/)
    - Clone specific tags/releases for reproducible evaluations
    - Support multi-tenancy with per-tenant repo configurations

    **Authentication Methods**:
    1. **SSH** (recommended for production):
       - Uses SSH keys from filesystem or Kubernetes Secrets
       - Path specified via GIT__SSH_KEY_PATH or mounted at /etc/git-secret/ssh
       - Known hosts file at /etc/git-secret/known_hosts

    2. **HTTPS with Personal Access Token** (PAT):
       - GitHub: 5,000 API requests/hour per authenticated user
       - GitLab: Similar rate limits
       - Store PAT in GIT__PERSONAL_ACCESS_TOKEN environment variable

    **Kubernetes Deployment Pattern** (git-sync sidecar):
    ```yaml
    # Secret creation (one-time setup)
    kubectl create secret generic git-creds \\
      --from-file=ssh=$HOME/.ssh/id_rsa \\
      --from-file=known_hosts=$HOME/.ssh/known_hosts

    # Pod spec with secret mounting
    volumes:
      - name: git-secret
        secret:
          secretName: git-creds
          defaultMode: 0400  # Read-only for owner
    containers:
      - name: rem-api
        volumeMounts:
          - name: git-secret
            mountPath: /etc/git-secret
            readOnly: true
        securityContext:
          fsGroup: 65533  # Make secrets readable by git user
    ```

    **Path Conventions**:
    - Agent schemas: {repo_root}/schemas/
    - Experiments: {repo_root}/experiments/
    - Evaluators: {repo_root}/schemas/evaluators/

    **Performance & Caching**:
    - Clones cached locally in {cache_dir}/{repo_hash}/
    - Supports shallow clones (--depth=1) for faster syncing
    - Periodic refresh via cron jobs or git-sync sidecar

    Environment variables:
        GIT__ENABLED - Enable Git provider (default: False)
        GIT__DEFAULT_REPO_URL - Default Git repository URL (ssh:// or https://)
        GIT__DEFAULT_BRANCH - Default branch to clone (default: main)
        GIT__SSH_KEY_PATH - Path to SSH private key (default: /etc/git-secret/ssh)
        GIT__KNOWN_HOSTS_PATH - Path to known_hosts file (default: /etc/git-secret/known_hosts)
        GIT__PERSONAL_ACCESS_TOKEN - GitHub/GitLab PAT for HTTPS auth
        GIT__CACHE_DIR - Local cache directory for cloned repos
        GIT__SHALLOW_CLONE - Use shallow clone (--depth=1) for faster sync
        GIT__VERIFY_SSL - Verify SSL certificates for HTTPS (default: True)

    **Security Best Practices**:
    - Store SSH keys in Kubernetes Secrets, never in environment variables
    - Use read-only SSH keys (deploy keys) with minimal permissions
    - Enable known_hosts verification to prevent MITM attacks
    - Rotate PATs regularly (90-day expiration recommended)
    - Use IRSA/Workload Identity for cloud-provider Git services
    """

    model_config = SettingsConfigDict(
        env_prefix="GIT__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=False,
        description="Enable Git provider for syncing schemas/experiments from Git repos",
    )

    default_repo_url: str | None = Field(
        default=None,
        description="Default Git repository URL (ssh://git@github.com/org/repo.git or https://github.com/org/repo.git)",
    )

    default_branch: str = Field(
        default="main",
        description="Default branch to clone/checkout (main, master, develop, etc.)",
    )

    ssh_key_path: str = Field(
        default="/etc/git-secret/ssh",
        description="Path to SSH private key (Kubernetes Secret mount point or local path)",
    )

    known_hosts_path: str = Field(
        default="/etc/git-secret/known_hosts",
        description="Path to known_hosts file for SSH host verification",
    )

    personal_access_token: str | None = Field(
        default=None,
        description="Personal Access Token (PAT) for HTTPS authentication (GitHub, GitLab, etc.)",
    )

    cache_dir: str = Field(
        default="/tmp/rem-git-cache",
        description="Local cache directory for cloned repositories",
    )

    shallow_clone: bool = Field(
        default=True,
        description="Use shallow clone (--depth=1) for faster syncing (recommended for large repos)",
    )

    verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates for HTTPS connections (disable for self-signed certs)",
    )

    sync_interval: int = Field(
        default=300,
        description="Sync interval in seconds for git-sync sidecar pattern (default: 5 minutes)",
    )


class DBListenerSettings(BaseSettings):
    """
    PostgreSQL LISTEN/NOTIFY database listener settings.

    The DB Listener is a lightweight worker that subscribes to PostgreSQL
    NOTIFY events and dispatches them to external systems (SQS, REST, custom).

    Architecture:
        - Single-replica deployment (to avoid duplicate processing)
        - Dedicated connection for LISTEN (not from connection pool)
        - Automatic reconnection with exponential backoff
        - Graceful shutdown on SIGTERM

    Use Cases:
        - Sync data changes to external systems (Phoenix, webhooks)
        - Trigger async jobs without polling
        - Event-driven architectures with PostgreSQL as event source

    Example PostgreSQL trigger:
        CREATE OR REPLACE FUNCTION notify_feedback_insert()
        RETURNS TRIGGER AS $$
        BEGIN
            PERFORM pg_notify('feedback_sync', json_build_object(
                'id', NEW.id,
                'table', 'feedbacks',
                'action', 'insert'
            )::text);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

    Environment variables:
        DB_LISTENER__ENABLED - Enable the listener worker (default: false)
        DB_LISTENER__CHANNELS - Comma-separated PostgreSQL channels to listen on
        DB_LISTENER__HANDLER_TYPE - Handler type: 'sqs', 'rest', or 'custom'
        DB_LISTENER__SQS_QUEUE_URL - SQS queue URL (for handler_type=sqs)
        DB_LISTENER__REST_ENDPOINT - REST endpoint URL (for handler_type=rest)
        DB_LISTENER__RECONNECT_DELAY - Initial reconnect delay in seconds
        DB_LISTENER__MAX_RECONNECT_DELAY - Maximum reconnect delay in seconds

    References:
        - PostgreSQL NOTIFY: https://www.postgresql.org/docs/current/sql-notify.html
        - Brandur's Notifier: https://brandur.org/notifier
    """

    model_config = SettingsConfigDict(
        env_prefix="DB_LISTENER__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=False,
        description="Enable the DB Listener worker (disabled by default)",
    )

    channels: str = Field(
        default="",
        description=(
            "Comma-separated list of PostgreSQL channels to LISTEN on. "
            "Example: 'feedback_sync,entity_update,user_events'"
        ),
    )

    handler_type: str = Field(
        default="rest",
        description=(
            "Handler type for dispatching notifications. Options: "
            "'sqs' (publish to SQS), 'rest' (POST to endpoint), 'custom' (Python handlers)"
        ),
    )

    sqs_queue_url: str = Field(
        default="",
        description="SQS queue URL for handler_type='sqs'",
    )

    rest_endpoint: str = Field(
        default="http://localhost:8000/api/v1/internal/events",
        description=(
            "REST endpoint URL for handler_type='rest'. "
            "Receives POST with {channel, payload, source} JSON body."
        ),
    )

    reconnect_delay: float = Field(
        default=1.0,
        description="Initial delay (seconds) between reconnection attempts",
    )

    max_reconnect_delay: float = Field(
        default=60.0,
        description="Maximum delay (seconds) between reconnection attempts (exponential backoff cap)",
    )

    @property
    def channel_list(self) -> list[str]:
        """Get channels as a list, filtering empty strings."""
        if not self.channels:
            return []
        return [c.strip() for c in self.channels.split(",") if c.strip()]


class EmailSettings(BaseSettings):
    """
    Email service settings for SMTP.

    Supports passwordless login via email codes and transactional emails.
    Uses Gmail SMTP with App Passwords by default.

    Generate app password at: https://myaccount.google.com/apppasswords

    Environment variables:
        EMAIL__ENABLED - Enable email service (default: false)
        EMAIL__SMTP_HOST - SMTP server host (default: smtp.gmail.com)
        EMAIL__SMTP_PORT - SMTP server port (default: 587 for TLS)
        EMAIL__SENDER_EMAIL - Sender email address
        EMAIL__SENDER_NAME - Sender display name
        EMAIL__APP_PASSWORD - Gmail app password (from secrets)
        EMAIL__USE_TLS - Use TLS encryption (default: true)
        EMAIL__LOGIN_CODE_EXPIRY_MINUTES - Login code expiry (default: 10)

    Branding environment variables (for email templates):
        EMAIL__APP_NAME - Application name in emails (default: REM)
        EMAIL__LOGO_URL - Logo URL for email templates (40x40 recommended)
        EMAIL__TAGLINE - Tagline shown in email footer
        EMAIL__WEBSITE_URL - Main website URL for email links
        EMAIL__PRIVACY_URL - Privacy policy URL for email footer
        EMAIL__TERMS_URL - Terms of service URL for email footer
    """

    model_config = SettingsConfigDict(
        env_prefix="EMAIL__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=False,
        description="Enable email service (requires app_password to be set)",
    )

    smtp_host: str = Field(
        default="smtp.gmail.com",
        description="SMTP server host",
    )

    smtp_port: int = Field(
        default=587,
        description="SMTP server port (587 for TLS, 465 for SSL)",
    )

    sender_email: str = Field(
        default="",
        description="Sender email address",
    )

    sender_name: str = Field(
        default="REM",
        description="Sender display name",
    )

    # Branding settings for email templates
    app_name: str = Field(
        default="REM",
        description="Application name shown in email templates",
    )

    logo_url: str | None = Field(
        default=None,
        description="Logo URL for email templates (40x40 recommended)",
    )

    tagline: str = Field(
        default="Your AI-powered platform",
        description="Tagline shown in email footer",
    )

    website_url: str = Field(
        default="https://rem.ai",
        description="Main website URL for email links",
    )

    privacy_url: str = Field(
        default="https://rem.ai/privacy",
        description="Privacy policy URL for email footer",
    )

    terms_url: str = Field(
        default="https://rem.ai/terms",
        description="Terms of service URL for email footer",
    )

    app_password: str | None = Field(
        default=None,
        description="Gmail app password for SMTP authentication",
    )

    use_tls: bool = Field(
        default=True,
        description="Use TLS encryption for SMTP",
    )

    login_code_expiry_minutes: int = Field(
        default=10,
        description="Login code expiry in minutes",
    )

    trusted_email_domains: str = Field(
        default="",
        description=(
            "Comma-separated list of trusted email domains for new user registration. "
            "Existing users can always login regardless of domain. "
            "New users must have an email from a trusted domain. "
            "Empty string means all domains are allowed. "
            "Example: 'siggymd.ai,example.com'"
        ),
    )

    @property
    def trusted_domain_list(self) -> list[str]:
        """Get trusted domains as a list, filtering empty strings."""
        if not self.trusted_email_domains:
            return []
        return [d.strip().lower() for d in self.trusted_email_domains.split(",") if d.strip()]

    def is_domain_trusted(self, email: str) -> bool:
        """Check if an email's domain is in the trusted list.

        Args:
            email: Email address to check

        Returns:
            True if domain is trusted (or if no trusted domains configured)
        """
        domains = self.trusted_domain_list
        if not domains:
            # No restrictions configured
            return True

        email_domain = email.lower().split("@")[-1].strip()
        return email_domain in domains

    @property
    def is_configured(self) -> bool:
        """Check if email service is properly configured."""
        return bool(self.sender_email and self.app_password)

    @property
    def template_kwargs(self) -> dict:
        """
        Get branding kwargs for email templates.

        Returns a dict that can be passed to template functions:
            login_code_template(..., **settings.email.template_kwargs)
        """
        kwargs = {
            "app_name": self.app_name,
            "tagline": self.tagline,
            "website_url": self.website_url,
            "privacy_url": self.privacy_url,
            "terms_url": self.terms_url,
        }
        if self.logo_url:
            kwargs["logo_url"] = self.logo_url
        return kwargs


class DebugSettings(BaseSettings):
    """
    Debug settings for development and troubleshooting.

    Environment variables:
        DEBUG__AUDIT_SESSION - Dump session history to /tmp/{session_id}.yaml
        DEBUG__AUDIT_DIR - Directory for session audit files (default: /tmp)
    """

    model_config = SettingsConfigDict(
        env_prefix="DEBUG__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    audit_session: bool = Field(
        default=False,
        description="When true, dump full session history to audit files for debugging",
    )

    audit_dir: str = Field(
        default="/tmp",
        description="Directory for session audit files",
    )


class TestSettings(BaseSettings):
    """
    Test environment settings.

    Environment variables:
        TEST__USER_EMAIL - Test user email (default: test@rem.ai)
        TEST__USER_ID - Test user UUID (auto-generated from email if not provided)

    The user_id is a deterministic UUID v5 generated from the email address.
    This ensures consistent IDs across test runs and allows tests to use both
    email and UUID interchangeably.
    """

    model_config = SettingsConfigDict(
        env_prefix="TEST__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    user_email: str = Field(
        default="test@rem.ai",
        description="Test user email address",
    )

    user_id: str | None = Field(
        default=None,
        description="Test user UUID (auto-generated from email if not provided)",
    )

    @property
    def effective_user_id(self) -> str:
        """
        Get the effective user ID (either explicit or generated from email).

        Returns a deterministic UUID v5 based on the email address if user_id
        is not explicitly set. This ensures consistent test data across runs.
        """
        if self.user_id:
            return self.user_id

        # Generate deterministic UUID v5 from email
        # Using DNS namespace as the base (standard practice for email-based UUIDs)
        import uuid
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, self.user_email))


class Settings(BaseSettings):
    """
    Global application settings.

    Aggregates all nested settings groups with environment variable support.
    Uses double underscore delimiter for nested variables (LLM__DEFAULT_MODEL).

    Environment variables:
        TEAM - Team/project name for observability
        ENVIRONMENT - Environment (development, staging, production)
        DOMAIN - Public domain for OAuth discovery
        ROOT_PATH - Root path for reverse proxy (e.g., /rem for ALB routing)
        TEST__USER_ID - Default user ID for integration tests
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app_name: str = Field(
        default="REM",
        description="Application/API name used in docs, titles, and user-facing text",
    )

    team: str = Field(
        default="rem",
        description="Team or project name for observability",
    )

    environment: str = Field(
        default="development",
        description="Environment (development, staging, production)",
    )

    domain: str | None = Field(
        default=None,
        description="Public domain for OAuth discovery (e.g., https://api.example.com)",
    )

    root_path: str = Field(
        default="",
        description="Root path for reverse proxy (e.g., /rem for ALB routing)",
    )

    # Nested settings groups
    api: APISettings = Field(default_factory=APISettings)
    chat: ChatSettings = Field(default_factory=ChatSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)
    models: ModelsSettings = Field(default_factory=ModelsSettings)
    otel: OTELSettings = Field(default_factory=OTELSettings)
    phoenix: PhoenixSettings = Field(default_factory=PhoenixSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    migration: MigrationSettings = Field(default_factory=MigrationSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    s3: S3Settings = Field(default_factory=S3Settings)
    data_lake: DataLakeSettings = Field(default_factory=DataLakeSettings)
    git: GitSettings = Field(default_factory=GitSettings)
    sqs: SQSSettings = Field(default_factory=SQSSettings)
    db_listener: DBListenerSettings = Field(default_factory=DBListenerSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    content: ContentSettings = Field(default_factory=ContentSettings)
    schema_search: SchemaSettings = Field(default_factory=SchemaSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    test: TestSettings = Field(default_factory=TestSettings)
    debug: DebugSettings = Field(default_factory=DebugSettings)


# Auto-load .env file from current directory if it exists
# This happens BEFORE config file loading, so .env takes precedence
from pathlib import Path
from dotenv import load_dotenv

_dotenv_path = Path(".env")
if _dotenv_path.exists():
    load_dotenv(_dotenv_path, override=False)  # Don't override existing env vars
    logger.debug(f"Loaded environment from {_dotenv_path.resolve()}")

# Load configuration from ~/.rem/config.yaml before initializing settings
# This allows user configuration to be merged with environment variables
# Set REM_SKIP_CONFIG=1 to disable (useful for development with .env)
if not os.getenv("REM_SKIP_CONFIG", "").lower() in ("true", "1", "yes"):
    try:
        from rem.config import load_config, merge_config_to_env

        _config = load_config()
        if _config:
            merge_config_to_env(_config)
    except ImportError:
        # config module not available (e.g., during initial setup)
        pass

# Global settings singleton
settings = Settings()

# Sync API keys to environment for pydantic-ai
# Pydantic AI providers check environment directly, so we need to ensure
# API keys from settings (LLM__*_API_KEY) are also available without prefix
if settings.llm.openai_api_key and not os.getenv("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = settings.llm.openai_api_key

if settings.llm.anthropic_api_key and not os.getenv("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = settings.llm.anthropic_api_key
