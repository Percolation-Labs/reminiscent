# Alembic Migrations for REM

This directory contains Alembic configuration for REM database migrations.

## Overview

REM uses **Alembic** to generate SQL diffs between Pydantic models (source of truth) and target databases. This enables:

- Schema comparison across environments (dev, staging, prod)
- Controlled migration generation and review
- Version-controlled SQL migration files
- Non-destructive schema updates

## Directory Structure

```
alembic/
├── README.md           # This file
├── env.py             # Alembic environment configuration (integrates with REM settings)
├── script.py.mako     # Template for generating migration files
└── versions/          # Generated migration files (auto-created)
```

## Configuration

**Alembic Config:** `../alembic.ini` (package root)

The `env.py` file:
- Loads database URL from REM settings (`settings.postgres`)
- Imports all Pydantic models from `rem.models.entities`
- Builds SQLAlchemy metadata for comparison
- Supports both online and offline migration modes

## Usage

### Generate Migration Diff

```bash
# Show what would change (dry-run)
rem db diff --plan

# Generate SQL diff file
rem db diff -o migration.sql

# Compare against specific database
rem db diff --db production_db -o prod-migration.sql
```

### Review and Apply

```bash
# Review generated SQL
cat migration.sql

# Dry-run (show SQL without executing)
rem db apply migration.sql --dry-run

# Apply migration
rem db apply migration.sql
```

## Workflow

1. **Modify Models**: Update Pydantic models in `src/rem/models/entities/`
2. **Plan**: Run `rem db diff --plan` to see changes
3. **Generate**: Run `rem db diff -o migration.sql` to generate SQL
4. **Review**: Inspect generated SQL, edit if needed
5. **Apply**: Run `rem db apply migration.sql` to apply changes

## Important Notes

- **Pydantic Models = Source of Truth**: Models define schema, Alembic generates diffs
- **Human-in-the-Loop**: Always review generated SQL before applying
- **Non-Destructive**: Migrations are files, not auto-applied
- **Target Flexibility**: Can diff against any database using `--db` flag

## Integration with REM

Alembic integrates with REM's existing schema generation:

- **Existing**: `rem db schema generate` - Generates full schema from scratch
- **New**: `rem db diff` - Generates incremental changes for existing databases

Use `rem db schema generate` for initial setup, `rem db diff` for updates.

## Troubleshooting

**Error: "Alembic config not found"**
- Ensure you're in the REM package directory
- Check that `alembic.ini` exists at package root

**Error: "Could not import models"**
- Verify all models in `rem/models/entities/` are valid
- Check for import errors in model files

**Empty Migration Generated**
- Models match database exactly
- Run `rem db diff --plan` to verify

## See Also

- `rem db diff --help` - Full command options
- `rem db apply --help` - Apply command options
- [CLAUDE.md](../CLAUDE.md) - Database Migration Pattern section
