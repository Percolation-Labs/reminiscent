"""Phoenix evaluator provider for REM agents.

This module provides factory functions for creating Phoenix-compatible evaluators
from schema definitions, following the same pattern as Pydantic AI agent creation.

Exported Functions:
===================
- load_evaluator_schema: Load evaluator schemas from schemas/evaluators/
- create_phoenix_evaluator: Create Phoenix evaluator config from schema
- create_evaluator_from_schema: Create callable evaluator function
- schema_to_prompt: Convert schema to Phoenix openai_params format
- sanitize_tool_name: Sanitize tool names for Phoenix/OpenAI compatibility
- run_evaluation_experiment: Run complete evaluation workflow

Design Pattern (mirrors Pydantic AI provider):
==============================================
1. Load evaluator schemas from schemas/evaluators/ directory
2. Extract system prompt, output schema, and metadata
3. Create Phoenix-compatible evaluator functions
4. Support both LLM-as-a-Judge and code-based evaluators

Two-Phase Evaluation Architecture:
===================================

Phase 1 - Golden Set Creation:
  SMEs create datasets with (input, reference) pairs in Phoenix

Phase 2 - Automated Evaluation:
  Step 1: Run agents → (input, agent_output)
  Step 2: Run evaluators → (input, agent_output, reference) → scores

Evaluator Types:
================

1. LLM-as-a-Judge (uses Claude/GPT to evaluate):
   - Compares agent output to reference
   - Scores on multiple dimensions (correctness, completeness, etc.)
   - Provides explanations and suggestions

2. Code-based (deterministic evaluation):
   - Exact match checking
   - Field presence validation
   - Format compliance

Usage:
======

Create evaluator from schema:
    >>> evaluator = create_evaluator_from_schema("rem-lookup-correctness")
    >>> result = evaluator(example)
    >>> # Returns: {"score": 0.95, "label": "correct", "explanation": "..."}

Run evaluation experiment:
    >>> from rem.services.phoenix import PhoenixClient
    >>> client = PhoenixClient()
    >>> experiment = run_evaluation_experiment(
    ...     dataset_name="rem-lookup-golden",
    ...     task=run_agent_task,
    ...     evaluator_schema_path="rem-lookup-correctness",
    ...     phoenix_client=client
    ... )
"""

from typing import Any, Callable, TYPE_CHECKING
from pathlib import Path
import json
import yaml

from loguru import logger

# Lazy import to avoid Phoenix initialization at module load time
if TYPE_CHECKING:
    from phoenix.evals import LLMEvaluator
    from phoenix.client.resources.datasets import Dataset
    from phoenix.client.resources.experiments.types import RanExperiment
    from rem.services.phoenix import PhoenixClient

PHOENIX_AVAILABLE = None  # Lazy check on first use


def _check_phoenix_available() -> bool:
    """Lazy check if Phoenix is available (only imports when needed)."""
    global PHOENIX_AVAILABLE
    if PHOENIX_AVAILABLE is not None:
        return PHOENIX_AVAILABLE

    try:
        import phoenix.evals  # noqa: F401
        PHOENIX_AVAILABLE = True
    except ImportError:
        PHOENIX_AVAILABLE = False
        logger.warning("arize-phoenix package not installed - evaluator factory unavailable")

    return PHOENIX_AVAILABLE


# =============================================================================
# NAME SANITIZATION
# =============================================================================


def sanitize_tool_name(tool_name: str) -> str:
    """Sanitize tool name for Phoenix/OpenAI compatibility.

    Replaces all non-alphanumeric characters with underscores to prevent
    prompt breaking and ensure compatibility with OpenAI function calling.

    Args:
        tool_name: Original tool name (e.g., "ask_rem", "traverse-graph")

    Returns:
        Sanitized name with only alphanumeric characters and underscores

    Example:
        >>> sanitize_tool_name("ask_rem")
        'ask_rem'
        >>> sanitize_tool_name("traverse-graph")
        'traverse_graph'
        >>> sanitize_tool_name("mcp://server/tool-name")
        'mcp___server_tool_name'
    """
    return "".join(c if c.isalnum() else "_" for c in tool_name)


# =============================================================================
# SCHEMA LOADING
# =============================================================================


def load_evaluator_schema(evaluator_name: str) -> dict[str, Any]:
    """Load evaluator schema from schemas/evaluators/ directory.

    Searches for evaluator schema in rem/schemas/evaluators/
    Supports .json, .yaml, and .yml files.

    Args:
        evaluator_name: Evaluator name (with or without extension)
                       e.g., "rem-lookup-correctness" or
                             "rem-lookup-correctness.yaml"

    Returns:
        Evaluator schema dictionary with keys:
        - description: System prompt for LLM evaluator
        - properties: Output schema fields
        - required: Required output fields
        - labels: Optional labels for categorization
        - version: Schema version

    Raises:
        FileNotFoundError: If evaluator schema not found

    Example:
        >>> schema = load_evaluator_schema("rem-lookup-correctness")
        >>> print(schema["description"])
    """
    # Get schemas directory (rem/schemas/evaluators/)
    # rem.__file__ = rem/src/rem/__init__.py
    # We need rem/schemas/evaluators/
    import rem
    rem_module_dir = Path(rem.__file__).parent  # rem/src/rem
    rem_package_root = rem_module_dir.parent.parent  # rem/src/rem -> rem/src -> rem
    schema_dir = rem_package_root / "schemas" / "evaluators"

    # Try .yaml first (preferred format)
    yaml_path = schema_dir / f"{evaluator_name}.yaml"
    if yaml_path.exists():
        logger.debug(f"Loading evaluator schema from {yaml_path}")
        with open(yaml_path) as f:
            return yaml.safe_load(f)

    # Try .yml
    yml_path = schema_dir / f"{evaluator_name}.yml"
    if yml_path.exists():
        logger.debug(f"Loading evaluator schema from {yml_path}")
        with open(yml_path) as f:
            return yaml.safe_load(f)

    # Try .json
    json_path = schema_dir / f"{evaluator_name}.json"
    if json_path.exists():
        logger.debug(f"Loading evaluator schema from {json_path}")
        with open(json_path) as f:
            return json.load(f)

    raise FileNotFoundError(
        f"Evaluator schema not found: {evaluator_name}\n"
        f"Searched in: {schema_dir}\n"
        f"Supported formats: .yaml, .yml, .json"
    )


# =============================================================================
# EVALUATOR CREATION
# =============================================================================


def create_phoenix_evaluator(
    evaluator_schema: dict[str, Any],
    model_name: str | None = None,
) -> dict[str, Any]:
    """Create Phoenix evaluator configuration from schema.

    Args:
        evaluator_schema: Evaluator schema dictionary
        model_name: Optional LLM model to use (defaults to claude-sonnet-4-5)

    Returns:
        Evaluator config dict with:
        - name: Evaluator name
        - llm: Phoenix LLM wrapper
        - prompt_template: System prompt
        - schema: Output schema

    Raises:
        ImportError: If arize-phoenix not installed
        KeyError: If required schema fields missing
    """
    if not _check_phoenix_available():
        raise ImportError(
            "arize-phoenix package required for evaluators. "
            "Install with: pip install arize-phoenix"
        )

    # Import Phoenix after availability check
    from phoenix.evals import OpenAIModel, AnthropicModel

    logger.debug("Creating Phoenix evaluator from schema")

    # Extract schema fields
    evaluator_name = evaluator_schema.get("title", "UnnamedEvaluator")
    system_prompt = evaluator_schema.get("description", "")
    output_schema = evaluator_schema.get("properties", {})

    if not system_prompt:
        raise KeyError("evaluator_schema must contain 'description' field with system prompt")

    # Default model (use Claude Sonnet 4.5 for evaluators)
    if model_name is None:
        model_name = "claude-sonnet-4-5-20250929"
        logger.debug(f"Using default evaluator model: {model_name}")

    logger.info(f"Creating Phoenix evaluator: {evaluator_name} with model={model_name}")

    # Parse provider and model name
    if ":" in model_name:
        provider, phoenix_model_name = model_name.split(":", 1)
    else:
        # Detect provider from model name
        if model_name.startswith("claude"):
            provider = "anthropic"
        else:
            provider = "openai"
        phoenix_model_name = model_name

    # Create appropriate Phoenix LLM wrapper based on provider
    if provider.lower() == "anthropic":
        # Anthropic models don't support both temperature and top_p
        llm = AnthropicModel(
            model=phoenix_model_name,
            temperature=0.0,
            top_p=None  # Don't send top_p to Anthropic API
        )
    else:
        # Default to OpenAI for other providers (gpt-4, etc.)
        llm = OpenAIModel(model=phoenix_model_name, temperature=0.0)

    # Return evaluator config (not an instance - we'll use llm_classify directly)
    evaluator_config = {
        "name": evaluator_name,
        "llm": llm,
        "prompt_template": system_prompt,
        "schema": output_schema,
        "labels": evaluator_schema.get("labels", []),
        "version": evaluator_schema.get("version", "1.0.0"),
    }

    logger.info(f"Phoenix evaluator '{evaluator_name}' created successfully")
    return evaluator_config


def create_evaluator_from_schema(
    evaluator_schema_path: str | Path | dict[str, Any],
    model_name: str | None = None,
) -> Callable[[Any], Any]:
    """Create an evaluator function from a schema file or dict.

    The returned evaluator is a callable that Phoenix experiments can use.

    Args:
        evaluator_schema_path: Path to schema file, evaluator name, or schema dict
        model_name: Optional LLM model to use for evaluation

    Returns:
        Evaluator function compatible with Phoenix experiments

    Raises:
        FileNotFoundError: If schema file not found
        ImportError: If arize-phoenix not installed

    Example:
        >>> # From evaluator name (searches in schemas/evaluators/)
        >>> evaluator = create_evaluator_from_schema("rem-lookup-correctness")
        >>>
        >>> # From schema dict
        >>> schema = {"description": "...", "properties": {...}}
        >>> evaluator = create_evaluator_from_schema(schema)
        >>>
        >>> # Use in experiment
        >>> result = evaluator({
        ...     "input": {"query": "LOOKUP person:sarah-chen"},
        ...     "output": {"label": "sarah-chen", "type": "person", ...},
        ...     "expected": {"label": "sarah-chen", "type": "person", ...}
        ... })
    """
    if not _check_phoenix_available():
        raise ImportError(
            "arize-phoenix package required for evaluators. "
            "Install with: pip install arize-phoenix"
        )

    # Load schema if path/name provided
    if isinstance(evaluator_schema_path, (str, Path)):
        schema_path = Path(evaluator_schema_path)

        # If it's a file path, load directly
        if schema_path.exists():
            logger.debug(f"Loading evaluator schema from {schema_path}")
            if schema_path.suffix in [".yaml", ".yml"]:
                with open(schema_path) as f:
                    schema = yaml.safe_load(f)
            else:
                with open(schema_path) as f:
                    schema = json.load(f)
        else:
            # Treat as evaluator name, search in schemas/evaluators/
            schema = load_evaluator_schema(str(evaluator_schema_path))
    else:
        # Already a dict
        schema = evaluator_schema_path

    # Create evaluator config
    evaluator_config = create_phoenix_evaluator(
        evaluator_schema=schema,
        model_name=model_name,
    )

    # Import llm_classify for evaluation
    from phoenix.evals import llm_classify
    import pandas as pd

    # Wrap for Phoenix experiment compatibility
    def evaluator_fn(example: dict[str, Any]) -> dict[str, Any]:
        """Evaluate a single example using Phoenix llm_classify.

        Args:
            example: Dict with 'input', 'output', 'expected' keys
                - input: Agent input dict (e.g., {"query": "LOOKUP person:sarah-chen"})
                - output: Agent output dict (what the agent returned)
                - expected: Expected output dict (ground truth from dataset)

        Returns:
            Evaluation result with score, label, explanation
        """
        logger.debug(f"Evaluating example: {example.get('input', '')[:100]}...")

        # Phoenix llm_classify() expects a flat dict with string values
        # Build evaluation input by flattening nested dicts
        eval_input = {}

        # Extract and flatten input fields
        input_data = example.get("input", {})
        if isinstance(input_data, dict):
            for key, value in input_data.items():
                eval_input[f"input_{key}"] = str(value) if value is not None else ""
        else:
            eval_input["input"] = str(input_data) if input_data is not None else ""

        # Extract and flatten agent output fields
        output_data = example.get("output", {})
        if isinstance(output_data, dict):
            for key, value in output_data.items():
                eval_input[f"output_{key}"] = str(value) if value is not None else ""
        else:
            eval_input["output"] = str(output_data) if output_data is not None else ""

        # Extract and flatten expected fields (reference/ground truth)
        expected_data = example.get("expected", {})
        if isinstance(expected_data, dict):
            for key, value in expected_data.items():
                eval_input[f"expected_{key}"] = str(value) if value is not None else ""
        elif expected_data:
            eval_input["expected"] = str(expected_data)

        try:
            # Create single-row DataFrame for llm_classify
            df = pd.DataFrame([eval_input])

            # Call Phoenix llm_classify
            results_df = llm_classify(
                dataframe=df,
                model=evaluator_config["llm"],
                template=evaluator_config["prompt_template"],
                rails=["correct", "partial", "incorrect"],  # Common labels
                provide_explanation=True,
            )

            # Extract result
            if not results_df.empty:
                row = results_df.iloc[0]
                label = row.get("label", "error")
                explanation = row.get("explanation", "")

                # Map labels to scores
                score_map = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}
                score = score_map.get(label, 0.0)

                return {
                    "label": label,
                    "score": score,
                    "explanation": explanation or "",
                }
            else:
                logger.warning("llm_classify returned empty DataFrame")
                return {
                    "label": "error",
                    "score": 0.0,
                    "explanation": "Evaluator returned empty result",
                }

        except Exception as e:
            logger.error(f"Evaluator error: {e}")
            return {
                "label": "error",
                "score": 0.0,
                "explanation": f"Evaluator failed: {str(e)}",
            }

    return evaluator_fn


def schema_to_prompt(
    schema: dict[str, Any],
    schema_type: str = "evaluator",
    model_name: str = "gpt-4.1",
) -> dict[str, Any]:
    """Convert agent or evaluator schema to complete Phoenix openai_params.

    Converts REM schema format to Phoenix PromptVersion.from_openai() format,
    including messages, response_format, and tools (for agents).

    Args:
        schema: Schema dictionary (from load_evaluator_schema or agent schema)
        schema_type: Type of schema - "agent" or "evaluator"
        model_name: Model name for the prompt

    Returns:
        Complete openai_params dict ready for PromptVersion.from_openai()
        Contains: model, messages, response_format, tools (for agents)

    Example:
        >>> schema = load_evaluator_schema("rem-lookup-correctness")
        >>> openai_params = schema_to_prompt(schema, schema_type="evaluator")
        >>> # Use with Phoenix: PromptVersion.from_openai(openai_params)
    """
    system_prompt = schema.get("description", "")
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    # Extract tool definitions and convert to OpenAI format (for agents)
    tool_definitions = []  # For metadata YAML
    openai_tools = []      # For Phoenix tools parameter

    if schema_type == "agent":
        json_schema_extra = schema.get("json_schema_extra", {})
        tools = json_schema_extra.get("tools", [])

        for tool in tools:
            # Keep metadata format for YAML section
            tool_def = {
                "mcp_server": tool.get("mcp_server"),
                "tool_name": tool.get("tool_name"),
                "usage": tool.get("usage", ""),
            }
            tool_definitions.append(tool_def)

            # Convert to OpenAI function calling format
            # Sanitize tool name to prevent prompt breaking
            tool_name = tool.get("tool_name", "")
            sanitized_name = sanitize_tool_name(tool_name)

            openai_tool = {
                "type": "function",
                "function": {
                    "name": sanitized_name,
                    "description": tool.get("usage", "MCP tool"),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            }
            openai_tools.append(openai_tool)

    # Build schema metadata section
    info_key = "agent_info" if schema_type == "agent" else "evaluator_info"
    schema_metadata = {
        info_key: {
            "version": schema.get("version", "1.0.0"),
            "title": schema.get("title", ""),
        },
        "output_schema": {
            "description": f"Structured output returned by this {schema_type}",
            "properties": {
                k: {
                    "type": v.get("type", "unknown"),
                    "description": v.get("description", ""),
                }
                for k, v in properties.items()
            },
            "required": required,
        },
    }

    # Add tool definitions for agents
    if tool_definitions:
        schema_metadata["tools"] = {
            "description": "MCP tools available to this agent",
            "tool_definitions": tool_definitions,
        }

    # Add input format for evaluators
    if schema_type == "evaluator":
        schema_metadata["input_format"] = {
            "description": "Evaluators receive dataset examples with 'input' and 'output' fields",
            "structure": {
                "input": "dict[str, Any] - What the agent receives (e.g., {'query': '...'})",
                "output": "dict[str, Any] - Expected/ground truth (e.g., {'label': '...'})",
                "metadata": "dict[str, Any] - Optional metadata (e.g., {'difficulty': 'medium'})",
            },
        }

    # Append schema metadata to system prompt
    schema_yaml = yaml.dump(schema_metadata, default_flow_style=False, sort_keys=False)
    schema_section = f"\n\n---\n\n## Schema Metadata\n\n```yaml\n{schema_yaml}```"
    system_prompt = system_prompt + schema_section

    # Create structured template
    user_content = "{{input}}" if schema_type == "agent" else "Question: {{input}}\nAgent's Answer: {{output}}"

    template_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]

    # Build response format
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": schema.get("title", ""),
            "schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False
            },
            "strict": True
        }
    }

    # Build complete openai_params dict ready for PromptVersion.from_openai()
    openai_params: dict[str, Any] = {
        "model": model_name,
        "messages": template_messages,
        "response_format": response_format,
    }

    # Add tools for agents (OpenAI function calling format)
    if openai_tools:
        openai_params["tools"] = openai_tools

    return openai_params


# =============================================================================
# EXPERIMENT WORKFLOWS
# =============================================================================


def run_evaluation_experiment(
    dataset_name: str,
    task: Callable[[Any], Any] | None = None,
    evaluator_schema_path: str | Path | dict[str, Any] | None = None,
    experiment_name: str | None = None,
    experiment_description: str | None = None,
    phoenix_client: "PhoenixClient | None" = None,
    model_name: str | None = None,
) -> "RanExperiment":
    """Run a complete evaluation experiment using Phoenix.

    High-level workflow that:
    1. Loads dataset from Phoenix
    2. Optionally runs task (agent) on dataset
    3. Optionally runs evaluators on results
    4. Tracks results in Phoenix UI

    Args:
        dataset_name: Name of dataset in Phoenix
        task: Optional task function (agent) to run on dataset
        evaluator_schema_path: Optional evaluator schema path/name/dict
        experiment_name: Name for this experiment
        experiment_description: Description of experiment
        phoenix_client: Optional PhoenixClient (auto-creates if not provided)
        model_name: LLM model for evaluation

    Returns:
        RanExperiment with results and metrics

    Example - Agent Run Only:
        >>> experiment = run_evaluation_experiment(
        ...     dataset_name="rem-lookup-golden",
        ...     task=run_agent_task,
        ...     experiment_name="rem-v1-baseline"
        ... )

    Example - Agent + Evaluator:
        >>> experiment = run_evaluation_experiment(
        ...     dataset_name="rem-lookup-golden",
        ...     task=run_agent_task,
        ...     evaluator_schema_path="rem-lookup-correctness",
        ...     experiment_name="rem-v1-full-eval"
        ... )

    Example - Evaluator Only (on existing results):
        >>> experiment = run_evaluation_experiment(
        ...     dataset_name="rem-v1-results",
        ...     evaluator_schema_path="rem-lookup-correctness",
        ...     experiment_name="rem-v1-scoring"
        ... )
    """
    # Create Phoenix client if not provided
    if phoenix_client is None:
        from rem.services.phoenix import PhoenixClient
        phoenix_client = PhoenixClient()

    # Load dataset
    logger.info(f"Loading dataset: {dataset_name}")
    dataset = phoenix_client.get_dataset(dataset_name)

    # Create evaluator if schema provided
    evaluators = []
    if evaluator_schema_path:
        logger.info(f"Creating evaluator from schema: {evaluator_schema_path}")
        evaluator = create_evaluator_from_schema(
            evaluator_schema_path=evaluator_schema_path,
            model_name=model_name,
        )
        evaluators.append(evaluator)

    # Run experiment
    logger.info(f"Running experiment: {experiment_name or 'unnamed'}")
    experiment = phoenix_client.run_experiment(
        dataset=dataset,
        task=task,
        evaluators=evaluators if evaluators else None,
        experiment_name=experiment_name,
        experiment_description=experiment_description,
    )

    logger.success(
        f"Experiment complete. View results: {experiment.url if hasattr(experiment, 'url') else 'N/A'}"
    )

    return experiment
