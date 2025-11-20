"""
RemService - REM query execution service (wrapper around PostgresService).

Delegates to PostgreSQL functions for performance:
- LOOKUP → rem_lookup() function (O(1) KV_STORE)
- FUZZY → rem_fuzzy() function (pg_trgm similarity)
- SEARCH → rem_search() function (vector similarity with embeddings)
- SQL → Direct PostgresService.execute() (pushed down to Postgres)
- TRAVERSE → rem_traverse() function (recursive graph traversal)

Design:
- RemService wraps PostgresService, does NOT duplicate logic
- All queries pushed down to Postgres for performance
- Model schema inspection for validation only
- Exceptions for missing fields/embeddings
"""

from typing import Any

from loguru import logger

from ...models.core import (
    FuzzyParameters,
    LookupParameters,
    QueryType,
    RemQuery,
    SearchParameters,
    SQLParameters,
    TraverseParameters,
)
from .exceptions import (
    ContentFieldNotFoundError,
    EmbeddingFieldNotFoundError,
    FieldNotFoundError,
    InvalidParametersError,
    QueryExecutionError,
)


class RemService:
    """
    REM query execution service.

    Wraps PostgresService and delegates all queries to PostgreSQL functions.
    """

    def __init__(self, postgres_service: Any, model_registry: dict[str, Any] | None = None):
        """
        Initialize REM service.

        Args:
            postgres_service: PostgresService instance
            model_registry: Optional dict mapping table names to Pydantic models
        """
        self.db = postgres_service
        self.model_registry = model_registry or {}

    def register_model(self, table_name: str, model: Any):
        """
        Register a Pydantic model for schema validation.

        Args:
            table_name: Table name (e.g., "resources")
            model: Pydantic model class
        """
        self.model_registry[table_name] = model
        logger.debug(f"Registered model {model.__name__} for table {table_name}")

    def _get_model_fields(self, table_name: str) -> list[str]:
        """Get list of field names from registered model."""
        if table_name not in self.model_registry:
            return []
        model = self.model_registry[table_name]
        return list(model.model_fields.keys())

    def _get_embeddable_fields(self, table_name: str) -> list[str]:
        """
        Get list of fields that have embeddings.

        Uses register_type conventions:
        - Fields with json_schema_extra={"embed": True}
        - Default embeddable fields: content, description, summary, text, body, message, notes
        """
        if table_name not in self.model_registry:
            return []

        model = self.model_registry[table_name]
        embeddable = []

        DEFAULT_EMBED_FIELDS = {
            "content",
            "description",
            "summary",
            "text",
            "body",
            "message",
            "notes",
        }

        for field_name, field_info in model.model_fields.items():
            # Check json_schema_extra for explicit embed configuration
            json_extra = getattr(field_info, "json_schema_extra", None)
            if json_extra and isinstance(json_extra, dict):
                embed = json_extra.get("embed")
                if embed is True:
                    embeddable.append(field_name)
                    continue
                elif embed is False:
                    continue

            # Default: embed if field name matches common content fields
            if field_name.lower() in DEFAULT_EMBED_FIELDS:
                embeddable.append(field_name)

        return embeddable

    async def execute_query(self, query: RemQuery) -> dict[str, Any]:
        """
        Execute REM query with delegation to PostgreSQL functions.

        Args:
            query: RemQuery with type and parameters

        Returns:
            Query results with metadata

        Raises:
            QueryExecutionError: If query execution fails
            FieldNotFoundError: If field does not exist
            EmbeddingFieldNotFoundError: If field has no embeddings
        """
        try:
            if query.query_type == QueryType.LOOKUP:
                return await self._execute_lookup(query.parameters, query.tenant_id)
            elif query.query_type == QueryType.FUZZY:
                return await self._execute_fuzzy(query.parameters, query.tenant_id)
            elif query.query_type == QueryType.SEARCH:
                return await self._execute_search(query.parameters, query.tenant_id)
            elif query.query_type == QueryType.SQL:
                return await self._execute_sql(query.parameters, query.tenant_id)
            elif query.query_type == QueryType.TRAVERSE:
                return await self._execute_traverse(query.parameters, query.tenant_id)
            else:
                raise InvalidParametersError("UNKNOWN", f"Unknown query type: {query.query_type}")
        except (FieldNotFoundError, EmbeddingFieldNotFoundError, InvalidParametersError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            logger.exception(f"REM query execution failed: {e}")
            raise QueryExecutionError(query.query_type.value, str(e), e)

    async def _execute_lookup(
        self, params: LookupParameters, tenant_id: str
    ) -> dict[str, Any]:
        """
        Execute LOOKUP query via rem_lookup() PostgreSQL function.

        Delegates to: rem_lookup(entity_key, tenant_id, user_id)

        Args:
            params: LookupParameters with entity key
            tenant_id: Tenant identifier

        Returns:
            Dict with entity metadata from KV_STORE
        """
        from .queries import LOOKUP_QUERY, get_lookup_params

        query_params = get_lookup_params(params.entity_key, tenant_id, params.user_id)
        results = await self.db.execute(LOOKUP_QUERY, query_params)

        return {
            "query_type": "LOOKUP",
            "entity_key": params.entity_key,
            "results": results,
            "count": len(results),
        }

    async def _execute_fuzzy(
        self, params: FuzzyParameters, tenant_id: str
    ) -> dict[str, Any]:
        """
        Execute FUZZY query via rem_fuzzy() PostgreSQL function.

        Delegates to: rem_fuzzy(query, tenant_id, threshold, limit, user_id)

        Args:
            params: FuzzyParameters with query text and threshold
            tenant_id: Tenant identifier

        Returns:
            Dict with fuzzy-matched entities ordered by similarity
        """
        from .queries import FUZZY_QUERY, get_fuzzy_params

        query_params = get_fuzzy_params(
            params.query_text,
            tenant_id,
            params.threshold,
            params.limit,
            params.user_id,
        )
        results = await self.db.execute(FUZZY_QUERY, query_params)

        return {
            "query_type": "FUZZY",
            "query_text": params.query_text,
            "threshold": params.threshold,
            "results": results,
            "count": len(results),
        }

    async def _execute_search(
        self, params: SearchParameters, tenant_id: str
    ) -> dict[str, Any]:
        """
        Execute SEARCH query via rem_search() PostgreSQL function.

        Validates:
        - Table exists in model registry
        - Field exists in model (or defaults to 'content')
        - Field has embeddings configured

        Delegates to: rem_search(query_embedding, table_name, field_name, ...)

        Args:
            params: SearchParameters with query text and table
            tenant_id: Tenant identifier

        Returns:
            Dict with semantically similar entities

        Raises:
            FieldNotFoundError: If field does not exist
            EmbeddingFieldNotFoundError: If field has no embeddings
            ContentFieldNotFoundError: If no 'content' field and field_name not specified
        """
        table_name = params.table_name
        field_name = params.field_name

        # Get model fields for validation
        available_fields = self._get_model_fields(table_name)
        embeddable_fields = self._get_embeddable_fields(table_name)

        # Default to 'content' if field_name not specified
        if field_name is None:
            if "content" in available_fields:
                field_name = "content"
            else:
                raise ContentFieldNotFoundError(
                    table_name or "UNKNOWN",
                    available_fields,
                )

        # Validate field exists
        if available_fields and field_name not in available_fields:
            raise FieldNotFoundError(
                table_name or "UNKNOWN",
                field_name,
                available_fields,
            )

        # Validate field has embeddings
        if embeddable_fields and field_name not in embeddable_fields:
            raise EmbeddingFieldNotFoundError(
                table_name or "UNKNOWN",
                field_name,
                embeddable_fields,
            )

        # Generate embedding for query text
        from ..embeddings.api import generate_embedding_async
        from .queries import SEARCH_QUERY, get_search_params

        query_embedding = await generate_embedding_async(
            text=params.query_text,
            model="text-embedding-3-small",
            provider=params.provider or "openai",
        )

        # Execute vector search via rem_search() PostgreSQL function
        query_params = get_search_params(
            query_embedding,
            table_name,
            field_name,
            tenant_id,
            params.provider or "openai",
            params.min_similarity or 0.7,
            params.limit or 10,
            params.user_id,
        )
        results = await self.db.execute(SEARCH_QUERY, query_params)

        return {
            "query_type": "SEARCH",
            "query_text": params.query_text,
            "table_name": table_name,
            "field_name": field_name,
            "results": results,
            "count": len(results),
        }

    async def _execute_sql(
        self, params: SQLParameters, tenant_id: str
    ) -> dict[str, Any]:
        """
        Execute SQL query via direct PostgresService.execute().

        Pushes SELECT queries down to Postgres for performance.

        Args:
            params: SQLParameters with table and WHERE clause
            tenant_id: Tenant identifier

        Returns:
            Query results
        """
        from .queries import build_sql_query

        # Build SQL query with tenant isolation
        query = build_sql_query(
            table_name=params.table_name,
            where_clause=params.where_clause or "1=1",
            tenant_id=tenant_id,
            limit=params.limit,
        )

        results = await self.db.execute(query, (tenant_id,))

        return {
            "query_type": "SQL",
            "table_name": params.table_name,
            "results": results,
            "count": len(results),
        }

    async def _execute_traverse(
        self, params: TraverseParameters, tenant_id: str
    ) -> dict[str, Any]:
        """
        Execute TRAVERSE query via rem_traverse() PostgreSQL function.

        Delegates to: rem_traverse(entity_key, tenant_id, max_depth, rel_type, user_id)

        Args:
            params: TraverseParameters with start key and depth
            tenant_id: Tenant identifier

        Returns:
            Dict with traversed entities and paths
        """
        from .queries import TRAVERSE_QUERY, get_traverse_params

        query_params = get_traverse_params(
            params.start_key,
            tenant_id,
            params.max_depth or 1,
            params.rel_type,
            params.user_id,
        )
        results = await self.db.execute(TRAVERSE_QUERY, query_params)

        return {
            "query_type": "TRAVERSE",
            "start_key": params.start_key,
            "max_depth": params.max_depth,
            "rel_type": params.rel_type,
            "results": results,
            "count": len(results),
        }

    async def ask_rem(
        self, natural_query: str, tenant_id: str, llm_model: str | None = None
    ) -> dict[str, Any]:
        """
        Natural language to REM query conversion.

        Uses REM Query Agent (LLM) to convert user questions into REM queries.

        Args:
            natural_query: Natural language question
            tenant_id: Tenant identifier
            llm_model: Optional LLM model override

        Returns:
            Dict with:
            - query_output: REMQueryOutput from agent
            - results: Executed query results (if confidence >= 0.7)
            - multi_step_results: Results for each step (if multi-step query)
        """
        from ...agentic.agents import ask_rem as agent_ask_rem

        # Get query from REM Query Agent
        query_output = await agent_ask_rem(
            natural_query=natural_query,
            llm_model=llm_model,
        )

        result = {
            "query_output": query_output.model_dump(),
            "natural_query": natural_query,
        }

        # Execute query if confidence is high enough
        if query_output.confidence >= 0.7:
            if query_output.multi_step:
                # Execute multi-step query plan
                multi_step_results = []
                for step in query_output.multi_step:
                    step_query = RemQuery(
                        query_type=QueryType(step["query_type"]),
                        parameters=step["parameters"],
                        tenant_id=tenant_id,
                    )
                    step_result = await self.execute_query(step_query)
                    multi_step_results.append({
                        "description": step.get("description"),
                        "results": step_result,
                    })
                result["multi_step_results"] = multi_step_results
            else:
                # Execute single query
                query = RemQuery(
                    query_type=query_output.query_type,
                    parameters=query_output.parameters,
                    tenant_id=tenant_id,
                )
                result["results"] = await self.execute_query(query)
        else:
            # Low confidence - don't auto-execute
            result["warning"] = "Low confidence score. Review query_output.reasoning before executing."

        return result
