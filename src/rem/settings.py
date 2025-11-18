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
    LLM__DEFAULT_MODEL=anthropic:claude-sonnet-4-5-20250929
    LLM__DEFAULT_TEMPERATURE=0.5
    LLM__MAX_RETRIES=10
    LLM__OPENAI_API_KEY=sk-...
    LLM__ANTHROPIC_API_KEY=sk-ant-...

    # Database (port 5050 for Docker Compose)
    POSTGRES__CONNECTION_STRING=postgresql://rem:rem@localhost:5050/rem
    POSTGRES__POOL_MIN_SIZE=5
    POSTGRES__POOL_MAX_SIZE=20
    POSTGRES__STATEMENT_TIMEOUT=30000

    # Auth (disabled by default)
    AUTH__ENABLED=false
    AUTH__OIDC_ISSUER_URL=https://accounts.google.com
    AUTH__OIDC_CLIENT_ID=your-client-id
    AUTH__SESSION_SECRET=your-secret-key

    # OpenTelemetry (disabled by default)
    OTEL__ENABLED=false
    OTEL__SERVICE_NAME=rem-api
    OTEL__COLLECTOR_ENDPOINT=http://localhost:4318
    OTEL__PROTOCOL=http

    # Arize Phoenix (disabled by default)
    PHOENIX__ENABLED=false
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

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    """
    LLM provider settings for Pydantic AI agents.

    Environment variables:
        LLM__DEFAULT_MODEL - Default model (format: provider:model-id)
        LLM__DEFAULT_TEMPERATURE - Temperature for generation
        LLM__MAX_RETRIES - Max agent request retries
        LLM__EVALUATOR_MODEL - Model for LLM-as-judge evaluation
        LLM__OPENAI_API_KEY - OpenAI API key
        LLM__ANTHROPIC_API_KEY - Anthropic API key
    """

    model_config = SettingsConfigDict(
        env_prefix="LLM__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    default_model: str = Field(
        default="anthropic:claude-sonnet-4-5-20250929",
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

    evaluator_model: str = Field(
        default="gpt-4.1",
        description="Model for LLM-as-judge evaluators (separate from generation model)",
    )

    query_agent_model: str | None = Field(
        default=None,
        description="Model for REM Query Agent (natural language to REM query). If None, uses default_model. Recommend fast model like gpt-4o-mini or claude-sonnet-4.5",
    )

    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API key for GPT models",
    )

    anthropic_api_key: str | None = Field(
        default=None,
        description="Anthropic API key for Claude models",
    )


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


class PhoenixSettings(BaseSettings):
    """
    Arize Phoenix settings for LLM observability and evaluation.

    Phoenix provides:
    - OpenTelemetry-based LLM tracing (OpenInference conventions)
    - Experiment tracking
    - Evaluation feedback

    Environment variables:
        PHOENIX__ENABLED - Enable Phoenix integration
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
        default=False,
        description="Enable Phoenix integration (disabled by default for local dev)",
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


class AuthSettings(BaseSettings):
    """
    Authentication settings for OAuth/OIDC.

    Supports multiple providers:
    - Google OAuth
    - Microsoft Entra ID
    - Custom OAuth provider

    FastMCP has built-in auth that can be disabled for testing.

    Environment variables:
        AUTH__ENABLED - Enable authentication (default: false)
        AUTH__OIDC_ISSUER_URL - OIDC issuer URL
        AUTH__OIDC_CLIENT_ID - OAuth client ID
        AUTH__OIDC_CLIENT_SECRET - OAuth client secret
        AUTH__SESSION_SECRET - Secret for session cookie signing
    """

    model_config = SettingsConfigDict(
        env_prefix="AUTH__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=False,
        description="Enable authentication (disabled by default for testing)",
    )

    oidc_issuer_url: str = Field(
        default="https://accounts.google.com",
        description="OIDC issuer URL",
    )

    oidc_audience: str = Field(
        default="api",
        description="Expected audience claim in tokens",
    )

    oidc_client_id: str = Field(
        default="",
        description="OIDC client ID",
    )

    oidc_client_secret: str = Field(
        default="",
        description="OIDC client secret",
    )

    oidc_redirect_uri: str = Field(
        default="http://localhost:8000/api/auth/callback",
        description="OAuth redirect URI (callback URL)",
    )

    session_secret: str = Field(
        default="",
        description="Secret key for session cookie signing",
    )


class PostgresSettings(BaseSettings):
    """
    PostgreSQL settings for CloudNativePG.

    Connects to PostgreSQL 18 with pgvector extension running on CloudNativePG.

    Environment variables:
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

    connection_string: str = Field(
        default="postgresql://rem:rem@localhost:5050/rem",
        description="PostgreSQL connection string (default uses Docker Compose port 5050)",
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


class S3Settings(BaseSettings):
    """
    S3 storage settings for file uploads and artifacts.

    Uses IRSA (IAM Roles for Service Accounts) for AWS permissions in EKS.
    For local development, can use MinIO or provide access keys.

    Environment variables:
        S3__BUCKET_NAME - S3 bucket name
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
        default="rem-storage",
        description="S3 bucket name",
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


class APISettings(BaseSettings):
    """
    API server settings.

    Environment variables:
        API__HOST - Host to bind to (0.0.0.0 for Docker, 127.0.0.1 for local)
        API__PORT - Port to listen on
        API__RELOAD - Enable auto-reload for development
        API__WORKERS - Number of worker processes (production)
        API__LOG_LEVEL - Logging level (debug, info, warning, error)
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
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
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
    llm: LLMSettings = Field(default_factory=LLMSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)
    otel: OTELSettings = Field(default_factory=OTELSettings)
    phoenix: PhoenixSettings = Field(default_factory=PhoenixSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    s3: S3Settings = Field(default_factory=S3Settings)
    sqs: SQSSettings = Field(default_factory=SQSSettings)


# Global settings singleton
settings = Settings()
