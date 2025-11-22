"""Test Phoenix connection and dataset creation."""

from phoenix.client import Client

# Use API key from Kubernetes secret
API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJBcGlLZXk6MyJ9.Hxdf349z3k9DGkYwnBAwqAXYM55JxOdGsbYAcbCteuY"
client = Client(base_url="http://localhost:6006", api_key=API_KEY)

print("Testing Phoenix connection...")
try:
    datasets = list(client.datasets.list())
    print(f"✓ Connection successful! Found {len(datasets)} datasets")

    # Try creating a simple dataset
    print("\nCreating test dataset...")
    dataset = client.datasets.create_dataset(
        name="test-dataset-simple",
        inputs=[{"question": "Hello"}],
        outputs=[{"answer": "World"}],
        dataset_description="Simple test dataset"
    )
    print(f"✓ Dataset created: {dataset.name} with {len(dataset)} examples")

except Exception as e:
    print(f"✗ Error: {e}")
    print(f"Error type: {type(e).__name__}")
