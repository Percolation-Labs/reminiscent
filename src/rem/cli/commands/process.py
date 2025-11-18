"""File processing CLI commands."""

import json
import sys

import click
from loguru import logger

from rem.services.content import ContentService


def register_commands(group: click.Group):
    """Register process commands."""
    group.add_command(process_uri)


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
    Process a file URI and extract content.

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
