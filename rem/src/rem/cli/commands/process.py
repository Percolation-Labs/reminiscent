"""File processing CLI commands."""

import json
import sys
from typing import Optional

import click
from loguru import logger

from rem.services.content import ContentService


@click.command(name="ingest")
@click.argument("path", type=click.Path(exists=True))
@click.option("--table", "-t", default=None, help="Target table (e.g., ontologies, resources). Auto-detected for schemas.")
@click.option("--make-private", is_flag=True, help="Make data private to a specific user. RARELY NEEDED - most data should be public/shared.")
@click.option("--user-id", default=None, help="User ID for private data. REQUIRES --make-private flag.")
@click.option("--category", help="Optional file category")
@click.option("--tags", help="Optional comma-separated tags")
@click.option("--pattern", "-p", default="**/*.md", help="Glob pattern for directory ingestion (default: **/*.md)")
@click.option("--dry-run", is_flag=True, help="Show what would be ingested without making changes")
def process_ingest(
    path: str,
    table: str | None,
    make_private: bool,
    user_id: str | None,
    category: str | None,
    tags: str | None,
    pattern: str,
    dry_run: bool,
):
    """
    Ingest files into REM (storage + parsing + embedding).

    Supports both single files and directories. For directories, recursively
    processes files matching the pattern (default: **/*.md).

    **IMPORTANT: Data is PUBLIC by default.** This is the correct behavior for
    shared knowledge bases (ontologies, procedures, reference data). Private
    user-scoped data is rarely needed and requires explicit --make-private flag.

    Target table is auto-detected for schemas (agent.yaml → schemas table).
    Use --table to explicitly set the target (e.g., ontologies for clinical knowledge).

    Examples:
        rem process ingest sample.pdf
        rem process ingest contract.docx --category legal --tags contract,2023
        rem process ingest agent.yaml  # Auto-detects kind=agent, saves to schemas table

        # Directory ingestion into ontologies table (PUBLIC - no user-id needed)
        rem process ingest ontology/procedures/scid-5/ --table ontologies
        rem process ingest ontology/ --table ontologies --pattern "**/*.md"

        # Preview what would be ingested
        rem process ingest ontology/ --table ontologies --dry-run

        # RARE: Private user-scoped data (requires --make-private)
        rem process ingest private-notes.md --make-private --user-id user-123
    """
    import asyncio

    # Validate: user_id requires --make-private flag
    if user_id and not make_private:
        raise click.UsageError(
            "Setting --user-id requires the --make-private flag.\n\n"
            "Data should be PUBLIC by default (no user-id). Private user-scoped data\n"
            "is rarely needed - only use --make-private for truly personal content.\n\n"
            "Example: rem process ingest file.md --make-private --user-id user-123"
        )

    # If --make-private is set, user_id is required
    if make_private and not user_id:
        raise click.UsageError(
            "--make-private requires --user-id to specify which user owns the data.\n\n"
            "Example: rem process ingest file.md --make-private --user-id user-123"
        )

    # Clear user_id if not making private (ensure None for public data)
    effective_user_id = user_id if make_private else None
    from pathlib import Path
    from ...services.content import ContentService

    async def _ingest():
        from rem.services.postgres import get_postgres_service
        from rem.services.postgres.repository import Repository
        from rem.models.entities import File, Resource, Ontology

        input_path = Path(path)
        tag_list = tags.split(",") if tags else None

        # Collect files to process
        if input_path.is_dir():
            files_to_process = list(input_path.glob(pattern))
            if not files_to_process:
                logger.error(f"No files matching '{pattern}' found in {input_path}")
                sys.exit(1)
            logger.info(f"Found {len(files_to_process)} files matching '{pattern}'")
        else:
            files_to_process = [input_path]

        # Dry run: just show what would be processed
        if dry_run:
            logger.info("DRY RUN - Would ingest:")
            for f in files_to_process[:20]:
                entity_key = f.stem  # filename without extension
                logger.info(f"  {f} → {table or 'auto-detect'} (key: {entity_key})")
            if len(files_to_process) > 20:
                logger.info(f"  ... and {len(files_to_process) - 20} more files")
            return

        db = get_postgres_service()
        if not db:
            raise RuntimeError("PostgreSQL service not available")
        await db.connect()

        try:
            # Direct table ingestion (ontologies, etc.)
            if table:
                await _ingest_to_table(
                    db=db,
                    files=files_to_process,
                    table_name=table,
                    user_id=effective_user_id,
                    category=category,
                    tag_list=tag_list,
                )
            else:
                # Standard file ingestion via ContentService
                file_repo = Repository(File, "files", db=db)
                resource_repo = Repository(Resource, "resources", db=db)
                service = ContentService(file_repo=file_repo, resource_repo=resource_repo)

                for file_path in files_to_process:
                    scope_msg = f"user: {effective_user_id}" if effective_user_id else "public"
                    logger.info(f"Ingesting: {file_path} ({scope_msg})")

                    result = await service.ingest_file(
                        file_uri=str(file_path),
                        user_id=effective_user_id,
                        category=category,
                        tags=tag_list,
                        is_local_server=True,
                    )

                    # Handle schema ingestion (agents/evaluators)
                    if result.get("schema_name"):
                        logger.success(f"Schema: {result['schema_name']} (kind={result.get('kind', 'agent')})")
                    elif result.get("processing_status") == "completed":
                        logger.success(f"File: {result['file_name']} ({result['resources_created']} resources)")
                    else:
                        logger.error(f"Failed: {result.get('message', 'Unknown error')}")

        except Exception as e:
            logger.error(f"Error during ingestion: {e}")
            sys.exit(1)
        finally:
            # Wait for embedding worker to finish
            from rem.services.embeddings.worker import get_global_embedding_worker
            try:
                worker = get_global_embedding_worker()
                if worker and worker.running and not worker.task_queue.empty():
                    logger.info(f"Waiting for {worker.task_queue.qsize()} embedding tasks...")
                    await worker.stop()
            except RuntimeError:
                pass

            await db.disconnect()

    async def _ingest_to_table(db, files, table_name, user_id, category, tag_list):
        """Direct ingestion of files to a specific table (ontologies, etc.)."""
        from rem.services.postgres.repository import Repository
        from rem import get_model_registry
        from rem.utils.model_helpers import get_table_name

        # Get model class for table
        registry = get_model_registry()
        registry.register_core_models()
        model_class = None
        for model in registry.get_model_classes().values():
            if get_table_name(model) == table_name:
                model_class = model
                break

        if not model_class:
            logger.error(f"Unknown table: {table_name}")
            sys.exit(1)

        repo = Repository(model_class, table_name, db=db)
        processed = 0
        failed = 0

        for file_path in files:
            try:
                # Read file content
                content = file_path.read_text(encoding="utf-8")

                # Generate entity key from filename
                # Special case: README files use parent directory as section name
                if file_path.stem.lower() == "readme":
                    # Use parent directory name, e.g., "drugs" for drugs/README.md
                    # For nested paths like disorders/anxiety/README.md -> "anxiety"
                    entity_key = file_path.parent.name
                else:
                    entity_key = file_path.stem  # filename without extension

                # Build entity based on table
                entity_data = {
                    "name": entity_key,
                    "content": content,
                    "tags": tag_list or [],
                }

                # Add optional fields
                if category:
                    entity_data["category"] = category

                # Scoping: user_id for private data, "public" for shared
                # tenant_id="public" is the default for shared knowledge bases
                entity_data["tenant_id"] = user_id or "public"
                entity_data["user_id"] = user_id  # None = public/shared

                # For ontologies, add URI
                if table_name == "ontologies":
                    entity_data["uri"] = f"file://{file_path.absolute()}"

                entity = model_class(**entity_data)
                await repo.upsert(entity, embeddable_fields=["content"], generate_embeddings=True)
                processed += 1
                logger.success(f"  ✓ {entity_key}")

            except Exception as e:
                failed += 1
                logger.error(f"  ✗ {file_path.name}: {e}")

        logger.info(f"Completed: {processed} succeeded, {failed} failed")

    asyncio.run(_ingest())

def register_commands(group: click.Group):
    """Register process commands."""
    group.add_command(process_uri)
    group.add_command(process_files)
    group.add_command(process_ingest)


@click.command(name="uri")
@click.argument("uri", type=str)
@click.option(
    "--output",
    "-o",
    type=click.Choice(["json", "text"]),
    default="json",
    help="Output format (json or text)",
)
@click.option(
    "--save",
    "-s",
    type=click.Path(),
    help="Save extracted content to file",
)
def process_uri(uri: str, output: str, save: str | None):
    """
    Process a file URI and extract content (READ-ONLY, no storage).

    **ARCHITECTURE NOTE - Code Path Comparison**:

    This CLI command provides READ-ONLY file processing:
    - Uses ContentService.process_uri() directly (no file storage, no DB writes)
    - Returns extracted content to stdout or saves to local file
    - No File entity created, no Resource chunks stored in database
    - Useful for testing file parsing without side effects

    Compare with MCP tool 'parse_and_ingest_file' (api/mcp_router/tools.py):
    - WRITES file to internal storage (~/.rem/fs/ or S3)
    - Creates File entity in database
    - Creates Resource chunks via ContentService.process_and_save()
    - Full ingestion pipeline for searchable content

    **SHARED CODE**: Both use ContentService for file parsing:
    - CLI: ContentService.process_uri() → extract only
    - MCP: ContentService.process_and_save() → extract + store chunks

    URI can be:
    - S3 URI: s3://bucket/key
    - Local file: /path/to/file.md or ./file.md

    Examples:

        \b
        # Process local markdown file
        rem process uri ./README.md

        \b
        # Process S3 file
        rem process uri s3://rem/uploads/document.md

        \b
        # Save to file
        rem process uri s3://rem/uploads/doc.md -s output.json

        \b
        # Text-only output
        rem process uri ./file.md -o text
    """
    try:
        service = ContentService()
        result = service.process_uri(uri)

        if output == "json":
            output_data = json.dumps(result, indent=2, default=str)
        else:
            # Text-only output
            output_data = result["content"]

        # Save to file or print to stdout
        if save:
            with open(save, "w") as f:
                f.write(output_data)
            logger.info(f"Saved to {save}")
        else:
            click.echo(output_data)

        sys.exit(0)

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        sys.exit(1)
    except RuntimeError as e:
        logger.error(f"Processing error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)


@click.command(name="files")
@click.option("--user-id", default=None, help="User ID (default: from settings)")
@click.option("--status", type=click.Choice(["pending", "processing", "completed", "failed"]), help="Filter by status")
@click.option("--extractor", help="Run files through custom extractor (e.g., cv-parser-v1)")
@click.option("--limit", type=int, help="Max files to process")
@click.option("--provider", help="Optional LLM provider override")
@click.option("--model", help="Optional model override")
def process_files(
    user_id: Optional[str],
    status: Optional[str],
    extractor: Optional[str],
    limit: Optional[int],
    provider: Optional[str],
    model: Optional[str],
):
    """Process files with optional custom extractor.

    Query files from the database and optionally run them through
    a custom extractor to extract domain-specific knowledge.

    Examples:

        \b
        # List completed files
        rem process files --status completed

        \b
        # Extract from CV files
        rem process files --extractor cv-parser-v1 --limit 10

        \b
        # Extract with provider override
        rem process files --extractor contract-analyzer-v1 \\
            --provider anthropic --model claude-sonnet-4-5
    """
    from ...settings import settings
    effective_user_id = user_id or settings.test.effective_user_id

    logger.warning("Not implemented yet")
    logger.info(f"Would process files for user: {effective_user_id}")

    if user_id:
        logger.info(f"Filter: user_id={user_id}")
    if status:
        logger.info(f"Filter: status={status}")
    if extractor:
        logger.info(f"Extractor: {extractor}")
    if limit:
        logger.info(f"Limit: {limit} files")
    if provider:
        logger.info(f"Provider override: {provider}")
    if model:
        logger.info(f"Model override: {model}")
