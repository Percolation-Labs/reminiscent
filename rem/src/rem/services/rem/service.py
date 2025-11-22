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

from .parser import RemQueryParser
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

        Supports both single key and list of keys. When given a list, executes
        multiple LOOKUP queries and aggregates results.

        Delegates to: rem_lookup(entity_key, tenant_id, user_id)

        Args:
            params: LookupParameters with entity key (str or list[str])
            tenant_id: Tenant identifier

        Returns:
            Dict with entity metadata from KV_STORE
        """
        from .queries import LOOKUP_QUERY, get_lookup_params

        # Handle both single key and list of keys
        keys = params.key if isinstance(params.key, list) else [params.key]

        all_results = []
        for key in keys:
            query_params = get_lookup_params(key, tenant_id, params.user_id)
            results = await self.db.execute(LOOKUP_QUERY, query_params)
            all_results.extend(results)

        return {
            "query_type": "LOOKUP",
            "keys": keys,  # Return list for consistency
            "results": all_results,
            "count": len(all_results),
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
        from ...settings import settings
        from ..embeddings.api import generate_embedding_async
        from .queries import SEARCH_QUERY, get_search_params

        query_embedding = await generate_embedding_async(
            text=params.query_text,
            model=settings.llm.embedding_model,
            provider=params.provider or settings.llm.embedding_provider,
        )

        # Execute vector search via rem_search() PostgreSQL function
        query_params = get_search_params(
            query_embedding,
            table_name,
            field_name,
            tenant_id,
            params.provider or settings.llm.embedding_provider,
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

        Delegates to: rem_traverse(entity_key, tenant_id, max_depth, rel_types, user_id)

        Args:
            params: TraverseParameters with start key and depth
            tenant_id: Tenant identifier

        Returns:
            Dict with traversed entities and paths
        """
        from .queries import TRAVERSE_QUERY, get_traverse_params

        # Handle edge_types wildcards
        rel_types = params.edge_types
        if not rel_types or "*" in rel_types:
            rel_types = None

        query_params = get_traverse_params(
            params.initial_query,
            tenant_id,
            params.max_depth or 1,
            rel_types,
            None, # user_id not yet in TraverseParameters, passing None
        )
        results = await self.db.execute(TRAVERSE_QUERY, query_params)

        return {
            "query_type": "TRAVERSE",
            "start_key": params.initial_query,
            "max_depth": params.max_depth,
            "edge_types": params.edge_types,
            "results": results,
            "count": len(results),
        }

    def _parse_query_string(self, query_string: str) -> tuple[QueryType, dict[str, Any]]:
        """
        Parse REM query string using the robust RemQueryParser.
        """
        parser = RemQueryParser()
        return parser.parse(query_string)

    async def ask_rem(
        self, natural_query: str, tenant_id: str, llm_model: str | None = None, plan_mode: bool = False
    ) -> dict[str, Any]:
        """
        Natural language to REM query conversion with optional execution.

        Uses REM Query Agent (Cerebras Qwen) to convert user questions into REM query strings.
        Auto-executes if confidence >= 0.7, otherwise returns query for review.

        Args:
            natural_query: Natural language question
            tenant_id: Tenant identifier
            llm_model: Optional LLM model override
            plan_mode: If True, only shows generated query without executing

        Returns:
            Dict with:
            - query: Generated REM query string (e.g., "LOOKUP sarah-chen")
            - confidence: Confidence score (0.0-1.0)
            - reasoning: Explanation (only if confidence < 0.7)
            - results: Executed query results (if confidence >= 0.7 and not plan_mode)
            - warning: Low confidence warning (if confidence < 0.7)

        Example:
            >>> result = await rem_service.ask_rem("Who is Sarah Chen?", tenant_id="acme")
            >>> print(result["query"])
            "LOOKUP sarah-chen"
            >>> print(result["results"]["count"])
            1

            >>> # Plan mode - show query without executing
            >>> result = await rem_service.ask_rem("Find Sarah", tenant_id="acme", plan_mode=True)
            >>> print(result["query"])
            "LOOKUP sarah"
            >>> print("results" in result)
            False
        """
        from ...agentic.agents import ask_rem as agent_ask_rem
        from ...models.core import RemQuery

        # Get query string from REM Query Agent
        query_output = await agent_ask_rem(
            natural_query=natural_query,
            llm_model=llm_model,
        )

        result = {
            "query": query_output.query,
            "confidence": query_output.confidence,
            "reasoning": query_output.reasoning or "",
            "natural_query": natural_query,
        }

        # Execute query if confidence is high enough and not in plan mode
        if query_output.confidence >= 0.7 and not plan_mode:
            try:
                # Parse query string
                query_type, parameters = self._parse_query_string(query_output.query)

                # Create RemQuery and execute
                rem_query = RemQuery(
                    query_type=query_type,
                    parameters=parameters,
                    tenant_id=tenant_id,
                )

                result["results"] = await self.execute_query(rem_query)

            except Exception as e:
                result["warning"] = f"Failed to parse or execute query: {str(e)}"
                logger.error(f"Query execution failed: {e}", exc_info=True)

        elif plan_mode:
            result["plan_mode"] = True
        else:
            # Low confidence - don't auto-execute
            result["warning"] = "Low confidence score. Review reasoning before executing."

        return result
