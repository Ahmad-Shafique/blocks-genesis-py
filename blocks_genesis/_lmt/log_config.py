import logging

from opentelemetry.sdk.resources import SERVICE_NAME, Resource

from blocks_genesis._core.secret_loader import get_blocks_secret
from blocks_genesis._lmt.mongo_log_exporter import MongoHandler, TraceContextFilter
from blocks_genesis._lmt.otlp import create_log_exporter, otlp_enabled


def create_otlp_log_handler() -> logging.Handler:
    """Builds a handler that sends log records over OTLP.

    The handler adds the active trace and span ids to each record. Attributes set on the record by
    TraceContextFilter, such as the tenant id, go out as log attributes.
    """
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

    provider = LoggerProvider(
        resource=Resource.create({SERVICE_NAME: get_blocks_secret().ServiceName})
    )
    provider.add_log_record_processor(BatchLogRecordProcessor(create_log_exporter()))
    return LoggingHandler(level=logging.INFO, logger_provider=provider)


def configure_logger():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(TenantId)s] [%(TraceId)s] %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    mongo_handler = MongoHandler()

    # Add context filter to enrich log records
    context_filter = TraceContextFilter()
    console_handler.addFilter(context_filter)
    mongo_handler.addFilter(context_filter)

    logger.handlers.clear()
    logger.addHandler(console_handler)
    logger.addHandler(mongo_handler)

    if otlp_enabled():
        otlp_handler = create_otlp_log_handler()
        otlp_handler.addFilter(context_filter)
        logger.addHandler(otlp_handler)
