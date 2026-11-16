"""Opt-in OpenTelemetry tracing to Application Insights.

Active only when ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set. Otherwise OpenTelemetry's
no-op tracer is used (no overhead, no network). Spans carry latency, counts and token usage,
never question, document or answer text.
"""

from opentelemetry import trace

from workplace_agent.config import Settings

_configured = False


def get_tracer() -> trace.Tracer:
    return trace.get_tracer("workplace_agent")


def configure_tracing(settings: Settings) -> bool:
    """Enable Azure Monitor tracing once if a connection string is set; return whether on."""
    global _configured
    connection_string = settings.applicationinsights_connection_string
    if not connection_string:
        return False
    if not _configured:
        from azure.monitor.opentelemetry import configure_azure_monitor

        # Logging export stays off: the per-document JSON lines on stderr are our log.
        configure_azure_monitor(
            connection_string=connection_string,
            disable_logging=True,
            disable_metrics=True,
            enable_live_metrics=False,
        )
        _configured = True
    return True


def flush_tracing() -> None:
    """Export pending spans before the process exits (no-op when tracing is off)."""
    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if callable(force_flush):
        force_flush()
