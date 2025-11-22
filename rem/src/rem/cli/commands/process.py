"""File processing CLI commands."""

import json
import sys
from typing import Optional

import click
from loguru import logger

from rem.services.content import ContentService


def register_commands(group: click.Group):
    """Register process commands."""
    group.add_command(process_uri)
    group.add_command(process_files)


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
@click.option("--tenant-id", required=True, help="Tenant ID")
@click.option("--user-id", help="Filter by user ID")
@click.option("--status", type=click.Choice(["pending", "processing", "completed", "failed"]), help="Filter by status")
@click.option("--extractor", help="Run files through custom extractor (e.g., cv-parser-v1)")
@click.option("--limit", type=int, help="Max files to process")
@click.option("--provider", help="Optional LLM provider override")
@click.option("--model", help="Optional model override")
def process_files(
    tenant_id: str,
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
        rem process files --tenant-id acme-corp --status completed

        \b
        # Extract from CV files
        rem process files --tenant-id acme-corp --extractor cv-parser-v1 --limit 10

        \b
        # Extract with provider override
        rem process files --tenant-id acme-corp --extractor contract-analyzer-v1 \\
            --provider anthropic --model claude-sonnet-4-5
    """
    logger.warning("Not implemented yet")
    logger.info(f"Would process files for tenant: {tenant_id}")

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
