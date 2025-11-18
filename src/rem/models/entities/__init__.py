"""
REM Entity Models

Core entity types for the REM system:
- Resources: Base content units (documents, conversations, artifacts)
- Messages: Communication content
- Users: User entities
- Files: File metadata and tracking
- Moments: Temporal narratives (meetings, coding sessions, conversations)
- Schemas: Agent schema definitions (JsonSchema specifications for Pydantic AI)

All entities inherit from CoreModel and support:
- Graph connectivity via InlineEdge
- Temporal tracking
- Flexible metadata
- Natural language labels for conversational queries
"""

from .file import File
from .message import Message
from .moment import Moment
from .resource import Resource
from .schema import Schema
from .user import User

__all__ = ["Resource", "Message", "User", "File", "Moment", "Schema"]
