"""Log documents carry Exception and ServiceName, the fields Blocks-OS LMT reads (genesis-net MongoDBDynamicSink)."""

import logging
import sys
import threading
from queue import Queue
from unittest.mock import MagicMock

from blocks_genesis._lmt.mongo_log_exporter import MongoBatchLogger, MongoHandler, TraceContextFilter

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig"
GRANT_ID = "dg_" + "a" * 64


def _bl():
    b = MongoBatchLogger.__new__(MongoBatchLogger)
    b.batch_size = 1
    b.flush_interval_sec = 0.01
    b.collection = MagicMock()
    b.queue = Queue()
    b._dropped = 0
    b._dropped_lock = threading.Lock()
    b._last_drop_report = float("-inf")
    b._service_name = "svc"
    return b


def _record(msg="m", args=None, exc_info=None):
    record = logging.getLogger("t").makeRecord("t", logging.ERROR, __file__, 1, msg, args, exc_info)
    record.TenantId = "tid"
    record.TraceId = "tr"
    record.SpanId = "sp"
    return record


def _doc(record):
    b = _bl()
    b.enqueue(record)
    return b.queue.get_nowait()


def test_record_with_exc_info_stores_the_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        record = _record(exc_info=sys.exc_info())
    text = _doc(record)["Exception"]
    assert text.startswith("Traceback (most recent call last)")
    assert text.endswith("ValueError: boom")


def test_record_without_exception_stores_empty_string():
    assert _doc(_record())["Exception"] == ""


def test_exc_info_of_none_stores_empty_string():
    assert _doc(_record(exc_info=(None, None, None)))["Exception"] == ""


def test_already_formatted_exc_text_is_reused():
    record = _record()
    record.exc_text = "formatted"
    assert _doc(record)["Exception"] == "formatted"


def test_exception_text_hides_jwts_and_grant_ids():
    try:
        raise ValueError(f"bad token {JWT} for grant {GRANT_ID}")
    except ValueError:
        record = _record(exc_info=sys.exc_info())
    text = _doc(record)["Exception"]
    assert JWT not in text
    assert GRANT_ID not in text
    assert "[REDACTED]" in text


def test_unformattable_exception_keeps_the_record():
    # A value that is not an exception makes formatException raise; only the Exception field is lost.
    record = _record("still logged", exc_info=(ValueError, "not an exception", None))
    doc = _doc(record)
    assert doc["Message"] == "still logged"
    assert doc["Exception"] == ""


def test_document_names_the_service():
    assert _doc(_record())["ServiceName"] == "svc"


def test_message_is_unchanged():
    record = _record("token %s", (JWT,))
    doc = _doc(record)
    assert doc["Message"] == record.getMessage()
    assert JWT in doc["Message"]


def test_logger_exception_reaches_the_document():
    fake = _bl()
    previous = MongoHandler._mongo_logger
    MongoHandler._mongo_logger = fake
    logger = logging.getLogger("g2.test")
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = MongoHandler()
    handler.addFilter(TraceContextFilter())
    logger.addHandler(handler)
    try:
        try:
            raise RuntimeError("worker crashed")
        except RuntimeError:
            logger.exception("failed")
        doc = fake.queue.get_nowait()
        assert doc["Exception"]
        assert doc["Exception"].endswith("RuntimeError: worker crashed")
    finally:
        logger.removeHandler(handler)
        handler.close()
        MongoHandler._mongo_logger = previous
