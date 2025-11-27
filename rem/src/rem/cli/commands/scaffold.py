"""
Scaffold command - generate project structure for REM-based applications.

TODO: Implement this command to generate:
- my_app/main.py (entry point with create_app)
- my_app/models.py (example CoreModel subclass)
- my_app/routers/ (example FastAPI router)
- schemas/agents/ (example agent schema)
- schemas/evaluators/ (example evaluator)
- sql/migrations/ (empty migrations directory)
- pyproject.toml (with remdb dependency)
- README.md (basic usage instructions)

Usage:
    rem scaffold my-app
    rem scaffold my-app --with-examples  # Include example models/routers/tools
"""

import click


@click.command()
@click.argument("name")
@click.option("--with-examples", is_flag=True, help="Include example code")
def scaffold(name: str, with_examples: bool) -> None:
    """
    Generate a new REM-based project structure.

    NAME is the project directory name to create.
    """
    click.echo(f"TODO: Scaffold command not yet implemented")
    click.echo(f"Would create project: {name}")
    click.echo(f"With examples: {with_examples}")
    click.echo()
    click.echo("For now, manually create this structure:")
    click.echo(f"""
{name}/
├── {name.replace('-', '_')}/
│   ├── main.py           # Entry point (create_app + extensions)
│   ├── models.py         # Custom models (inherit CoreModel)
│   └── routers/          # Custom FastAPI routers
├── schemas/
│   ├── agents/           # Custom agent YAML schemas
│   └── evaluators/       # Custom evaluator schemas
├── sql/migrations/       # Custom SQL migrations
└── pyproject.toml
""")
