"""The trace and log exporters prepare only a collection they create; an existing one is used as is.

createIndexes waits for the build, so an index or TTL on a large existing collection would block trace export or
startup for hours, and a TTL index on an existing plain collection would expire its old documents.
"""

import logging
from queue import Queue
from unittest.mock import MagicMock, call

import pytest
from pymongo.errors import CollectionInvalid, OperationFailure

from blocks_genesis._lmt.mongo_log_exporter import RETENTION_SECONDS, MongoBatchLogger
from blocks_genesis._lmt.mongo_trace_exporter import MongoDBTraceExporter

SECRET = "mongodb://user:sentinel-pw-3e1a@db.internal"
TRACE_LOGGER = "blocks_genesis._lmt.mongo_trace_exporter"
RACES = [
    CollectionInvalid("collection tid already exists"),
    OperationFailure("Collection already exists", code=48),
]
PLAIN_LOG_WARNING = (
    "[MongoBatchLogger] log collection is a plain collection, not time-series: "
    "used as is, without expiry; migrate it to time-series\n"
)


# ------------------------------------------------------------------ trace exporter


def _exp():
    e = MongoDBTraceExporter.__new__(MongoDBTraceExporter)
    e._service_name = "svc"
    e._db = MagicMock()
    e._queue = Queue(maxsize=100)
    e._batch_size = 1000
    e._flush_interval = 0.01
    e._client = MagicMock()
    e._stop_event = MagicMock()
    e._worker_thread = MagicMock()
    e._ensured_collections = set()
    return e


def _trace_exp(listed):
    """A trace exporter whose database lists `listed` for every collection-name filter."""
    e = _exp()
    coll = MagicMock()
    e._db.__getitem__.return_value = coll
    e._db.list_collections.return_value = listed
    return e, coll


def _flush_twice(e, name="tid"):
    e._flush_to_mongo({name: [{}]})
    e._flush_to_mongo({name: [{}]})


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.name == TRACE_LOGGER and r.levelno == logging.WARNING]


def _assert_trace_collection_untouched(e, coll):
    coll.create_index.assert_not_called()
    e._db.create_collection.assert_not_called()
    e._db.drop_collection.assert_not_called()
    coll.drop.assert_not_called()


def test_existing_plain_trace_collection_is_used_as_is(capsys):
    e, coll = _trace_exp([{"name": "tid", "type": "collection"}])

    _flush_twice(e)

    _assert_trace_collection_untouched(e, coll)
    assert coll.insert_many.call_count == 2
    assert e._db.list_collections.call_count == 1
    assert capsys.readouterr().out == ""


def test_existing_time_series_trace_collection_is_used_as_is(capsys):
    e, coll = _trace_exp([{"name": "tid", "type": "timeseries"}])

    _flush_twice(e)

    _assert_trace_collection_untouched(e, coll)
    assert coll.insert_many.call_count == 2
    assert e._db.list_collections.call_count == 1
    assert capsys.readouterr().out == ""


def test_missing_trace_collection_is_created_then_indexed(capsys):
    e, coll = _trace_exp([])
    order = []
    e._db.create_collection.side_effect = lambda *a, **k: order.append("create")
    coll.create_index.side_effect = lambda *a, **k: order.append("index")
    coll.insert_many.side_effect = lambda *a, **k: order.append("insert")

    _flush_twice(e)

    e._db.create_collection.assert_called_once_with(
        "tid",
        timeseries={"timeField": "Timestamp", "metaField": "TraceId", "granularity": "minutes"},
        expireAfterSeconds=RETENTION_SECONDS,
    )
    assert coll.create_index.call_args_list == [call([("TraceId", 1), ("Timestamp", -1)], name="tid_Index")]
    assert order == ["create", "index", "insert", "insert"]
    assert e._db.list_collections.call_count == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("race", RACES)
def test_trace_collection_created_by_someone_else_first_is_used_as_is(race, caplog, capsys):
    e, coll = _trace_exp([])
    e._db.create_collection.side_effect = race

    e._flush_to_mongo({"tid": [{}]})

    coll.create_index.assert_not_called()
    coll.insert_many.assert_called_once()
    assert _warnings(caplog) == []
    assert e._db.list_collections.call_count == 1
    assert capsys.readouterr().out == ""


def test_each_trace_collection_is_checked_once_per_process(capsys):
    e = _exp()
    coll = MagicMock()
    e._db.__getitem__.return_value = coll
    kinds = {"t1": "collection", "t2": "timeseries"}
    e._db.list_collections.side_effect = lambda filter: [{"name": filter["name"], "type": kinds[filter["name"]]}]

    _flush_twice(e, "t1")
    _flush_twice(e, "t2")

    assert e._db.list_collections.call_args_list == [call(filter={"name": "t1"}), call(filter={"name": "t2"})]
    coll.create_index.assert_not_called()
    assert coll.insert_many.call_count == 4
    assert capsys.readouterr().out == ""


def test_trace_id_index_failure_on_a_created_collection_is_logged_and_not_retried(caplog, capsys):
    e, coll = _trace_exp([])
    coll.create_index.side_effect = OperationFailure(SECRET)

    _flush_twice(e)

    assert coll.insert_many.call_count == 2
    assert coll.create_index.call_count == 1
    assert any("OperationFailure" in m and "tid" in m for m in _warnings(caplog))
    assert "sentinel-pw" not in caplog.text
    assert capsys.readouterr().out == ""


def test_trace_collection_check_failure_is_logged_without_detail_and_export_continues(caplog, capsys):
    e, coll = _trace_exp([])
    e._db.list_collections.side_effect = OperationFailure(SECRET)

    e._flush_to_mongo({"tid": [{}]})

    e._db.create_collection.assert_not_called()
    coll.create_index.assert_not_called()
    coll.insert_many.assert_called_once()
    assert any("OperationFailure" in m and "tid" in m for m in _warnings(caplog))
    assert "sentinel-pw" not in caplog.text
    assert capsys.readouterr().out == ""


# ------------------------------------------------------------------ log exporter


def _logger():
    return MongoBatchLogger.__new__(MongoBatchLogger)


def _db(names, kind=None):
    """A database whose collection 'svc' is listed by name as `names`, and has type `kind` when listed."""
    db = MagicMock()
    coll = MagicMock()
    coll.list_indexes.return_value = []
    db.__getitem__.return_value = coll
    db.list_collection_names.return_value = names
    db.list_collections.side_effect = lambda **k: iter([{"name": "svc", "type": kind}] if kind else [])
    return db, coll


def _assert_log_collection_untouched(db, coll):
    coll.create_index.assert_not_called()
    coll.list_indexes.assert_not_called()
    db.drop_collection.assert_not_called()
    coll.drop.assert_not_called()


def test_existing_plain_log_collection_is_used_as_is(capsys):
    db, coll = _db(["svc"], "collection")

    _logger()._create_collection_for_logs(db, "svc")

    _assert_log_collection_untouched(db, coll)
    db.create_collection.assert_not_called()
    assert capsys.readouterr() == ("", PLAIN_LOG_WARNING)


def test_existing_time_series_log_collection_is_used_as_is(capsys):
    db, coll = _db(["svc"], "timeseries")

    _logger()._create_collection_for_logs(db, "svc")

    _assert_log_collection_untouched(db, coll)
    db.create_collection.assert_not_called()
    assert capsys.readouterr() == ("", "")


def test_missing_log_collection_is_created_then_indexed(capsys):
    db, coll = _db([])

    _logger()._create_collection_for_logs(db, "svc")

    db.create_collection.assert_called_once_with(
        "svc",
        timeseries={"timeField": "Timestamp", "metaField": "TenantId", "granularity": "minutes"},
        expireAfterSeconds=RETENTION_SECONDS,
    )
    assert coll.create_index.call_args_list == [
        call(
            [("TenantId", 1), ("Timestamp", -1)],
            name="svc_Index",
            partialFilterExpression={"TenantId": {"$exists": True}},
        )
    ]
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("race", RACES)
def test_log_collection_created_by_someone_else_first_is_used_as_is(race, capsys):
    db, coll = _db([], "timeseries")
    db.create_collection.side_effect = race

    _logger()._create_collection_for_logs(db, "svc")

    _assert_log_collection_untouched(db, coll)
    assert capsys.readouterr() == ("", "")


def test_log_collection_check_failure_goes_to_stderr_without_detail(capsys):
    db, coll = _db([])
    db.list_collection_names.side_effect = OperationFailure(SECRET)

    _logger()._create_collection_for_logs(db, "svc")

    db.create_collection.assert_not_called()
    coll.create_index.assert_not_called()
    assert capsys.readouterr() == ("", "[MongoBatchLogger] log collection setup failed (OperationFailure)\n")
