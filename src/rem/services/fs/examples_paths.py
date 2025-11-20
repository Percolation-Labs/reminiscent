"""
Examples demonstrating REM filesystem path conventions.

Run with:
    python -m rem.services.fs.examples_paths
"""

from datetime import datetime, date
from rem.services.fs import (
    FS,
    get_rem_home,
    get_base_uri,
    get_uploads_path,
    get_versioned_path,
    get_user_path,
    get_temp_path,
    ensure_dir_exists,
    join_path,
)


def example_basic_paths():
    """Demonstrate basic path generation."""
    print("=== Basic Paths ===\n")

    # REM home directory
    rem_home = get_rem_home()
    print(f"REM_HOME: {rem_home}")

    # Base URI (auto-detects local vs S3 based on environment)
    base_local = get_base_uri(use_s3=False)
    print(f"Base URI (local): {base_local}")

    base_s3 = get_base_uri(use_s3=True)
    print(f"Base URI (S3): {base_s3}")
    print()


def example_uploads_paths():
    """Demonstrate uploads path generation."""
    print("=== Uploads Paths ===\n")

    # System uploads (no user_id)
    system_upload = get_uploads_path()
    print(f"System upload (today): {system_upload}")

    # User-specific uploads
    user_upload = get_uploads_path(user_id="user-123")
    print(f"User upload (user-123): {user_upload}")

    # With specific date
    specific_date = date(2025, 1, 15)
    dated_upload = get_uploads_path(user_id="user-456", dt=specific_date)
    print(f"Dated upload (2025-01-15): {dated_upload}")

    # With time included
    now = datetime.now()
    timed_upload = get_uploads_path(user_id="user-789", dt=now, include_time=True)
    print(f"Timed upload (with hour/min): {timed_upload}")

    # S3 version
    s3_upload = get_uploads_path(user_id="user-123", use_s3=True)
    print(f"S3 upload: {s3_upload}")
    print()


def example_versioned_paths():
    """Demonstrate versioned resource paths."""
    print("=== Versioned Paths ===\n")

    # Schemas
    schema_path = get_versioned_path("schemas", "user-schema")
    print(f"Schema path: {schema_path}")

    # Agents
    agent_path = get_versioned_path("agents", "query-agent", version="v2")
    print(f"Agent path (v2): {agent_path}")

    # Tools
    tool_path = get_versioned_path("tools", "web-scraper")
    print(f"Tool path: {tool_path}")

    # Datasets
    dataset_path = get_versioned_path("datasets", "training-data")
    print(f"Dataset path: {dataset_path}")
    print()


def example_user_paths():
    """Demonstrate user-scoped paths."""
    print("=== User Paths ===\n")

    # User root
    user_root = get_user_path("user-123")
    print(f"User root: {user_root}")

    # User documents
    user_docs = get_user_path("user-123", "documents")
    print(f"User documents: {user_docs}")

    # User images
    user_images = get_user_path("user-456", "images")
    print(f"User images: {user_images}")
    print()


def example_temp_paths():
    """Demonstrate temporary file paths."""
    print("=== Temp Paths ===\n")

    # Default temp
    temp_default = get_temp_path()
    print(f"Default temp: {temp_default}")

    # Processing temp
    temp_processing = get_temp_path("processing")
    print(f"Processing temp: {temp_processing}")

    # Conversion temp
    temp_conversion = get_temp_path("conversion")
    print(f"Conversion temp: {temp_conversion}")
    print()


def example_practical_usage():
    """Demonstrate practical usage with FS."""
    print("=== Practical Usage ===\n")

    fs = FS()

    # Get upload path for today
    upload_dir = get_uploads_path(user_id="user-123")
    print(f"Upload directory: {upload_dir}")

    # Ensure directory exists (local only)
    ensure_dir_exists(upload_dir)

    # Write file to upload directory
    file_path = join_path(upload_dir, "test-data.json", is_s3=False)
    print(f"Writing to: {file_path}")

    data = {
        "message": "Hello from REM",
        "timestamp": datetime.now().isoformat(),
        "user_id": "user-123",
    }
    fs.write(file_path, data)
    print(f"✓ Written successfully")

    # Read it back
    read_data = fs.read(file_path)
    print(f"✓ Read back: {read_data}")

    # List files in directory
    files = fs.ls(upload_dir)
    print(f"✓ Files in directory: {files}")
    print()


def example_path_components():
    """Demonstrate path structure breakdown."""
    print("=== Path Structure ===\n")

    example_path = get_uploads_path(
        user_id="user-123", dt=datetime(2025, 1, 19, 14, 30), include_time=True
    )

    print(f"Full path: {example_path}")
    print("\nBreakdown:")
    print("  base_uri/rem/v1/uploads/user-123/2025/01/19/14_30")
    print("  │        │  │  │       │        │    │  │  │")
    print("  │        │  │  │       │        │    │  │  └─ minute")
    print("  │        │  │  │       │        │    │  └──── hour")
    print("  │        │  │  │       │        │    └─────── day")
    print("  │        │  │  │       │        └──────────── month")
    print("  │        │  │  │       └───────────────────── year")
    print("  │        │  │  └───────────────────────────── user_id (or 'system')")
    print("  │        │  └──────────────────────────────── category")
    print("  │        └─────────────────────────────────── version")
    print("  └──────────────────────────────────────────── namespace")
    print()


def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("REM Filesystem Path Conventions Examples")
    print("=" * 70 + "\n")

    example_basic_paths()
    example_uploads_paths()
    example_versioned_paths()
    example_user_paths()
    example_temp_paths()
    example_path_components()
    example_practical_usage()

    print("=" * 70)
    print("Done! Check $REM_HOME/fs/rem/v1/uploads/ for created files")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
