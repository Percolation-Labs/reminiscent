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


def validate_evaluator_credentials(
    model_name: str | None = None,
) -> tuple[bool, str | None]:
    """Validate that the evaluator's LLM provider has working credentials.

    Performs a minimal API call to verify credentials before running experiments.
    This prevents running expensive agent tasks only to have evaluations fail.

    Args:
        model_name: Model to validate (defaults to claude-sonnet-4-5-20250929)

    Returns:
        Tuple of (success: bool, error_message: str | None)
        - (True, None) if credentials are valid
        - (False, "error description") if validation fails

    Example:
        >>> success, error = validate_evaluator_credentials()
        >>> if not success:
        ...     print(f"Evaluator validation failed: {error}")
        ...     return
    """
    if not _check_phoenix_available():
        return False, "arize-phoenix package not installed"

    from phoenix.evals import OpenAIModel, AnthropicModel

    # Default model (check env var first)
    if model_name is None:
        import os
        model_name = os.environ.get("EVALUATOR_MODEL", "claude-sonnet-4-5-20250929")

    # Parse provider
    if ":" in model_name:
        provider, phoenix_model_name = model_name.split(":", 1)
    else:
        if model_name.startswith("claude"):
            provider = "anthropic"
        else:
            provider = "openai"
        phoenix_model_name = model_name

    try:
        # Create LLM wrapper
        if provider.lower() == "anthropic":
            llm = AnthropicModel(
                model=phoenix_model_name,
                temperature=0.0,
                top_p=None,
            )
        else:
            llm = OpenAIModel(model=phoenix_model_name, temperature=0.0)

        # Test with minimal prompt
        logger.info(f"Validating evaluator credentials for {provider}:{phoenix_model_name}")
        response = llm("Say 'ok' if you can read this.")

        if response and len(response) > 0:
            logger.info(f"Evaluator credentials validated successfully for {provider}")
            return True, None
        else:
            return False, f"Empty response from {provider} model"

    except Exception as e:
        error_msg = str(e)
        # Extract meaningful error from common API errors
        if "credit balance is too low" in error_msg.lower():
            return False, f"Anthropic API credits exhausted. Add credits at https://console.anthropic.com/settings/billing"
        elif "api key" in error_msg.lower() or "authentication" in error_msg.lower():
            return False, f"{provider.capitalize()} API key missing or invalid. Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable."
        elif "rate limit" in error_msg.lower():
            return False, f"{provider.capitalize()} rate limit exceeded. Wait and retry."
        else:
            return False, f"{provider.capitalize()} API error: {error_msg[:200]}"


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
    """Load evaluator schema using centralized schema loader.

    Uses the same unified search logic as agent schemas:
    - "hello-world/default" → schemas/evaluators/hello-world/default.yaml
    - "lookup-correctness" → schemas/evaluators/rem/lookup-correctness.yaml
    - "rem-lookup-correctness" → schemas/evaluators/rem/lookup-correctness.yaml

    Args:
        evaluator_name: Evaluator name or path
                       e.g., "hello-world/default", "lookup-correctness"

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
        >>> schema = load_evaluator_schema("hello-world/default")
        >>> print(schema["description"])
    """
    from ...utils.schema_loader import load_agent_schema

    # Use centralized schema loader (searches evaluator paths too)
    return load_agent_schema(evaluator_name)


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
        import os
        model_name = os.environ.get("EVALUATOR_MODEL", "claude-sonnet-4-5-20250929")
        logger.debug(f"Using evaluator model: {model_name}")

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
    llm: OpenAIModel | AnthropicModel
    if provider.lower() == "anthropic":
        # Anthropic's newer Claude models (claude-sonnet-4, claude-opus-4, etc.)
        # don't allow both temperature and top_p to be specified together.
        # Phoenix's AnthropicModel defaults top_p=1, so we explicitly set it
        # to None to prevent it from being sent in the API request.
        # The invocation_parameters() method only includes params that are not None.
        llm = AnthropicModel(
            model=phoenix_model_name,
            temperature=0.0,
            top_p=None,  # type: ignore[arg-type] - None prevents param from being sent
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


def _evaluate_expression(expression: str, context: dict[str, Any]) -> Any:
    """Safely evaluate a simple expression with context variables.

    Supports: arithmetic, comparisons, boolean logic, len()
    """
    try:
        allowed_names = {
            "len": len,
            "True": True,
            "False": False,
            "true": True,
            "false": False,
        }
        allowed_names.update(context)
        return eval(expression, {"__builtins__": {}}, allowed_names)
    except Exception as e:
        logger.warning(f"Expression evaluation failed: {expression} - {e}")
        return 0.0


def _calculate_derived_scores(
    response_json: dict[str, Any],
    derived_scores_config: dict[str, Any],
) -> dict[str, Any]:
    """Calculate derived scores from evaluator output using config formulas.

    Supports:
    - weighted_sum: Weighted average of fields
    - conditional_weighted: Different formulas based on conditions
    - boolean_logic: Boolean expression evaluation
    """
    for score_name, score_config in derived_scores_config.items():
        score_type = score_config.get("type")

        if score_type == "weighted_sum":
            weights = score_config.get("weights", {})
            total = 0.0
            for field, weight in weights.items():
                field_value = response_json.get(field, 0.0)
                if isinstance(field_value, (int, float)):
                    total += field_value * weight
            response_json[score_name] = total

        elif score_type == "conditional_weighted":
            conditions = score_config.get("conditions", [])
            formula_to_use = None
            for cond_config in conditions:
                condition = cond_config.get("condition")
                if condition is None:
                    formula_to_use = cond_config.get("formula")
                    break
                field = condition.get("field")
                operator = condition.get("operator")
                value = condition.get("value")
                field_value = response_json.get(field, 0.0)
                condition_met = False
                if operator == ">=":
                    condition_met = field_value >= value
                elif operator == ">":
                    condition_met = field_value > value
                elif operator == "<=":
                    condition_met = field_value <= value
                elif operator == "<":
                    condition_met = field_value < value
                elif operator == "==":
                    condition_met = field_value == value
                elif operator == "!=":
                    condition_met = field_value != value
                if condition_met:
                    formula_to_use = cond_config.get("formula")
                    break
            if formula_to_use and formula_to_use.get("type") == "weighted_sum":
                weights = formula_to_use.get("weights", {})
                total = 0.0
                for field, weight in weights.items():
                    field_value = response_json.get(field, 0.0)
                    if isinstance(field_value, (int, float)):
                        total += field_value * weight
                response_json[score_name] = total

        elif score_type == "boolean_logic":
            expression = score_config.get("expression", "")
            result = _evaluate_expression(expression, response_json)
            response_json[score_name] = result

    return response_json


def _create_phoenix_evaluations(
    response_json: dict[str, Any],
    evaluations_config: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create Phoenix evaluation dicts from evaluator output using config.

    Each evaluation becomes a column in Phoenix UI with name, label, score, explanation.
    """
    evaluations = []
    for eval_config in evaluations_config:
        eval_name = eval_config.get("name", "unnamed")
        score_field = eval_config.get("score_field")
        score_expression = eval_config.get("score_expression")
        label_field = eval_config.get("label_field")
        label_expression = eval_config.get("label_expression")
        label_logic = eval_config.get("label_logic", [])
        label_transform = eval_config.get("label_transform", {})
        score_logic = eval_config.get("score_logic", {})
        explanation_field = eval_config.get("explanation_field")

        evaluation = {"name": eval_name}

        # Get score
        if score_expression:
            evaluation["score"] = _evaluate_expression(score_expression, response_json)
        elif score_field:
            evaluation["score"] = response_json.get(score_field, 0.0)
        elif score_logic and label_field:
            label_value = response_json.get(label_field)
            if isinstance(label_value, bool):
                label_value = "true" if label_value else "false"
            evaluation["score"] = score_logic.get(str(label_value), 0.0)
        else:
            evaluation["score"] = None

        # Get label
        if label_expression:
            evaluation["label"] = str(_evaluate_expression(label_expression, response_json))
        elif label_field:
            label_value = response_json.get(label_field)
            if isinstance(label_value, bool):
                label_value = "true" if label_value else "false"
            if label_transform:
                evaluation["label"] = label_transform.get(str(label_value), str(label_value))
            else:
                evaluation["label"] = str(label_value)
        elif label_logic and (score_field or score_expression):
            score_value = evaluation.get("score", 0.0)
            label = "unknown"
            for logic in label_logic:
                threshold = logic.get("threshold", 0.0)
                operator = logic.get("operator", ">=")
                if operator == ">=" and score_value >= threshold:
                    label = logic.get("label", "unknown")
                    break
                elif operator == ">" and score_value > threshold:
                    label = logic.get("label", "unknown")
                    break
            evaluation["label"] = label
        else:
            evaluation["label"] = None

        # Get explanation
        if explanation_field:
            explanation_value = response_json.get(explanation_field, "")
            if isinstance(explanation_value, list):
                evaluation["explanation"] = ", ".join(str(x) for x in explanation_value) if explanation_value else "None"
            else:
                evaluation["explanation"] = str(explanation_value)
        else:
            evaluation["explanation"] = None

        evaluations.append(evaluation)
    return evaluations


def create_evaluator_from_schema(
    evaluator_schema_path: str | Path | dict[str, Any],
    model_name: str | None = None,
) -> Callable[[Any], Any]:
    """Create an evaluator function from a schema file or dict.

    Uses direct LLM call with JSON schema for structured output evaluation.
    Supports phoenix_config for derived scores and evaluation column mappings.

    Args:
        evaluator_schema_path: Path to schema file, evaluator name, or schema dict
        model_name: Optional LLM model to use for evaluation

    Returns:
        Evaluator function compatible with Phoenix experiments

    Raises:
        FileNotFoundError: If schema file not found
        ImportError: If arize-phoenix not installed

    Example:
        >>> evaluator = create_evaluator_from_schema("rem-lookup-correctness")
        >>> result = evaluator(input={...}, output={...}, expected={...})
        >>> # Returns: list of {"name": "...", "score": 0.95, "label": "...", "explanation": "..."}
    """
    if not _check_phoenix_available():
        raise ImportError(
            "arize-phoenix package required for evaluators. "
            "Install with: pip install arize-phoenix"
        )

    # Load schema if path/name provided
    if isinstance(evaluator_schema_path, (str, Path)):
        schema_path = Path(evaluator_schema_path)
        if schema_path.exists():
            logger.debug(f"Loading evaluator schema from {schema_path}")
            if schema_path.suffix in [".yaml", ".yml"]:
                with open(schema_path) as f:
                    schema = yaml.safe_load(f)
            else:
                with open(schema_path) as f:
                    schema = json.load(f)
        else:
            schema = load_evaluator_schema(str(evaluator_schema_path))
    else:
        schema = evaluator_schema_path

    # Extract schema components
    output_schema = schema.get("properties", {})

    # Extract phoenix_config for derived scores and evaluations
    phoenix_config = schema.get("phoenix_config", {})
    derived_scores_config = phoenix_config.get("derived_scores", {})
    evaluations_config = phoenix_config.get("evaluations", [])

    # Create evaluator config (LLM wrapper, prompt, etc.)
    evaluator_config = create_phoenix_evaluator(
        evaluator_schema=schema,
        model_name=model_name,
    )

    import re

    def evaluator_fn(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> list[dict[str, Any]]:
        """Evaluate using Phoenix's named parameter binding with structured LLM output.

        Phoenix automatically binds these parameters:
        - input: Dataset input dict
        - output: Task's return value (agent output)
        - expected: Expected output dict (reference/ground truth)

        Returns:
            List of Phoenix evaluation dicts with name, score, label, explanation
        """
        logger.debug("Evaluating with structured output pattern")

        # Extract question from input
        if isinstance(input, dict):
            question = input.get("input", input.get("text", str(input)))
        else:
            question = str(input)

        # Serialize agent output
        if isinstance(output, dict):
            output_str = json.dumps(output, indent=2)
        else:
            output_str = str(output)

        # Get reference from expected
        if isinstance(expected, dict):
            reference = expected.get("reference", expected.get("expected_output",
                         expected.get("ground_truth", str(expected))))
        else:
            reference = str(expected)

        try:
            # Build user message
            user_message = f"""Question/Input: {question}

Agent's Answer:
{output_str}

Expected Answer (Reference):
{reference}

Please evaluate the agent's answer according to the evaluation criteria."""

            # Add JSON schema requirement to system prompt
            system_prompt = evaluator_config["prompt_template"]
            schema_instruction = f"\n\nYou MUST respond with valid JSON matching this schema:\n{json.dumps(output_schema, indent=2)}\n\nProvide ONLY the JSON response, no markdown code blocks or extra text."
            system_with_schema = system_prompt + schema_instruction

            # Phoenix LLM models expect a single prompt string
            llm = evaluator_config["llm"]
            full_prompt = f"{system_with_schema}\n\n{user_message}"
            response_text = llm(full_prompt)

            # Parse JSON response
            try:
                response_json = json.loads(response_text)
            except json.JSONDecodeError:
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
                if json_match:
                    response_json = json.loads(json_match.group(1))
                else:
                    raise ValueError(f"Could not parse JSON from LLM response: {response_text[:200]}")

            logger.debug(f"LLM response parsed: {list(response_json.keys())}")

            # Calculate derived scores using config
            if derived_scores_config:
                logger.debug(f"Calculating {len(derived_scores_config)} derived scores")
                response_json = _calculate_derived_scores(response_json, derived_scores_config)

            # Create Phoenix evaluations using config
            if evaluations_config:
                logger.debug(f"Creating {len(evaluations_config)} Phoenix evaluations")
                evaluations = _create_phoenix_evaluations(response_json, evaluations_config)
            else:
                # Fallback: create evaluations from all numeric/boolean fields
                logger.warning("No evaluations_config - creating default evaluations from schema")
                evaluations = []
                for field_name, field_value in response_json.items():
                    if isinstance(field_value, (int, float)):
                        evaluations.append({
                            "name": field_name,
                            "score": float(field_value),
                            "label": "good" if field_value >= 0.5 else "poor",
                            "explanation": None
                        })
                    elif isinstance(field_value, bool):
                        evaluations.append({
                            "name": field_name,
                            "score": 1.0 if field_value else 0.0,
                            "label": "pass" if field_value else "fail",
                            "explanation": None
                        })

                # Always add overall if not present
                if not any(e["name"] == "overall" for e in evaluations):
                    overall_score = response_json.get("overall_score", 0.0)
                    overall_pass = response_json.get("pass", False)
                    evaluations.append({
                        "name": "overall",
                        "score": overall_score if isinstance(overall_score, (int, float)) else 0.0,
                        "label": "pass" if overall_pass else "fail",
                        "explanation": response_json.get("evaluation_notes", None)
                    })

            logger.debug(f"Created {len(evaluations)} evaluations")

            # Phoenix client expects a dict with score, label, explanation
            # (not the old EvaluationResult class)
            overall_eval = next(
                (e for e in evaluations if e["name"] == "overall"),
                {"score": 0.0, "label": "unknown", "explanation": None}
            )

            return {
                "score": overall_eval.get("score", 0.0),
                "label": overall_eval.get("label", "unknown"),
                "explanation": overall_eval.get("explanation"),
            }

        except Exception as e:
            logger.error(f"Evaluator error: {e}")
            return {
                "score": 0.0,
                "label": "error",
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
        f"Experiment complete. View results: {experiment.url if hasattr(experiment, 'url') else 'N/A'}"  # type: ignore[attr-defined]
    )

    return experiment
