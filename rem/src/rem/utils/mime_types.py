"""
Centralized MIME type mappings for file format detection.

Provides bidirectional mappings between file extensions and MIME types.
Use these constants throughout the codebase instead of inline dictionaries.
"""

# Extension to MIME type mapping (extension includes leading dot)
EXTENSION_TO_MIME: dict[str, str] = {
    # Images
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".svg": "image/svg+xml",
    # Documents
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    # Audio
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/x-m4a",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".aac": "audio/aac",
    # Video
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    # Text/Code
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".json": "application/json",
    ".yaml": "application/x-yaml",
    ".yml": "application/x-yaml",
    ".xml": "application/xml",
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".py": "text/x-python",
    ".ts": "application/typescript",
    ".csv": "text/csv",
}

# MIME type to extension mapping (reverse of above, preferring shorter extensions)
MIME_TO_EXTENSION: dict[str, str] = {
    # Images
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/svg+xml": ".svg",
    # Documents
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    # Audio
    "audio/wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/x-m4a": ".m4a",
    "audio/mp4": ".m4a",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "audio/aac": ".aac",
    # Video
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/x-msvideo": ".avi",
    "video/quicktime": ".mov",
    # Text/Code
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/json": ".json",
    "application/x-yaml": ".yaml",
    "application/xml": ".xml",
    "text/html": ".html",
    "text/css": ".css",
    "application/javascript": ".js",
    "text/x-python": ".py",
    "application/typescript": ".ts",
    "text/csv": ".csv",
}

# Grouped by category for convenience
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".avi", ".mov"}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".xml", ".html", ".css", ".js", ".py", ".ts", ".csv"}


def get_extension(mime_type: str, default: str = ".bin") -> str:
    """
    Get file extension for a MIME type.

    Args:
        mime_type: MIME type string (e.g., "image/png")
        default: Default extension if MIME type not found

    Returns:
        File extension with leading dot (e.g., ".png")
    """
    return MIME_TO_EXTENSION.get(mime_type, default)


def get_mime_type(extension: str, default: str = "application/octet-stream") -> str:
    """
    Get MIME type for a file extension.

    Args:
        extension: File extension with or without leading dot
        default: Default MIME type if extension not found

    Returns:
        MIME type string (e.g., "image/png")
    """
    # Normalize extension to have leading dot
    ext = extension if extension.startswith(".") else f".{extension}"
    return EXTENSION_TO_MIME.get(ext.lower(), default)


def is_image(extension_or_mime: str) -> bool:
    """Check if extension or MIME type represents an image."""
    if extension_or_mime.startswith("."):
        return extension_or_mime.lower() in IMAGE_EXTENSIONS
    return extension_or_mime.startswith("image/")


def is_audio(extension_or_mime: str) -> bool:
    """Check if extension or MIME type represents audio."""
    if extension_or_mime.startswith("."):
        return extension_or_mime.lower() in AUDIO_EXTENSIONS
    return extension_or_mime.startswith("audio/")


def is_document(extension_or_mime: str) -> bool:
    """Check if extension or MIME type represents a document."""
    if extension_or_mime.startswith("."):
        return extension_or_mime.lower() in DOCUMENT_EXTENSIONS
    # Check common document MIME types
    doc_mimes = {"application/pdf", "application/msword"}
    return extension_or_mime in doc_mimes or "officedocument" in extension_or_mime
