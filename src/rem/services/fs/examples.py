"""
Example usage of the REM file system service.

Run these examples to test the fs service functionality.
"""

from rem.services.fs import FS, generate_presigned_url


def example_basic_operations():
    """Basic read/write operations."""
    fs = FS()

    # Write and read JSON
    data = {"name": "rem", "version": "0.1.0", "features": ["s3", "local", "polars"]}
    fs.write("/tmp/test.json", data)
    loaded = fs.read("/tmp/test.json")
    print(f"JSON: {loaded}")

    # Write and read YAML
    config = {"database": {"host": "localhost", "port": 5432}, "cache": {"enabled": True}}
    fs.write("/tmp/config.yaml", config)
    loaded_config = fs.read("/tmp/config.yaml")
    print(f"YAML: {loaded_config}")

    # Write and read text
    fs.write("/tmp/readme.md", "# Hello REM\n\nFile system abstraction.")
    text = fs.read("/tmp/readme.md")
    print(f"Text: {text[:50]}...")


def example_columnar_data():
    """Columnar data with Polars."""
    try:
        import polars as pl
    except ImportError:
        print("Polars not installed - skipping columnar examples")
        print("Install with: uv add polars")
        return

    fs = FS()

    # Create sample dataframe
    df = pl.DataFrame({
        "id": [1, 2, 3, 4, 5],
        "name": ["Alice", "Bob", "Carol", "Dave", "Eve"],
        "score": [95.5, 87.2, 92.8, 78.3, 88.9],
    })

    # Write to CSV
    fs.write("/tmp/data.csv", df)
    csv_df = fs.read("/tmp/data.csv", use_polars=True)
    print(f"CSV DataFrame:\n{csv_df}")

    # Write to Parquet
    fs.write("/tmp/data.parquet", df)
    parquet_df = fs.read("/tmp/data.parquet")
    print(f"Parquet DataFrame:\n{parquet_df}")


def example_image_operations():
    """Image read/write operations."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        print("Pillow not installed - skipping image examples")
        print("Install with: uv add pillow")
        return

    fs = FS()

    # Create sample image
    img_array = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    img = Image.fromarray(img_array)

    # Write image
    fs.write("/tmp/test.png", img)

    # Read image
    loaded_img = fs.read_image("/tmp/test.png")
    print(f"Image: {loaded_img.size} {loaded_img.mode}")


def example_file_operations():
    """File listing, copying, deleting."""
    fs = FS()

    # Create test files
    fs.write("/tmp/rem_test/file1.txt", "Content 1")
    fs.write("/tmp/rem_test/file2.txt", "Content 2")
    fs.write("/tmp/rem_test/subdir/file3.txt", "Content 3")

    # List files
    files = fs.ls("/tmp/rem_test/")
    print(f"Files: {files}")

    # List directories
    dirs = fs.ls_dirs("/tmp/rem_test/")
    print(f"Directories: {dirs}")

    # Copy file
    fs.copy("/tmp/rem_test/file1.txt", "/tmp/rem_test/file1_copy.txt")

    # Check existence
    exists = fs.exists("/tmp/rem_test/file1_copy.txt")
    print(f"Copy exists: {exists}")

    # Delete files (with safety limit)
    deleted = fs.delete("/tmp/rem_test/", limit=10)
    print(f"Deleted {len(deleted)} files")


def example_s3_operations():
    """S3 operations (requires configured S3 bucket)."""
    fs = FS()

    # NOTE: Update bucket name to your test bucket
    test_bucket = "s3://rem-test-bucket"

    try:
        # Write to S3
        data = {"timestamp": "2025-01-01T00:00:00Z", "event": "test"}
        fs.write(f"{test_bucket}/test.json", data)

        # Read from S3
        loaded = fs.read(f"{test_bucket}/test.json")
        print(f"S3 JSON: {loaded}")

        # Generate presigned URL
        url = generate_presigned_url(f"{test_bucket}/test.json", expiry=3600)
        print(f"Presigned URL: {url[:100]}...")

        # Copy from S3 to local
        fs.copy(f"{test_bucket}/test.json", "/tmp/downloaded.json")
        print("Downloaded from S3 to /tmp/downloaded.json")

        # Upload from local to S3
        fs.write("/tmp/upload.txt", "Upload test")
        fs.copy("/tmp/upload.txt", f"{test_bucket}/uploaded.txt")
        print("Uploaded to S3")

        # List S3 files
        files = fs.ls(f"{test_bucket}/")
        print(f"S3 files: {files[:5]}")  # First 5

    except Exception as e:
        print(f"S3 operations failed (bucket may not exist): {e}")
        print("Configure S3 settings in .env and create test bucket")


def example_presigned_urls():
    """Generate presigned URLs for S3 access."""
    # Download URL
    download_url = generate_presigned_url(
        "s3://rem-bucket/document.pdf",
        expiry=3600  # 1 hour
    )
    print(f"Download URL: {download_url[:100]}...")

    # Upload URL
    upload_url = generate_presigned_url(
        "s3://rem-bucket/upload.pdf",
        expiry=300,  # 5 minutes
        for_upload=True
    )
    print(f"Upload URL (PUT): {upload_url[:100]}...")


def main():
    """Run all examples."""
    print("=" * 60)
    print("REM File System Service Examples")
    print("=" * 60)

    print("\n1. Basic Operations")
    print("-" * 60)
    example_basic_operations()

    print("\n2. Columnar Data (Polars)")
    print("-" * 60)
    example_columnar_data()

    print("\n3. Image Operations")
    print("-" * 60)
    example_image_operations()

    print("\n4. File Operations")
    print("-" * 60)
    example_file_operations()

    print("\n5. S3 Operations")
    print("-" * 60)
    example_s3_operations()

    print("\n6. Presigned URLs")
    print("-" * 60)
    example_presigned_urls()

    print("\n" + "=" * 60)
    print("Examples complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
