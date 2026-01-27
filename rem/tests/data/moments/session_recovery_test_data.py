"""Test data generator for session recovery testing.

This module creates realistic test sessions with:
- Long conversations (50-100 messages)
- Moment boundaries with proper lag
- Various conversation types

Usage:
    from tests.data.moments.session_recovery_test_data import (
        create_test_session_with_moments,
        generate_conversation_messages,
        insert_partition_event,
    )
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

# Sample conversation templates for realistic test data
CONVERSATION_TEMPLATES = [
    # Technical discussion about Python/FastAPI
    {
        "topic": "api-development",
        "exchanges": [
            ("How do I set up JWT authentication in FastAPI?", "JWT authentication in FastAPI involves using python-jose or PyJWT libraries..."),
            ("What about refresh tokens?", "Refresh tokens should be stored securely and have longer expiration..."),
            ("How do I handle token revocation?", "You can maintain a blacklist in Redis or use token versioning..."),
            ("What's the best way to test this?", "Use pytest with httpx.AsyncClient for testing FastAPI endpoints..."),
        ],
    },
    # Database discussion
    {
        "topic": "database-design",
        "exchanges": [
            ("Should I use PostgreSQL or MongoDB for this project?", "It depends on your data model. PostgreSQL is great for relational data with ACID compliance..."),
            ("How do I handle migrations?", "For PostgreSQL, use Alembic for schema migrations. It integrates well with SQLAlchemy..."),
            ("What about connection pooling?", "Use asyncpg with connection pooling. Set pool_min_size and pool_max_size based on load..."),
            ("How do I optimize queries?", "Add indexes on frequently queried columns, use EXPLAIN ANALYZE to identify bottlenecks..."),
        ],
    },
    # Deployment discussion
    {
        "topic": "deployment",
        "exchanges": [
            ("How do I deploy to Kubernetes?", "Create a Deployment manifest with your container spec, then expose it with a Service..."),
            ("What about auto-scaling?", "Use HPA (Horizontal Pod Autoscaler) based on CPU/memory metrics or custom metrics..."),
            ("How do I handle secrets?", "Use Kubernetes Secrets or external secret managers like HashiCorp Vault..."),
            ("What's the best CI/CD setup?", "GitHub Actions or GitLab CI work well. Build containers on merge, deploy to staging, then prod..."),
        ],
    },
    # Architecture discussion
    {
        "topic": "architecture",
        "exchanges": [
            ("How should I structure my microservices?", "Start with domain-driven design. Identify bounded contexts and define clear interfaces..."),
            ("What about event-driven architecture?", "Use message queues like RabbitMQ or Kafka for async communication between services..."),
            ("How do I handle distributed transactions?", "Prefer saga pattern over 2PC. Each service handles its own transaction and publishes events..."),
            ("What about observability?", "Implement the three pillars: logging (structured), metrics (Prometheus), and tracing (OpenTelemetry)..."),
        ],
    },
]


def generate_conversation_messages(
    num_messages: int = 50,
    start_time: datetime | None = None,
    topic_mix: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Generate realistic conversation messages.

    Args:
        num_messages: Number of messages to generate
        start_time: Starting timestamp (defaults to now - 2 hours)
        topic_mix: List of topics to include (defaults to all)

    Returns:
        List of message dicts with role, content, timestamp
    """
    if start_time is None:
        start_time = datetime.utcnow() - timedelta(hours=2)

    # Select templates based on topic_mix
    templates = CONVERSATION_TEMPLATES
    if topic_mix:
        templates = [t for t in CONVERSATION_TEMPLATES if t["topic"] in topic_mix]
        if not templates:
            templates = CONVERSATION_TEMPLATES

    messages = []
    current_time = start_time
    template_idx = 0
    exchange_idx = 0

    while len(messages) < num_messages:
        template = templates[template_idx % len(templates)]
        exchanges = template["exchanges"]
        exchange = exchanges[exchange_idx % len(exchanges)]

        # User message
        messages.append({
            "role": "user",
            "content": exchange[0],
            "timestamp": current_time.isoformat() + "Z",
        })
        current_time += timedelta(seconds=30)

        if len(messages) >= num_messages:
            break

        # Assistant response (longer, with detail)
        response = exchange[1]
        # Add some variation to responses
        if len(messages) % 5 == 0:
            response += "\n\nLet me know if you need more details on any of these points."
        if len(messages) % 7 == 0:
            response += f"\n\nThis relates to {template['topic']} best practices."

        messages.append({
            "role": "assistant",
            "content": response,
            "timestamp": current_time.isoformat() + "Z",
        })
        current_time += timedelta(minutes=1, seconds=30)

        exchange_idx += 1
        if exchange_idx >= len(exchanges):
            exchange_idx = 0
            template_idx += 1
            # Add a small break between topics
            current_time += timedelta(minutes=5)

    return messages[:num_messages]


def create_partition_event(
    moment_keys: list[str],
    last_n_moment_keys: list[str],
    recent_summary: str,
    messages_compressed: int,
    timestamp: datetime,
) -> dict[str, Any]:
    """
    Create a partition event message.

    Args:
        moment_keys: Keys of moments just created
        last_n_moment_keys: Last N moment keys overall
        recent_summary: Brief summary of recent journey
        messages_compressed: Number of messages compressed
        timestamp: When the partition occurred

    Returns:
        Message dict formatted as a partition event
    """
    partition_content = {
        "partition_type": "moment_compression",
        "created_at": timestamp.isoformat() + "Z",
        "user_key": "user-test",
        "moment_keys": moment_keys,
        "last_n_moment_keys": last_n_moment_keys,
        "recent_moments_summary": recent_summary,
        "messages_compressed": messages_compressed,
        "summary": f"Compressed {messages_compressed} messages into {len(moment_keys)} moments.",
        "recovery_hint": (
            "This is a memory checkpoint. Use REM LOOKUP on moment_keys for detailed history. "
            "Each moment has previous_moment_keys for chaining backwards."
        ),
    }

    return {
        "role": "tool",
        "tool_name": "session_partition",
        "content": json.dumps(partition_content),
        "timestamp": timestamp.isoformat() + "Z",
        "metadata": {
            "tool_name": "session_partition",
            "tool_result": partition_content,
        },
    }


def create_test_session_data(
    total_messages: int = 80,
    moment_boundary_at: int = 50,
    lag_messages: int = 10,
) -> dict[str, Any]:
    """
    Create a complete test session with moment boundary.

    This creates a session that simulates what would happen after
    the moment builder runs with the lag mechanism:
    - First N messages are "compressed" (before the boundary)
    - Partition event is inserted at the boundary
    - Last M messages (lag) are recent context

    Args:
        total_messages: Total messages in the session
        moment_boundary_at: Where to insert the partition (message index)
        lag_messages: Number of messages after the boundary

    Returns:
        Dict with:
        - messages: All messages including partition event
        - moment_keys: Keys referenced in the partition
        - boundary_index: Where the partition was inserted
    """
    # Generate all messages
    messages = generate_conversation_messages(total_messages)

    # Create moment keys (simulating compressed messages)
    moment_key = f"session-discussion-{datetime.utcnow().strftime('%Y%m%d')}"
    moment_keys = [moment_key]
    last_n_moment_keys = [moment_key]

    # Create partition event at the boundary point
    boundary_timestamp = datetime.fromisoformat(
        messages[moment_boundary_at - 1]["timestamp"].rstrip("Z")
    )

    partition = create_partition_event(
        moment_keys=moment_keys,
        last_n_moment_keys=last_n_moment_keys,
        recent_summary=f"Technical discussion covering API development, authentication, and deployment. User is building a Python/FastAPI application.",
        messages_compressed=moment_boundary_at,
        timestamp=boundary_timestamp,
    )

    # Insert partition event into the message list
    messages_with_partition = (
        messages[:moment_boundary_at]
        + [partition]
        + messages[moment_boundary_at:]
    )

    return {
        "messages": messages_with_partition,
        "moment_keys": moment_keys,
        "boundary_index": moment_boundary_at,
        "total_original": total_messages,
        "lag_messages": len(messages) - moment_boundary_at,
    }


def create_multi_session_test_data(
    num_sessions: int = 5,
    messages_per_session: int = 60,
    sessions_with_moments: int = 3,
) -> list[dict[str, Any]]:
    """
    Create multiple test sessions, some with moment boundaries.

    Args:
        num_sessions: Number of sessions to create
        messages_per_session: Messages per session
        sessions_with_moments: Number of sessions that have moment boundaries

    Returns:
        List of session data dicts
    """
    sessions = []
    base_time = datetime.utcnow() - timedelta(days=7)

    for i in range(num_sessions):
        session_time = base_time + timedelta(days=i)

        if i < sessions_with_moments:
            # Session with moment boundary
            session_data = create_test_session_data(
                total_messages=messages_per_session,
                moment_boundary_at=int(messages_per_session * 0.7),
                lag_messages=int(messages_per_session * 0.3),
            )
            session_data["session_id"] = f"session-{uuid.uuid4().hex[:8]}"
            session_data["has_moments"] = True
            session_data["session_time"] = session_time.isoformat()
        else:
            # Session without moment boundary
            messages = generate_conversation_messages(
                num_messages=messages_per_session,
                start_time=session_time,
            )
            session_data = {
                "session_id": f"session-{uuid.uuid4().hex[:8]}",
                "messages": messages,
                "moment_keys": [],
                "has_moments": False,
                "session_time": session_time.isoformat(),
            }

        sessions.append(session_data)

    return sessions


# Pre-generated test data for quick access
LONG_SESSION_WITH_MOMENT = create_test_session_data(
    total_messages=80,
    moment_boundary_at=50,
)

SHORT_SESSION_NO_MOMENT = {
    "messages": generate_conversation_messages(num_messages=20),
    "moment_keys": [],
    "has_moments": False,
}


if __name__ == "__main__":
    # Generate sample data when run directly
    import json

    print("=== Long Session with Moment Boundary ===")
    data = create_test_session_data(total_messages=80, moment_boundary_at=50)
    print(f"Total messages: {len(data['messages'])}")
    print(f"Moment boundary at: {data['boundary_index']}")
    print(f"Moment keys: {data['moment_keys']}")

    # Find and display the partition event
    for i, msg in enumerate(data["messages"]):
        if msg.get("role") == "tool" and msg.get("tool_name") == "session_partition":
            print(f"\nPartition event at index {i}:")
            print(json.dumps(json.loads(msg["content"]), indent=2))
            break

    print("\n=== Multi-Session Test Data ===")
    sessions = create_multi_session_test_data(num_sessions=5)
    for s in sessions:
        print(f"Session {s['session_id']}: {len(s['messages'])} messages, has_moments={s.get('has_moments', False)}")
