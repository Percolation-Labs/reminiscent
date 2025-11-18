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
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME, DEPLOYMENT_ENVIRONMENT
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPExporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GRPCExporter

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
            exporter = GRPCExporter(
                endpoint=settings.otel.collector_endpoint,
                timeout=settings.otel.export_timeout,
            )
        else:  # http
            exporter = HTTPExporter(
                endpoint=f"{settings.otel.collector_endpoint}/v1/traces",
                timeout=settings.otel.export_timeout,
            )

        # Add span processor
        tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

        # Set as global tracer provider
        trace.set_tracer_provider(tracer_provider)

        logger.info(
            f"OTLP exporter configured: {settings.otel.collector_endpoint} ({settings.otel.protocol})"
        )

        # Configure Phoenix if enabled
        if settings.phoenix.enabled:
            try:
                from openinference.instrumentation.pydantic_ai import PydanticAIInstrumentor

                # Phoenix exporter (OTLP compatible)
                phoenix_exporter = HTTPExporter(
                    endpoint=settings.phoenix.collector_endpoint,
                    timeout=settings.otel.export_timeout,
                )

                # Add Phoenix span processor
                tracer_provider.add_span_processor(BatchSpanProcessor(phoenix_exporter))

                # Instrument Pydantic AI with OpenInference conventions
                PydanticAIInstrumentor().instrument()

                logger.info(
                    f"Phoenix integration configured: {settings.phoenix.collector_endpoint}"
                )

            except ImportError:
                logger.warning(
                    "Phoenix instrumentation requested but openinference-instrumentation-pydantic-ai not installed. "
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
        agent_schema: Agent schema with metadata (FQN, version, etc.)
    """
    if not settings.otel.enabled or not agent_schema:
        return

    try:
        from opentelemetry import trace

        # Get current span and set attributes
        span = trace.get_current_span()
        if span.is_recording():
            fqn = agent_schema.get("json_schema_extra", {}).get("fully_qualified_name")
            version = agent_schema.get("json_schema_extra", {}).get("version", "unknown")

            if fqn:
                span.set_attribute("agent.fqn", fqn)
            if version:
                span.set_attribute("agent.version", version)

            logger.debug(f"Set agent resource attributes: fqn={fqn}, version={version}")

    except Exception as e:
        logger.warning(f"Failed to set agent resource attributes: {e}")
