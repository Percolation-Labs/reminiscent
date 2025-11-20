"""
File - File metadata and tracking in REM.

Files represent uploaded or referenced files (PDFs, images, audio, etc.)
that are parsed into Resources or used as input to dreaming workflows.

File entities track:
- File metadata (name, size, mime type)
- Storage location (URI)
- Processing status
- Relationships to derived Resources
"""

from typing import Optional

from pydantic import Field

from ..core import CoreModel


class File(CoreModel):
    """
    File metadata and tracking.

    Represents files uploaded to or referenced by the REM system,
    tracking their metadata and processing status. Tenant isolation
    is provided via CoreModel.tenant_id field.
    """

    name: str = Field(
        ...,
        description="File name",
    )
    uri: str = Field(
        ...,
        description="File storage URI (S3, local path, etc.)",
    )
    content: Optional[str] = Field(
        default=None,
        description="Extracted text content (if applicable)",
    )
    timestamp: Optional[str] = Field(
        default=None,
        description="File creation/modification timestamp",
    )
    size_bytes: Optional[int] = Field(
        default=None,
        description="File size in bytes",
    )
    mime_type: Optional[str] = Field(
        default=None,
        description="File MIME type",
    )
    processing_status: Optional[str] = Field(
        default="pending",
        description="File processing status (pending, processing, completed, failed)",
    )
