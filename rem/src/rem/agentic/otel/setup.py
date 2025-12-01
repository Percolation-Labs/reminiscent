"""
OpenTelemetry instrumentation setup for REM agents.

Provides:
- OTLP exporter configuration
- Phoenix integration (OpenInference conventions)
- Resource attributes for agent metadata
- Idempotent setup (safe to call multiple times)
"""

from typing import Any

from loguru import logger

from ...settings import settings


# Global flag to track if instrumentation is initialized
_instrumentation_initialized = False


def setup_instrumentation() -> None:
    """
    Initialize OpenTelemetry instrumentation for REM agents.

    Idempotent - safe to call multiple times, only initializes once.

    Configures:
    - OTLP exporter (HTTP or gRPC)
    - Phoenix integration if enabled
    - Pydantic AI instrumentation (automatic via agent.instrument=True)
    - Resource attributes (service name, environment, etc.)

    Environment variables:
        OTEL__ENABLED - Enable instrumentation (default: false)
        OTEL__SERVICE_NAME - Service name (default: rem-api)
        OTEL__COLLECTOR_ENDPOINT - OTLP endpoint (default: http://localhost:4318)
        OTEL__PROTOCOL - Protocol (http or grpc, default: http)
        PHOENIX__ENABLED - Enable Phoenix (default: false)
        PHOENIX__COLLECTOR_ENDPOINT - Phoenix endpoint (default: http://localhost:6006/v1/traces)
    """
    global _instrumentation_initialized

    if _instrumentation_initialized:
        logger.debug("OTEL instrumentation already initialized, skipping")
        return

    if not settings.otel.enabled:
        logger.debug("OTEL instrumentation disabled (OTEL__ENABLED=false)")
        return

    logger.info("Initializing OpenTelemetry instrumentation...")

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME, DEPLOYMENT_ENVIRONMENT
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPExporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GRPCExporter

        class SanitizingSpanExporter(SpanExporter):
            """
            Wrapper exporter that sanitizes span attributes before export.

            Removes None values that cause OTLP encoding failures like:
            - llm.input_messages.3.message.content: None
            """

            def __init__(self, wrapped_exporter: SpanExporter):
                self._wrapped = wrapped_exporter

            def _sanitize_value(self, value):
                """Recursively sanitize a value, replacing None with empty string."""
                if value is None:
                    return ""  # Replace None with empty string
                if isinstance(value, dict):
                    return {k: self._sanitize_value(v) for k, v in value.items()}
                if isinstance(value, (list, tuple)):
                    return [self._sanitize_value(v) for v in value]
                return value

            def export(self, spans: tuple[ReadableSpan, ...]) -> SpanExportResult:
                # Create sanitized copies of spans
                sanitized_spans = []
                for span in spans:
                    if span.attributes:
                        # Sanitize all attribute values - replace None with empty string
                        sanitized_attrs = {}
                        for k, v in span.attributes.items():
                            sanitized_attrs[k] = self._sanitize_value(v)
                        sanitized_spans.append(_SanitizedSpan(span, sanitized_attrs))
                    else:
                        sanitized_spans.append(span)

                return self._wrapped.export(tuple(sanitized_spans))

            def shutdown(self) -> None:
                self._wrapped.shutdown()

            def force_flush(self, timeout_millis: int = 30000) -> bool:
                return self._wrapped.force_flush(timeout_millis)

        class _SanitizedSpan(ReadableSpan):
            """ReadableSpan wrapper with sanitized attributes."""

            def __init__(self, original: ReadableSpan, sanitized_attributes: dict):
                self._original = original
                self._sanitized_attributes = sanitized_attributes

            @property
            def name(self): return self._original.name
            @property
            def context(self): return self._original.context
            @property
            def parent(self): return self._original.parent
            @property
            def resource(self): return self._original.resource
            @property
            def instrumentation_scope(self): return self._original.instrumentation_scope
            @property
            def status(self): return self._original.status
            @property
            def start_time(self): return self._original.start_time
            @property
            def end_time(self): return self._original.end_time
            @property
            def links(self): return self._original.links
            @property
            def events(self): return self._original.events
            @property
            def kind(self): return self._original.kind
            @property
            def attributes(self): return self._sanitized_attributes
            @property
            def dropped_attributes(self): return self._original.dropped_attributes
            @property
            def dropped_events(self): return self._original.dropped_events
            @property
            def dropped_links(self): return self._original.dropped_links

            def get_span_context(self): return self._original.get_span_context()

        # Create resource with service metadata
        resource = Resource(
            attributes={
                SERVICE_NAME: settings.otel.service_name,
                DEPLOYMENT_ENVIRONMENT: settings.environment,
                "service.team": settings.team,
            }
        )

        # Create tracer provider
        tracer_provider = TracerProvider(resource=resource)

        # Configure OTLP exporter based on protocol
        if settings.otel.protocol == "grpc":
            base_exporter = GRPCExporter(
                endpoint=settings.otel.collector_endpoint,
                timeout=settings.otel.export_timeout,
                insecure=settings.otel.insecure,
            )
        else:  # http
            base_exporter = HTTPExporter(
                endpoint=f"{settings.otel.collector_endpoint}/v1/traces",
                timeout=settings.otel.export_timeout,
            )

        # Wrap with sanitizing exporter to handle None values
        exporter = SanitizingSpanExporter(base_exporter)

        # Add span processor
        tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

        # Set as global tracer provider
        trace.set_tracer_provider(tracer_provider)

        logger.info(
            f"OTLP exporter configured: {settings.otel.collector_endpoint} ({settings.otel.protocol})"
        )

        # Add OpenInference span processor for Pydantic AI
        # This adds rich attributes (openinference.span.kind, input/output, etc.) to ALL traces
        # Phoenix receives these traces via the OTLP collector - no separate "Phoenix integration" needed
        # Note: The OTEL exporter may log warnings about None values in tool call messages,
        # but this is a known limitation in openinference-instrumentation-pydantic-ai
        try:
            from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor as PydanticAISpanProcessor

            tracer_provider.add_span_processor(PydanticAISpanProcessor())
            logger.info("Added OpenInference span processor for Pydantic AI")

        except ImportError:
            logger.warning(
                "openinference-instrumentation-pydantic-ai not installed - traces will lack OpenInference attributes. "
                "Install with: pip install openinference-instrumentation-pydantic-ai"
            )

        _instrumentation_initialized = True
        logger.info("OpenTelemetry instrumentation initialized successfully")

    except Exception as e:
        logger.error(f"Failed to initialize OTEL instrumentation: {e}")
        # Don't raise - allow application to continue without tracing


def set_agent_resource_attributes(agent_schema: dict[str, Any] | None = None) -> None:
    """
    Set resource attributes for agent execution.

    Called before creating agent to set span attributes with agent metadata.

    Args:
        agent_schema: Agent schema with metadata (kind, name, version, etc.)
    """
    if not settings.otel.enabled or not agent_schema:
        return

    try:
        from opentelemetry import trace

        # Get current span and set attributes
        span = trace.get_current_span()
        if span.is_recording():
            json_extra = agent_schema.get("json_schema_extra", {})
            kind = json_extra.get("kind")
            name = json_extra.get("name")
            version = json_extra.get("version", "unknown")

            if kind:
                span.set_attribute("agent.kind", kind)
            if name:
                span.set_attribute("agent.name", name)
            if version:
                span.set_attribute("agent.version", version)

            logger.debug(f"Set agent resource attributes: kind={kind}, name={name}, version={version}")

    except Exception as e:
        logger.warning(f"Failed to set agent resource attributes: {e}")
