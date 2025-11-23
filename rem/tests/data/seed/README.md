# Test Seed Data

This directory contains sample data for testing and development purposes.

## Files

- `001_sample_data.yaml` - Comprehensive sample data in YAML format including users, resources, moments, messages, files, and schemas

## Loading Seed Data

Seed data is **not** automatically loaded. You must manually load it when needed.

### Load with Python Script

```python
import yaml
from pathlib import Path
from datetime import datetime
from rem.models.entities import User, Resource, Moment, Message, File, Schema

def load_seed_data(session):
    """Load YAML seed data into database."""
    seed_file = Path(__file__).parent / "data" / "seed" / "001_sample_data.yaml"
    data = yaml.safe_load(seed_file.read_text())

    # Load users
    for user_data in data.get("users", []):
        user = User(**user_data)
        session.add(user)

    # Load resources
    for resource_data in data.get("resources", []):
        resource = Resource(**resource_data)
        session.add(resource)

    # Load moments
    for moment_data in data.get("moments", []):
        moment_data["starts_timestamp"] = datetime.fromisoformat(moment_data["starts_timestamp"])
        if moment_data.get("ends_timestamp"):
            moment_data["ends_timestamp"] = datetime.fromisoformat(moment_data["ends_timestamp"])
        moment = Moment(**moment_data)
        session.add(moment)

    # Load messages
    for message_data in data.get("messages", []):
        message = Message(**message_data)
        session.add(message)

    # Load files
    for file_data in data.get("files", []):
        file = File(**file_data)
        session.add(file)

    # Load schemas
    for schema_data in data.get("schemas", []):
        schema = Schema(**schema_data)
        session.add(schema)

    session.commit()
```

### Load with pytest Fixture

```python
import pytest
import yaml
from pathlib import Path

@pytest.fixture
def seed_data():
    """Load seed data for tests."""
    seed_file = Path(__file__).parent.parent / "data" / "seed" / "001_sample_data.yaml"
    return yaml.safe_load(seed_file.read_text())

@pytest.fixture
def db_with_seed_data(db_session, seed_data):
    """Database session with seed data loaded."""
    # Load all entities from seed_data into db_session
    # ... (implementation as shown above)
    yield db_session
```

## Sample Data Contents

### Users (3)
- Sarah Chen (engineer, backend/python)
- Mike Johnson (designer, ui-ux/frontend)
- Alex Kim (engineer, frontend/react)

### Resources (3)
- API Design Document v2 (document)
- Q4 2024 Retrospective Notes (conversation)
- Frontend Component Refactor (artifact)

### Moments (3)
- Q4 2024 Team Retrospective (meeting, team-event)
- API Design Review Session (meeting, design-review)
- Frontend Pairing Session (coding-session, development)

### Messages (4)
- Team chat conversation
- Assistant query response

### Files (3)
- API architecture diagram (PNG, completed)
- Q4 retro recording (MP4, completed)
- Design mockups (PDF, pending)

### Schemas (3 Agent Definitions)
- REM Query Assistant (assistant category)
- Document Analyzer (analyzer category)
- Code Review Assistant (reviewer category)

## User ID

All sample data uses user ID: `acme-corp` (with optional tenant_id field for future multi-tenancy)

## Testing Queries

After loading seed data, you can test with:

```bash
# Query for Sarah Chen's documents
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: acme-corp" \
  -d '{
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [{"role": "user", "content": "What documents did Sarah Chen author?"}],
    "stream": false
  }'

# Load a specific agent schema
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: acme-corp" \
  -H "X-Agent-Schema: schema_rem_assistant" \
  -d '{
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [{"role": "user", "content": "Find moments about API design"}],
    "stream": false
  }'
```

## Data Format

The YAML file uses a structured format with top-level keys for each entity type:
- `users` - User entities
- `resources` - Content units (documents, conversations, artifacts)
- `moments` - Temporal narratives (meetings, coding sessions)
- `messages` - Chat messages and conversations
- `files` - File metadata and tracking
- `schemas` - Agent schema definitions

All timestamps use ISO 8601 format (`YYYY-MM-DDTHH:MM:SS`).
All entities include CoreModel fields (id, user_id, metadata, tags, graph_edges, etc.).

## Timestamp Format

All timestamps in seed data YAML files use ISO 8601 format: `YYYY-MM-DDTHH:MM:SS`

**IMPORTANT:** Timestamps are treated as timezone-naive UTC:
- ISO strings with timezone info (e.g., `2024-01-01T10:00:00Z`) are automatically converted to timezone-naive
- System assumes all datetimes are UTC
- No timezone conversions are performed

**Example:**
```yaml
moments:
  - starts_timestamp: "2024-01-01T10:00:00"  # Treated as UTC
    ends_timestamp: "2024-01-01T11:00:00"
```
