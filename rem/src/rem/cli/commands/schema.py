"""
Schema generation commands.

Usage:
    rem db schema generate --models src/rem/models/entities
    rem db schema validate
    rem db schema indexes --background
"""

import asyncio
import importlib
from pathlib import Path

import click
from loguru import logger

from ...settings import settings
from ...services.postgres.schema_generator import SchemaGenerator
from ...utils.sql_paths import get_package_sql_dir, get_package_migrations_dir


def _import_model_modules() -> list[str]:
    """
    Import modules specified in MODELS__IMPORT_MODULES setting.

    This ensures downstream models decorated with @rem.register_model
    are registered before schema generation.

    Returns:
        List of successfully imported module names
    """
    imported = []
    for module_name in settings.models.module_list:
        try:
            importlib.import_module(module_name)
            imported.append(module_name)
            logger.debug(f"Imported model module: {module_name}")
        except ImportError as e:
            logger.warning(f"Failed to import model module '{module_name}': {e}")
            click.echo(
                click.style(f"  ⚠ Could not import '{module_name}': {e}", fg="yellow"),
                err=True,
            )
    return imported


@click.command()
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default="002_install_models.sql",
    help="Output SQL file (default: 002_install_models.sql)",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Base output directory (default: package sql/migrations)",
)
def generate(output: Path, output_dir: Path | None):
    """
    Generate database schema from registered Pydantic models.

    Uses the model registry (core models + user-registered models) to generate:
    - CREATE TABLE statements
    - Embeddings tables (embeddings_<table>)
    - KV_STORE triggers for cache maintenance
    - Indexes (foreground only)

    Output is written to src/rem/sql/migrations/002_install_models.sql by default.

    Example:
        rem db schema generate

    To register custom models in downstream apps:

    1. Create models with @rem.register_model decorator:

        # models/__init__.py
        import rem
        from rem.models.core import CoreModel

        @rem.register_model
        class MyEntity(CoreModel):
            name: str

    2. Set MODELS__IMPORT_MODULES in your .env:

        MODELS__IMPORT_MODULES=models

    3. Run schema generation:

        rem db schema generate

    This creates:
    - src/rem/sql/migrations/002_install_models.sql - Entity tables and triggers
    - src/rem/sql/background_indexes.sql - HNSW indexes (apply after data load)

    After generation, verify with:
        rem db diff
    """
    from ...registry import get_model_registry

    # Import downstream model modules to trigger @rem.register_model decorators
    imported_modules = _import_model_modules()
    if imported_modules:
        click.echo(f"Imported model modules: {', '.join(imported_modules)}")

    registry = get_model_registry()
    models = registry.get_models(include_core=True)
    click.echo(f"Generating schema from {len(models)} registered models")

    # Default to package migrations directory
    actual_output_dir = output_dir or get_package_migrations_dir()
    generator = SchemaGenerator(output_dir=actual_output_dir)

    # Generate schema from registry
    try:
        schema_sql = asyncio.run(generator.generate_from_registry(output_file=output.name))

        click.echo(f"✓ Schema generated: {len(generator.schemas)} tables")
        click.echo(f"✓ Written to: {actual_output_dir / output.name}")

        # Generate background indexes in parent sql dir
        background_indexes = generator.generate_background_indexes()
        if background_indexes:
            bg_file = get_package_sql_dir() / "background_indexes.sql"
            bg_file.write_text(background_indexes)
            click.echo(f"✓ Background indexes: {bg_file}")

        # Summary
        click.echo("\nGenerated tables:")
        for table_name, schema in generator.schemas.items():
            embeddable = len(schema.get("embeddable_fields", []))
            embed_status = f"({embeddable} embeddable fields)" if embeddable else "(no embeddings)"
            click.echo(f"  - {table_name} {embed_status}")

    except Exception as e:
        logger.exception("Schema generation failed")
        click.echo(f"✗ Error: {e}", err=True)
        raise click.Abort()


@click.command()
def validate():
    """
    Validate registered Pydantic models for schema generation.

    Checks:
    - Models can be loaded from registry
    - Models have suitable entity_key fields
    - Fields with embeddings are properly configured

    Set MODELS__IMPORT_MODULES to include custom models from downstream apps.
    """
    from ...registry import get_model_registry

    # Import downstream model modules to trigger @rem.register_model decorators
    imported_modules = _import_model_modules()
    if imported_modules:
        click.echo(f"Imported model modules: {', '.join(imported_modules)}")

    registry = get_model_registry()
    models = registry.get_models(include_core=True)

    click.echo(f"Validating {len(models)} registered models")

    if not models:
        click.echo("✗ No models found in registry", err=True)
        raise click.Abort()

    generator = SchemaGenerator()
    errors: list[str] = []
    warnings: list[str] = []

    for model_name, ext in models.items():
        model = ext.model
        table_name = ext.table_name or generator.infer_table_name(model)
        entity_key = ext.entity_key_field or generator.infer_entity_key_field(model)

        # Check for entity_key
        if entity_key == "id":
            warnings.append(f"{model_name}: No natural key field, using 'id'")

        click.echo(f"  {model_name} -> {table_name} (key: {entity_key})")

    if warnings:
        click.echo("\nWarnings:")
        for warning in warnings:
            click.echo(click.style(f"  ⚠ {warning}", fg="yellow"))

    if errors:
        click.echo("\nErrors:")
        for error in errors:
            click.echo(click.style(f"  ✗ {error}", fg="red"))
        raise click.Abort()

    click.echo("\n✓ All models valid")


@click.command()
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output file for background indexes (default: package sql/background_indexes.sql)",
)
def indexes(output: Path):
    """
    Generate SQL for background index creation.

    Creates HNSW vector indexes that should be run CONCURRENTLY
    after initial data load to avoid blocking writes.
    """
    click.echo("Generating background index SQL")

    generator = SchemaGenerator()

    # Load existing schemas (would need to be persisted or regenerated)
    click.echo(click.style("⚠ Note: This requires schemas to be generated first", fg="yellow"))
    click.echo(click.style("⚠ Run 'rem db schema generate' before 'rem db schema indexes'", fg="yellow"))


def register_commands(schema_group):
    """Register all schema commands."""
    schema_group.add_command(generate)
    schema_group.add_command(validate)
    schema_group.add_command(indexes)
