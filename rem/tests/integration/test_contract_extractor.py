"""
Integration tests for the Contract Extractor agent.
"""
from rem.settings import settings
import asyncio
from pathlib import Path
import pytest
import yaml

from rem.agentic.context import AgentContext
from rem.agentic.providers.pydantic_ai import create_agent
from rem.api.mcp_router.tools import ingest_into_rem, init_services
from rem.settings import settings
from rem.models.entities import Resource
from rem.services.postgres import PostgresService
from rem.services.rem import RemService

# Mark all tests in this module as asyncio
pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def event_loop():
    """Create an instance of the default event loop for our test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def postgres_service() -> PostgresService:
    """Create PostgresService instance and ensure a clean database for each test.

    Note: Database schema should already exist from prior migrations.
    This fixture only cleans up data, not schema.
    """
    pg = PostgresService()
    await pg.connect()

    # Ensure a clean database state for each test by truncating data
    # Do NOT drop schema as it removes functions/tables for other tests
    # Do NOT re-run migrations as indexes may already exist
    cleanup_sql_commands = [
        "TRUNCATE TABLE resources CASCADE",
        "TRUNCATE TABLE users CASCADE",
        "TRUNCATE TABLE moments CASCADE",
        "TRUNCATE TABLE files CASCADE",
        "TRUNCATE TABLE messages CASCADE",
    ]
    for cmd in cleanup_sql_commands:
        try:
            await pg.execute_ddl(cmd)
        except Exception as e:
            # Tables might not exist yet, that's ok
            pass

    yield pg
    await pg.disconnect()


@pytest.mark.integration
async def test_ingest_contract_pdf(postgres_service: PostgresService, monkeypatch):
    """
    Tests that the service_contract.pdf can be ingested successfully.
    """
    # Initialize MCP tools with services
    rem_service = RemService(postgres_service=postgres_service)
    init_services(postgres_service=postgres_service, rem_service=rem_service)

    # Disable S3 for internal storage during test
    monkeypatch.setattr(settings.s3, "bucket_name", None)

    # Override chunking settings to ensure chunks are always created for test data
    monkeypatch.setattr(settings.chunking, "min_chunk_size", 1)
    monkeypatch.setattr(settings.chunking, "chunk_size", 10)

    user_id=settings.test.effective_user_id
    contract_path = Path("tests/data/content-examples/pdf/service_contract.pdf")

    assert contract_path.exists(), "Contract PDF not found"

    # Ingest the file (tenant_id removed - using user_id for partitioning)
    result = await ingest_into_rem(
        file_uri=str(contract_path.absolute()),
        user_id=user_id,
        is_local_server=True,
    )

    assert result["processing_status"] == "completed"
    assert result["resources_created"] > 0
    assert result["file_name"] == contract_path.name


@pytest.mark.integration
async def test_run_contract_extractor_agent(monkeypatch):
    """
    Tests running the contract-extractor agent on a contract.
    """
    from unittest.mock import AsyncMock

    # Mock the API key to avoid UserError during agent creation
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy_key")

    # Mock the agent.run method to prevent actual LLM calls
    class MockAgentRunResult:
        document_title: str = "Mock Contract"
        parties: list[str] = ["ACME Corp.", "Innovate LLC"]
        effective_date: str = "2024-01-01"
        key_terms: list[str] = ["Service Agreement", "Effective Date"]
        key_clauses: list[dict] = [{"type": "Payment", "section": "3.1", "summary": "Net-30"}]
        risk_assessment: str = "low"
        tools_used: list[str] = ["search_rem", "ingest_to_rem"]

        def model_dump_json(self, indent=None):
            import json
            # Convert to dict for JSON serialization
            data = {
                "document_title": self.document_title,
                "parties": self.parties,
                "effective_date": self.effective_date,
                "key_terms": self.key_terms,
                "key_clauses": self.key_clauses,
                "risk_assessment": self.risk_assessment,
                "tools_used": self.tools_used,
            }
            return json.dumps(data, indent=indent)
    
    # We create an instance of the mock result and then patch the run method
    mock_result_instance = MockAgentRunResult()
    monkeypatch.setattr("pydantic_ai.agent.Agent.run", AsyncMock(return_value=mock_result_instance))

    # Load the agent schema
    schema_path = Path("src/rem/schemas/agents/examples/contract-extractor.yaml")
    assert schema_path.exists(), "Contract extractor schema not found"
    with open(schema_path, "r") as f:
        agent_schema = yaml.safe_load(f)

    # Load the contract content
    contract_text = """
    SERVICE AGREEMENT
    This Service Agreement (the "Agreement") is made and entered into as of January 1, 2024 (the "Effective Date"),
    by and between ACME Corp., a Delaware corporation ("Client"), and Innovate LLC, a California limited liability company ("Provider").
    """

    # Create agent context (tenant_id deprecated, using user_id)
    context = AgentContext(user_id=settings.test.effective_user_id)

    # Create the agent
    agent = await create_agent(
        context=context,
        agent_schema_override=agent_schema,
    )

    # Run the agent on the contract text
    result = await agent.run(contract_text)

    # Assertions
    assert result is not None
    assert hasattr(result, "document_title")
    assert hasattr(result, "parties")
    assert hasattr(result, "effective_date")
    assert hasattr(result, "key_terms")
    assert hasattr(result, "key_clauses")
    assert hasattr(result, "risk_assessment")

    assert result.document_title == "Mock Contract"
    assert "ACME Corp." in result.parties
    assert "Innovate LLC" in result.parties
    assert result.risk_assessment == "low"
    assert "search_rem" in result.tools_used
    assert "ingest_to_rem" in result.tools_used
    assert len(result.parties) > 0

    print("\n--- Agent Output ---")
    print(result.model_dump_json(indent=2))
    print("--- End Agent Output ---")
