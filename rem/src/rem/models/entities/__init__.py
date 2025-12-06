"""
REM Entity Models

Core entity types for the REM system:
- Resources: Base content units (documents, conversations, artifacts)
- ImageResources: Image-specific resources with CLIP embeddings
- Messages: Communication content
- Sessions: Conversation sessions (normal or evaluation mode)
- SharedSessions: Session sharing between users for collaboration
- Feedback: User feedback on messages/sessions with trace integration
- Users: User entities
- Files: File metadata and tracking
- Moments: Temporal narratives (meetings, coding sessions, conversations)
- Schemas: Agent schema definitions (JsonSchema specifications for Pydantic AI)
- Ontologies: Domain-specific extracted knowledge from files
- OntologyConfigs: User-defined rules for automatic ontology extraction

All entities inherit from CoreModel and support:
- Graph connectivity via InlineEdge
- Temporal tracking
- Flexible metadata
- Natural language labels for conversational queries
"""

from .domain_resource import DomainResource
from .feedback import Feedback, FeedbackCategory
from .file import File
from .image_resource import ImageResource
from .message import Message
from .moment import Moment
from .ontology import Ontology
from .ontology_config import OntologyConfig
from .resource import Resource
from .schema import Schema
from .session import Session, SessionMode
from .shared_session import (
    SharedSession,
    SharedSessionCreate,
    SharedWithMeResponse,
    SharedWithMeSummary,
)
from .subscriber import Subscriber, SubscriberOrigin, SubscriberStatus
from .user import User, UserTier

__all__ = [
    "Resource",
    "DomainResource",
    "ImageResource",
    "Message",
    "Session",
    "SessionMode",
    "SharedSession",
    "SharedSessionCreate",
    "SharedWithMeResponse",
    "SharedWithMeSummary",
    "Feedback",
    "FeedbackCategory",
    "User",
    "UserTier",
    "Subscriber",
    "SubscriberStatus",
    "SubscriberOrigin",
    "File",
    "Moment",
    "Schema",
    "Ontology",
    "OntologyConfig",
]
