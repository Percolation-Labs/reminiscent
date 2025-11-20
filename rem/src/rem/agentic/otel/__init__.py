"""OpenTelemetry instrumentation for REM agents."""

from .setup import setup_instrumentation, set_agent_resource_attributes

__all__ = ["setup_instrumentation", "set_agent_resource_attributes"]
