"""
REM Extension Registry - Register custom models and schema paths.

This module provides registration for downstream applications extending REM:
1. Models - for database schema generation
2. Schema paths - for agent/evaluator schema discovery

Usage:
    import rem
    from rem.models.core import CoreModel

    # Register custom models
    @rem.register_model
    class CustomEntity(CoreModel):
        name: str
        custom_field: str

    # Or register multiple at once
    rem.register_models(ModelA, ModelB, ModelC)

    # Register schema search paths
    rem.register_schema_path("/app/custom-agents")
    rem.register_schema_paths("/app/agents", "/app/evaluators")

    # Then:
    # - Schema generation includes your models: rem db schema generate
    # - Schema loading finds your custom agents: load_agent_schema("my-agent")
"""

from dataclasses import dataclass
from typing import Callable

from loguru import logger
from pydantic import BaseModel


@dataclass
class ModelExtension:
    """Container for Pydantic model extension."""

    model: type[BaseModel]
    table_name: str | None = None  # Optional: override inferred table name
    entity_key_field: str | None = None  # Optional: override inferred entity key


class ModelRegistry:
    """
    Registry for Pydantic models used in schema generation.

    Models registered here are discovered by SchemaGenerator alongside
    REM's core models.
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelExtension] = {}
        self._core_models_registered: bool = False

    def clear(self) -> None:
        """Clear all registered models. Useful for testing."""
        self._models.clear()
        self._core_models_registered = False
        logger.debug("Model registry cleared")

    def register(
        self,
        model: type[BaseModel],
        table_name: str | None = None,
        entity_key_field: str | None = None,
    ) -> type[BaseModel]:
        """
        Register a Pydantic model for database schema generation.

        Args:
            model: Pydantic model class (should inherit from CoreModel)
            table_name: Optional table name override (inferred from class name if not provided)
            entity_key_field: Optional entity key field override (inferred if not provided)

        Returns:
            The model class (allows use as decorator)

        Example:
            import rem
            from rem.models.core import CoreModel

            @rem.register_model
            class CustomEntity(CoreModel):
                name: str
                custom_field: str

            # Or with options:
            rem.register_model(CustomEntity, table_name="custom_entities")
        """
        model_name = model.__name__
        if model_name in self._models:
            logger.warning(f"Model {model_name} already registered, overwriting")

        self._models[model_name] = ModelExtension(
            model=model,
            table_name=table_name,
            entity_key_field=entity_key_field,
        )
        logger.debug(f"Registered model: {model_name}")
        return model

    def register_many(self, *models: type[BaseModel]) -> None:
        """
        Register multiple models at once.

        Example:
            import rem
            rem.register_models(ModelA, ModelB, ModelC)
        """
        for model in models:
            self.register(model)

    def register_core_models(self) -> None:
        """
        Register REM's built-in core models.

        Called automatically by schema generator if not already done.
        """
        if self._core_models_registered:
            return

        from .models.entities import (
            Feedback,
            File,
            ImageResource,
            Message,
            Moment,
            Ontology,
            OntologyConfig,
            Resource,
            Schema,
            Session,
            SharedSession,
            User,
        )

        core_models = [
            Feedback,
            File,
            ImageResource,
            Message,
            Moment,
            Ontology,
            OntologyConfig,
            Resource,
            Schema,
            Session,
            SharedSession,
            User,
        ]

        for model in core_models:
            if model.__name__ not in self._models:
                self.register(model)

        self._core_models_registered = True
        logger.debug(f"Registered {len(core_models)} core models")

    def get_models(self, include_core: bool = True) -> dict[str, ModelExtension]:
        """
        Get all registered models.

        Args:
            include_core: If True, ensures core models are registered first

        Returns:
            Dict mapping model name to ModelExtension
        """
        if include_core:
            self.register_core_models()
        return self._models.copy()

    def get_model_classes(self, include_core: bool = True) -> dict[str, type[BaseModel]]:
        """
        Get all registered model classes (without extension metadata).

        Args:
            include_core: If True, ensures core models are registered first

        Returns:
            Dict mapping model name to model class
        """
        models = self.get_models(include_core)
        return {name: ext.model for name, ext in models.items()}


# =============================================================================
# SCHEMA PATH REGISTRY
# =============================================================================


class SchemaPathRegistry:
    """
    Registry for custom schema search paths.

    Paths registered here are searched BEFORE built-in package schemas
    when loading agent/evaluator schemas.

    Search order:
    1. Exact path (if file exists)
    2. Paths from this registry (in registration order)
    3. Paths from SCHEMA__PATHS env var
    4. Built-in package schemas
    5. Database LOOKUP
    """

    def __init__(self) -> None:
        self._paths: list[str] = []

    def clear(self) -> None:
        """Clear all registered paths. Useful for testing."""
        self._paths.clear()
        logger.debug("Schema path registry cleared")

    def register(self, path: str) -> None:
        """
        Register a schema search path.

        Args:
            path: Directory path to search for schemas

        Example:
            import rem
            rem.register_schema_path("/app/custom-agents")
        """
        if path not in self._paths:
            self._paths.append(path)
            logger.debug(f"Registered schema path: {path}")

    def register_many(self, *paths: str) -> None:
        """
        Register multiple schema paths at once.

        Example:
            import rem
            rem.register_schema_paths("/app/agents", "/app/evaluators")
        """
        for path in paths:
            self.register(path)

    def get_paths(self) -> list[str]:
        """
        Get all registered paths (registry + settings).

        Returns paths in search order:
        1. Programmatically registered paths (this registry)
        2. Paths from SCHEMA__PATHS environment variable

        Returns:
            List of directory paths to search
        """
        from .settings import settings

        # Combine registry paths with settings paths
        all_paths = self._paths.copy()

        # Add paths from settings (SCHEMA__PATHS env var)
        for path in settings.schema_search.path_list:
            if path not in all_paths:
                all_paths.append(path)

        return all_paths


# =============================================================================
# MODULE-LEVEL SINGLETONS
# =============================================================================

_model_registry = ModelRegistry()
_schema_path_registry = SchemaPathRegistry()


def register_model(
    model: type[BaseModel] | None = None,
    *,
    table_name: str | None = None,
    entity_key_field: str | None = None,
) -> type[BaseModel] | Callable[[type[BaseModel]], type[BaseModel]]:
    """
    Register a Pydantic model for database schema generation.

    Can be used as a decorator or called directly.

    Example:
        import rem

        @rem.register_model
        class CustomEntity(CoreModel):
            name: str

        # Or with options:
        @rem.register_model(table_name="custom_table")
        class AnotherEntity(CoreModel):
            name: str

        # Or direct call:
        rem.register_model(MyModel, table_name="my_table")
    """
    def decorator(m: type[BaseModel]) -> type[BaseModel]:
        return _model_registry.register(m, table_name, entity_key_field)

    if model is not None:
        return decorator(model)
    return decorator


def register_models(*models: type[BaseModel]) -> None:
    """Register multiple models at once."""
    _model_registry.register_many(*models)


def get_model_registry() -> ModelRegistry:
    """Get the global model registry instance."""
    return _model_registry


def clear_model_registry() -> None:
    """Clear all model registrations. Useful for testing."""
    _model_registry.clear()


# =============================================================================
# SCHEMA PATH FUNCTIONS
# =============================================================================


def register_schema_path(path: str) -> None:
    """
    Register a schema search path.

    Paths registered here are searched BEFORE built-in package schemas.

    Example:
        import rem
        rem.register_schema_path("/app/custom-agents")

        # Now load_agent_schema("my-agent") will find /app/custom-agents/my-agent.yaml
    """
    _schema_path_registry.register(path)


def register_schema_paths(*paths: str) -> None:
    """
    Register multiple schema paths at once.

    Example:
        import rem
        rem.register_schema_paths("/app/agents", "/app/evaluators")
    """
    _schema_path_registry.register_many(*paths)


def get_schema_path_registry() -> SchemaPathRegistry:
    """Get the global schema path registry instance."""
    return _schema_path_registry


def get_schema_paths() -> list[str]:
    """
    Get all registered schema paths (registry + SCHEMA__PATHS env var).

    Returns:
        List of directory paths to search for schemas
    """
    return _schema_path_registry.get_paths()


def clear_schema_path_registry() -> None:
    """Clear all schema path registrations. Useful for testing."""
    _schema_path_registry.clear()
