"""Phoenix prompt label management via GraphQL.

This module provides utilities for creating and assigning labels to prompts
in Phoenix using the GraphQL API.

Based on carrier implementation with adaptations for REM:
- Standard REM labels: rem, golden-set, agent-results, evaluator
- GraphQL operations: create, list, assign labels
- Color-coded label system
"""

import httpx
from typing import Optional
from loguru import logger


class PromptLabelQueries:
    """GraphQL queries for prompt and dataset label operations."""

    CREATE_PROMPT_LABEL = """
    mutation CreateLabel($input: CreatePromptLabelInput!) {
      createPromptLabel(input: $input) {
        promptLabels {
          id
          name
          color
          description
        }
      }
    }
    """

    CREATE_DATASET_LABEL = """
    mutation CreateDatasetLabel($input: CreateDatasetLabelInput!) {
      createDatasetLabel(input: $input) {
        datasetLabel {
          id
          name
          color
          description
        }
      }
    }
    """

    LIST_PROMPT_LABELS = """
    query {
      promptLabels {
        edges {
          node {
            id
            name
            color
            description
          }
        }
      }
    }
    """

    LIST_DATASET_LABELS = """
    query {
      datasetLabels {
        edges {
          node {
            id
            name
            color
            description
          }
        }
      }
    }
    """

    GET_DATASET_BY_NAME = """
    query GetDataset($name: String!) {
      datasets(first: 1, filterBy: {name: {equals: $name}}) {
        edges {
          node {
            id
            name
          }
        }
      }
    }
    """

    ASSIGN_PROMPT_LABELS = """
    mutation SetLabels($promptId: ID!, $promptLabelIds: [ID!]!) {
      setPromptLabels(input: {
        promptId: $promptId
        promptLabelIds: $promptLabelIds
      }) {
        query {
          node(id: $promptId) {
            __typename
            ... on Prompt {
              id
              name
              labels {
                id
                name
                color
              }
            }
          }
        }
      }
    }
    """

    ASSIGN_DATASET_LABELS = """
    mutation SetDatasetLabels($datasetId: ID!, $datasetLabelIds: [ID!]!) {
      setDatasetLabels(input: {
        datasetId: $datasetId
        datasetLabelIds: $datasetLabelIds
      }) {
        dataset {
          id
          labels {
            id
            name
            color
          }
        }
      }
    }
    """


class GraphQLClient:
    """Simple GraphQL client for Phoenix API."""

    def __init__(self, base_url: str, api_key: Optional[str] = None):
        """Initialize GraphQL client.

        Args:
            base_url: Phoenix base URL
            api_key: Optional API key for auth
        """
        self.base_url = base_url
        self.api_key = api_key

    def execute(self, query: str, variables: Optional[dict] = None) -> dict:
        """Execute GraphQL query.

        Args:
            query: GraphQL query/mutation string
            variables: Optional variables dict

        Returns:
            Response data dict

        Raises:
            httpx.HTTPStatusError: On HTTP errors
        """
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = httpx.post(
            f"{self.base_url}/graphql",
            headers=headers,
            json={"query": query, "variables": variables},
            timeout=10,
        )
        response.raise_for_status()

        result = response.json()

        # Log errors but don't raise
        if result.get("errors"):
            error_msgs = [e.get("message", "Unknown error") for e in result["errors"]]
            logger.debug(f"GraphQL errors: {error_msgs}")

        return result


class PhoenixPromptLabels:
    """Helper for managing Phoenix prompt labels via GraphQL."""

    def __init__(self, base_url: str = "http://localhost:6006", api_key: Optional[str] = None):
        """Initialize label manager.

        Args:
            base_url: Phoenix base URL
            api_key: Phoenix API key (optional, for auth)
        """
        self.client = GraphQLClient(base_url, api_key)
        self._label_cache: Optional[dict[str, str]] = None

    def create_prompt_label(
        self,
        name: str,
        color: str,
        description: str = "",
    ) -> Optional[str]:
        """Create a new prompt label.

        Args:
            name: Label name (lowercase, hyphens, underscores)
            color: Color in rgba(r, g, b, a) format
            description: Optional description

        Returns:
            Label ID if created, None if already exists

        Raises:
            httpx.HTTPStatusError: On HTTP errors
        """
        variables = {"input": {"name": name, "color": color, "description": description}}
        result = self.client.execute(PromptLabelQueries.CREATE_PROMPT_LABEL, variables)

        # Check if already exists
        if result.get("errors"):
            for error in result["errors"]:
                if "already exists" in error.get("message", ""):
                    logger.debug(f"Prompt label '{name}' already exists")
                    return None

        # Extract label ID from response
        if result.get("data") and result["data"].get("createPromptLabel"):
            labels = result["data"]["createPromptLabel"]["promptLabels"]
            if labels:
                label_id = labels[0]["id"]
                logger.info(f"Created prompt label '{name}' ({label_id})")
                # Invalidate cache
                self._label_cache = None
                return label_id

        return None

    def create_dataset_label(
        self,
        name: str,
        color: str,
        description: str = "",
    ) -> Optional[str]:
        """Create a new dataset label.

        Args:
            name: Label name
            color: Color in rgba(r, g, b, a) format
            description: Optional description

        Returns:
            Label ID if created, None if already exists

        Raises:
            httpx.HTTPStatusError: On HTTP errors
        """
        variables = {"input": {"name": name, "color": color, "description": description}}
        result = self.client.execute(PromptLabelQueries.CREATE_DATASET_LABEL, variables)

        # Check if already exists
        if result.get("errors"):
            for error in result["errors"]:
                if "already exists" in error.get("message", ""):
                    logger.debug(f"Dataset label '{name}' already exists")
                    return None

        # Extract label ID from response
        if result.get("data") and result["data"].get("createDatasetLabel"):
            label = result["data"]["createDatasetLabel"]["datasetLabel"]
            label_id = label["id"]
            logger.info(f"Created dataset label '{name}' ({label_id})")
            return label_id

        return None

    def list_prompt_labels(self, force_refresh: bool = False) -> dict[str, str]:
        """List all available prompt labels.

        Args:
            force_refresh: Force refresh cache

        Returns:
            Dict mapping label name to label ID
        """
        if self._label_cache and not force_refresh:
            return self._label_cache

        result = self.client.execute(PromptLabelQueries.LIST_PROMPT_LABELS)
        labels = {}

        if result.get("data", {}).get("promptLabels"):
            for edge in result["data"]["promptLabels"]["edges"]:
                label = edge["node"]
                labels[label["name"]] = label["id"]

        self._label_cache = labels
        return labels

    def list_dataset_labels(self) -> dict[str, str]:
        """List all available dataset labels.

        Returns:
            Dict mapping label name to label ID
        """
        result = self.client.execute(PromptLabelQueries.LIST_DATASET_LABELS)
        labels = {}

        if result.get("data", {}).get("datasetLabels"):
            for edge in result["data"]["datasetLabels"]["edges"]:
                label = edge["node"]
                labels[label["name"]] = label["id"]

        return labels

    def ensure_prompt_labels(self, labels: list[tuple[str, str, str]]) -> dict[str, str]:
        """Ensure prompt labels exist, creating them if needed.

        Args:
            labels: List of (name, color, description) tuples

        Returns:
            Dict mapping label name to label ID
        """
        existing = self.list_prompt_labels(force_refresh=True)

        for name, color, description in labels:
            if name not in existing:
                label_id = self.create_prompt_label(name, color, description)
                if label_id:
                    existing[name] = label_id

        return existing

    def ensure_dataset_labels(self, labels: list[tuple[str, str, str]]) -> dict[str, str]:
        """Ensure dataset labels exist, creating them if needed.

        Args:
            labels: List of (name, color, description) tuples

        Returns:
            Dict mapping label name to label ID
        """
        existing = self.list_dataset_labels()

        for name, color, description in labels:
            if name not in existing:
                label_id = self.create_dataset_label(name, color, description)
                if label_id:
                    existing[name] = label_id

        return existing

    def assign_prompt_labels(
        self,
        prompt_id: str,
        label_names: list[str],
    ) -> list[dict]:
        """Assign labels to a prompt.

        Args:
            prompt_id: Prompt ID (from prompts GraphQL query)
            label_names: List of label names to assign

        Returns:
            List of assigned labels with id, name, color

        Raises:
            ValueError: If label not found
            httpx.HTTPStatusError: On HTTP errors
        """
        available_labels = self.list_prompt_labels()

        # Convert label names to IDs
        label_ids = []
        for name in label_names:
            if name not in available_labels:
                raise ValueError(
                    f"Prompt label '{name}' not found. Available: {list(available_labels.keys())}"
                )
            label_ids.append(available_labels[name])

        variables = {"promptId": prompt_id, "promptLabelIds": label_ids}
        result = self.client.execute(PromptLabelQueries.ASSIGN_PROMPT_LABELS, variables)

        if result.get("data") and result["data"].get("setPromptLabels"):
            node = result["data"]["setPromptLabels"]["query"]["node"]
            labels = node.get("labels", [])
            logger.info(f"Assigned {len(label_names)} labels to prompt {node['name']}")
            return labels

        return []

    def get_dataset_id(self, dataset_name: str) -> str | None:
        """Get dataset ID by name.

        Args:
            dataset_name: Dataset name

        Returns:
            Dataset ID if found, None otherwise
        """
        variables = {"name": dataset_name}
        result = self.client.execute(PromptLabelQueries.GET_DATASET_BY_NAME, variables)

        if result.get("data") and result["data"].get("datasets"):
            edges = result["data"]["datasets"]["edges"]
            if edges:
                return edges[0]["node"]["id"]

        return None

    def assign_dataset_labels(
        self,
        dataset_id: str,
        label_names: list[str],
    ) -> bool:
        """Assign labels to a dataset.

        Args:
            dataset_id: Dataset ID (from datasets GraphQL query)
            label_names: List of label names to assign

        Returns:
            True if successful

        Raises:
            ValueError: If label not found
            httpx.HTTPStatusError: On HTTP errors
        """
        available_labels = self.list_dataset_labels()

        # Convert label names to IDs
        label_ids = []
        for name in label_names:
            if name not in available_labels:
                raise ValueError(
                    f"Dataset label '{name}' not found. Available: {list(available_labels.keys())}"
                )
            label_ids.append(available_labels[name])

        variables = {"datasetId": dataset_id, "datasetLabelIds": label_ids}
        result = self.client.execute(PromptLabelQueries.ASSIGN_DATASET_LABELS, variables)

        if result.get("data") and result["data"].get("setDatasetLabels"):
            dataset = result["data"]["setDatasetLabels"]["dataset"]
            labels = dataset.get("labels", [])
            logger.info(f"Assigned {len(labels)} labels to dataset {dataset_id}")
            return True

        return False


# Standard REM labels (shared by prompts and datasets)
# Phoenix expects hex colors (e.g., #3b82f6), not rgba format
REM_LABELS = [
    ("REM", "#3b82f6", "All REM integration artifacts (auto-added)"),
    ("Agent", "#10b981", "Agent prompts (auto-added for agents)"),
    ("Evaluator", "#8b5cf6", "Evaluator prompts (auto-added for evaluators)"),
    ("Ground Truth", "#22c55e", "Ground truth/golden set datasets (auto-added)"),
    ("Test", "#f59e0b", "Test and integration artifacts"),
    ("HelloWorld", "#ec4899", "Hello world test examples"),
]


def setup_rem_labels(
    base_url: str = "http://localhost:6006",
    api_key: Optional[str] = None,
) -> PhoenixPromptLabels:
    """Setup standard REM prompt and dataset labels.

    Args:
        base_url: Phoenix base URL
        api_key: Phoenix API key

    Returns:
        Configured PhoenixPromptLabels instance
    """
    helper = PhoenixPromptLabels(base_url=base_url, api_key=api_key)
    helper.ensure_prompt_labels(REM_LABELS)
    helper.ensure_dataset_labels(REM_LABELS)
    return helper
