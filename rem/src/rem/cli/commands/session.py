"""
CLI command for viewing and simulating session conversations.

Usage:
    rem session show <user_id> [--session-id] [--role user|assistant|system]
    rem session show <user_id> --simulate-next [--save] [--custom-sim-prompt "..."]

Examples:
    # Show all messages for a user
    rem session show 11111111-1111-1111-1111-111111111001

    # Show only user messages
    rem session show 11111111-1111-1111-1111-111111111001 --role user

    # Simulate next user message
    rem session show 11111111-1111-1111-1111-111111111001 --simulate-next

    # Simulate with custom prompt and save
    rem session show 11111111-1111-1111-1111-111111111001 --simulate-next --save \
        --custom-sim-prompt "Respond as an anxious patient"
"""

import asyncio
from pathlib import Path
from typing import Literal

import click
import yaml
from loguru import logger

from ...models.entities.user import User
from ...models.entities.message import Message
from ...services.postgres import get_postgres_service
from ...services.postgres.repository import Repository
from ...settings import settings


SIMULATOR_PROMPT = """You are simulating a patient in a mental health conversation.

## Context
You are continuing a conversation with a clinical evaluation agent. Based on the
user profile and conversation history below, generate the next realistic patient message.

## User Profile
{user_profile}

## Conversation History
{conversation_history}

## Instructions
- Stay in character as the patient described in the profile
- Your response should be natural, conversational, and consistent with the patient's presentation
- Consider the patient's risk level, symptoms, and communication style
- Do NOT include any metadata or role labels - just the raw message content
- Keep responses concise (1-3 sentences typical for conversation)

Generate the next patient message:"""


async def _load_user_and_messages(
    user_id: str,
    session_id: str | None = None,
    role_filter: str | None = None,
    limit: int = 100,
) -> tuple[User | None, list[Message]]:
    """Load user profile and messages from database."""
    pg = get_postgres_service()
    if not pg:
        logger.error("PostgreSQL not available")
        return None, []

    await pg.connect()

    try:
        # Load user
        user_repo = Repository(User, "users", db=pg)
        user = await user_repo.get_by_id(user_id, tenant_id="default")

        # Load messages
        message_repo = Repository(Message, "messages", db=pg)
        filters = {"user_id": user_id}
        if session_id:
            filters["session_id"] = session_id

        messages = await message_repo.find(
            filters=filters,
            order_by="created_at ASC",
            limit=limit,
        )

        # Filter by role if specified
        if role_filter:
            messages = [m for m in messages if m.message_type == role_filter]

        return user, messages

    finally:
        await pg.disconnect()


def _format_user_yaml(user: User | None) -> str:
    """Format user profile as YAML."""
    if not user:
        return "# No user found"

    data = {
        "id": str(user.id),
        "name": user.name,
        "summary": user.summary,
        "interests": user.interests,
        "preferred_topics": user.preferred_topics,
        "metadata": user.metadata,
    }
    return yaml.dump(data, default_flow_style=False, allow_unicode=True)


def _format_messages_yaml(messages: list[Message]) -> str:
    """Format messages as YAML."""
    if not messages:
        return "# No messages found"

    data = []
    for msg in messages:
        data.append({
            "role": msg.message_type or "unknown",
            "content": msg.content,
            "session_id": msg.session_id,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        })
    return yaml.dump(data, default_flow_style=False, allow_unicode=True)


def _format_conversation_for_llm(messages: list[Message]) -> str:
    """Format conversation history for LLM context."""
    lines = []
    for msg in messages:
        role = msg.message_type or "unknown"
        lines.append(f"[{role.upper()}]: {msg.content}")
    return "\n\n".join(lines) if lines else "(No previous messages)"


async def _simulate_next_message(
    user: User | None,
    messages: list[Message],
    custom_prompt: str | None = None,
) -> str:
    """Use LLM to simulate the next patient message."""
    from pydantic_ai import Agent

    # Build context
    user_profile = _format_user_yaml(user) if user else "Unknown patient"
    conversation_history = _format_conversation_for_llm(messages)

    # Use custom prompt or default
    if custom_prompt:
        # Check if it's a file path
        if Path(custom_prompt).exists():
            prompt_template = Path(custom_prompt).read_text()
        else:
            prompt_template = custom_prompt
        # Simple variable substitution
        prompt = prompt_template.replace("{user_profile}", user_profile)
        prompt = prompt.replace("{conversation_history}", conversation_history)
    else:
        prompt = SIMULATOR_PROMPT.format(
            user_profile=user_profile,
            conversation_history=conversation_history,
        )

    # Create simple agent for simulation
    agent = Agent(
        model=settings.llm.default_model,
        system_prompt="You are a patient simulator. Generate realistic patient responses.",
    )

    result = await agent.run(prompt)
    return result.output


async def _save_message(
    user_id: str,
    session_id: str | None,
    content: str,
    role: str = "user",
) -> Message:
    """Save a simulated message to the database."""
    from uuid import uuid4

    pg = get_postgres_service()
    if not pg:
        raise RuntimeError("PostgreSQL not available")

    await pg.connect()

    try:
        message_repo = Repository(Message, "messages", db=pg)

        message = Message(
            id=uuid4(),
            user_id=user_id,
            tenant_id="default",
            session_id=session_id or str(uuid4()),
            content=content,
            message_type=role,
        )

        await message_repo.upsert(message)
        return message

    finally:
        await pg.disconnect()


@click.group()
def session():
    """Session viewing and simulation commands."""
    pass


@session.command("show")
@click.argument("user_id")
@click.option("--session-id", "-s", help="Filter by session ID")
@click.option(
    "--role", "-r",
    type=click.Choice(["user", "assistant", "system", "tool"]),
    help="Filter messages by role",
)
@click.option("--limit", "-l", default=100, help="Max messages to load")
@click.option("--simulate-next", is_flag=True, help="Simulate the next patient message")
@click.option("--save", is_flag=True, help="Save simulated message to database")
@click.option(
    "--custom-sim-prompt", "-p",
    help="Custom simulation prompt (text or file path)",
)
def show(
    user_id: str,
    session_id: str | None,
    role: str | None,
    limit: int,
    simulate_next: bool,
    save: bool,
    custom_sim_prompt: str | None,
):
    """
    Show user profile and session messages.

    USER_ID: The user identifier to load.

    Examples:

        # Show user and all messages
        rem session show 11111111-1111-1111-1111-111111111001

        # Show only assistant responses
        rem session show 11111111-1111-1111-1111-111111111001 --role assistant

        # Simulate next patient message
        rem session show 11111111-1111-1111-1111-111111111001 --simulate-next

        # Simulate and save to database
        rem session show 11111111-1111-1111-1111-111111111001 --simulate-next --save
    """
    asyncio.run(_show_async(
        user_id=user_id,
        session_id=session_id,
        role_filter=role,
        limit=limit,
        simulate_next=simulate_next,
        save=save,
        custom_sim_prompt=custom_sim_prompt,
    ))


async def _show_async(
    user_id: str,
    session_id: str | None,
    role_filter: str | None,
    limit: int,
    simulate_next: bool,
    save: bool,
    custom_sim_prompt: str | None,
):
    """Async implementation of show command."""
    # Load data
    user, messages = await _load_user_and_messages(
        user_id=user_id,
        session_id=session_id,
        role_filter=role_filter if not simulate_next else None,  # Need all messages for simulation
        limit=limit,
    )

    # Display user profile
    click.echo("\n# User Profile")
    click.echo("---")
    click.echo(_format_user_yaml(user))

    # Display messages (apply filter for display if simulating)
    display_messages = messages
    if simulate_next and role_filter:
        display_messages = [m for m in messages if m.message_type == role_filter]

    click.echo("\n# Messages")
    click.echo("---")
    click.echo(_format_messages_yaml(display_messages))

    # Simulate next message if requested
    if simulate_next:
        click.echo("\n# Simulated Next Message")
        click.echo("---")

        try:
            simulated = await _simulate_next_message(
                user=user,
                messages=messages,
                custom_prompt=custom_sim_prompt,
            )
            click.echo(f"role: user")
            click.echo(f"content: |\n  {simulated}")

            if save:
                saved_msg = await _save_message(
                    user_id=user_id,
                    session_id=session_id,
                    content=simulated,
                    role="user",
                )
                logger.success(f"Saved message: {saved_msg.id}")

        except Exception as e:
            logger.error(f"Simulation failed: {e}")
            raise


def register_command(cli_group):
    """Register the session command group."""
    cli_group.add_command(session)
