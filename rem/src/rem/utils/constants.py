"""
Centralized constants for the REM system.

All magic numbers and commonly-used values should be defined here
to ensure consistency and make tuning easier.
"""

# =============================================================================
# Embedding Model Constants
# =============================================================================

# OpenAI embedding dimensions by model
OPENAI_EMBEDDING_DIMS_SMALL = 1536  # text-embedding-3-small
OPENAI_EMBEDDING_DIMS_LARGE = 3072  # text-embedding-3-large
OPENAI_EMBEDDING_DIMS_ADA = 1536  # text-embedding-ada-002

# Default embedding dimension (text-embedding-3-small)
DEFAULT_EMBEDDING_DIMS = 1536

# Voyage AI embedding dimensions
VOYAGE_EMBEDDING_DIMS = 1024  # voyage-2

# =============================================================================
# HTTP/API Timeouts (seconds)
# =============================================================================

HTTP_TIMEOUT_DEFAULT = 30.0  # Standard API calls
HTTP_TIMEOUT_LONG = 60.0  # Vision/embedding APIs
HTTP_TIMEOUT_VERY_LONG = 300.0  # Subprocess/batch operations

# Request timeout for httpx AsyncClient
ASYNC_CLIENT_TIMEOUT = 300.0

# =============================================================================
# Audio Processing Constants
# =============================================================================

# Minimum valid WAV file size (header only)
WAV_HEADER_MIN_BYTES = 44

# OpenAI Whisper API cost per minute (USD)
WHISPER_COST_PER_MINUTE = 0.006

# Audio chunking parameters
AUDIO_CHUNK_TARGET_SECONDS = 60.0  # Target chunk duration
AUDIO_CHUNK_WINDOW_SECONDS = 2.0  # Window for silence detection
SILENCE_THRESHOLD_DB = -40.0  # Silence detection threshold
MIN_SILENCE_MS = 500  # Minimum silence duration to split on

# =============================================================================
# File Processing Constants
# =============================================================================

# Subprocess timeout for document parsing
SUBPROCESS_TIMEOUT_SECONDS = 300  # 5 minutes

# Maximum file sizes
MAX_AUDIO_FILE_SIZE_MB = 25  # Whisper API limit

# =============================================================================
# Database/Query Constants
# =============================================================================

# Default batch sizes
DEFAULT_BATCH_SIZE = 100
EMBEDDING_BATCH_SIZE = 50

# Default pagination limits
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# =============================================================================
# Rate Limiting
# =============================================================================

# Default retry settings
DEFAULT_MAX_RETRIES = 3
RETRY_BACKOFF_MULTIPLIER = 1
RETRY_BACKOFF_MIN = 1
RETRY_BACKOFF_MAX = 60

# =============================================================================
# S3/Storage Constants
# =============================================================================

S3_URI_PREFIX = "s3://"
FILE_URI_PREFIX = "file://"

# =============================================================================
# LLM Constants
# =============================================================================

# Default max tokens for vision analysis
VISION_MAX_TOKENS = 2048

# Default temperature
DEFAULT_TEMPERATURE = 0.0
