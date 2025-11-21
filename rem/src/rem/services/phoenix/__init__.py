"""Phoenix observability and evaluation services for REM.

This package provides Phoenix integration for:
1. Dataset management (golden sets, evaluation datasets)
2. Experiment execution (agent runs, evaluator runs)
3. Trace retrieval and analysis
4. Label management for organizing evaluations

Two-Phase Evaluation Workflow:
==============================

Phase 1: SME Golden Set Creation
---------------------------------
Subject Matter Experts create golden datasets containing:
- input: What the agent receives (e.g., {"query": "LOOKUP person:sarah-chen"})
- reference: Expected correct output (ground truth)
- metadata: Optional context (difficulty, category, etc.)

Phase 2: Automated Evaluation
------------------------------
1. Run agents against golden set → produces agent outputs
2. Run evaluators against (input, agent_output, reference) → produces scores
3. Track results in Phoenix for analysis and iteration

This two-phase approach allows:
- SMEs to contribute domain knowledge without running agents
- Automated regression testing as agents evolve
- Systematic comparison across agent versions
- Label-based organization (by query type, difficulty, etc.)
"""

from .client import PhoenixClient
from .config import PhoenixConfig
from .prompt_labels import (
    PhoenixPromptLabels,
    setup_rem_labels,
    REM_LABELS,
)

__all__ = [
    "PhoenixClient",
    "PhoenixConfig",
    "PhoenixPromptLabels",
    "setup_rem_labels",
    "REM_LABELS",
]
