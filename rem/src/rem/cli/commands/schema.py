"""
Schema generation commands.

Usage:
    rem db schema generate --models src/rem/models/entities
    rem db schema validate
    rem db schema indexes --background
"""

import asyncio
from pathlib import Path

import click
from loguru import logger

from ...settings import settings
from ...services.postgres.schema_generator import SchemaGenerator


@click.command()
@click.option(
    "--models",
    "-m",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Directory containing Pydantic models",
)
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
    help=f"Base output directory (default: {settings.sql_dir}/migrations)",
)
def generate(models: Path, output: Path, output_dir: Path | None):
    """
    Generate database schema from Pydantic models.

    Scans the specified directory for Pydantic models and generates:
    - CREATE TABLE statements
    - Embeddings tables (embeddings_<table>)
    - KV_STORE triggers for cache maintenance
    - Indexes (foreground only)

    Output is written to src/rem/sql/migrations/002_install_models.sql by default.

    Example:
        rem db schema generate --models src/rem/models/entities

    This creates:
    - src/rem/sql/migrations/002_install_models.sql - Entity tables and triggers
    - src/rem/sql/background_indexes.sql - HNSW indexes (apply after data load)

    After generation, apply with:
        rem db migrate
    """
    click.echo(f"Discovering models in {models}")

    # Default to migrations directory
    actual_output_dir = output_dir or Path(settings.sql_dir) / "migrations"
    generator = SchemaGenerator(output_dir=actual_output_dir)

    # Generate schema
    try:
        schema_sql = asyncio.run(generator.generate_from_directory(models, output_file=output.name))

        click.echo(f"✓ Schema generated: {len(generator.schemas)} tables")
        click.echo(f"✓ Written to: {actual_output_dir / output.name}")

        # Generate background indexes in parent sql dir
        background_indexes = generator.generate_background_indexes()
        if background_indexes:
            bg_file = Path(settings.sql_dir) / "background_indexes.sql"
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
@click.option(
    "--models",
    "-m",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Directory containing Pydantic models",
)
def validate(models: Path):
    """
    Validate Pydantic models for schema generation.

    Checks:
    - Models can be loaded
    - Models have suitable entity_key fields
    - Fields with embeddings are properly configured
    """
    click.echo(f"Validating models in {models}")

    generator = SchemaGenerator()
    discovered = generator.discover_models(models)

    if not discovered:
        click.echo("✗ No models found", err=True)
        raise click.Abort()

    click.echo(f"✓ Discovered {len(discovered)} models")

    errors: list[str] = []
    warnings: list[str] = []

    for model_name, model in discovered.items():
        table_name = generator.infer_table_name(model)
        entity_key = generator.infer_entity_key_field(model)

        # Check for entity_key
        if entity_key == "id":
            warnings.append(f"{model_name}: No natural key field, using 'id'")

        # Check for embeddable fields
        # TODO: Implement should_embed_field check
        embeddable: list[str] = []  # Placeholder - needs implementation

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
    help=f"Output file for background indexes (default: {settings.sql_dir}/background_indexes.sql)",
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
