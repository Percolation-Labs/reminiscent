"""OTEL utilities for chat routers."""

from loguru import logger


def get_tracer():
    """Get the OpenTelemetry tracer for chat completions."""
    try:
        from opentelemetry import trace
        return trace.get_tracer("rem.chat.completions")
    except Exception:
        return None


def get_current_trace_context() -> tuple[str | None, str | None]:
    """Get trace_id and span_id from current OTEL context.

    Returns:
        Tuple of (trace_id, span_id) as hex strings, or (None, None) if not available.
    """
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            trace_id = format(ctx.trace_id, '032x')
            span_id = format(ctx.span_id, '016x')
            return trace_id, span_id
    except Exception as e:
        logger.debug(f"Could not get trace context: {e}")

    return None, None
