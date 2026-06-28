import pytest

from src.web_backend.graph_runner_settings import (
    GraphRunnerSettingsError,
    resolve_graph_runner_worker_count,
)


def test_graph_runner_worker_count_defaults_when_not_configured():
    assert resolve_graph_runner_worker_count({}) == 3
    assert resolve_graph_runner_worker_count({"graphRunner": {}}) == 3


def test_graph_runner_worker_count_accepts_camel_and_snake_case_settings():
    assert resolve_graph_runner_worker_count({"graphRunner": {"workerCount": "2"}}) == 2
    assert resolve_graph_runner_worker_count({"graph_runner": {"workers": 4}}) == 4


def test_graph_runner_worker_count_accepts_large_configured_value():
    assert resolve_graph_runner_worker_count({"graphRunner": {"workerCount": 30}}) == 30


def test_graph_runner_worker_count_rejects_invalid_configured_value():
    with pytest.raises(GraphRunnerSettingsError, match="must be a number"):
        resolve_graph_runner_worker_count({"graphRunner": {"workerCount": "many"}})

    with pytest.raises(GraphRunnerSettingsError, match="greater than zero"):
        resolve_graph_runner_worker_count({"graphRunner": {"workerCount": 0}})


def test_graph_runner_worker_count_rejects_boolean_value():
    with pytest.raises(GraphRunnerSettingsError, match="workerCount"):
        resolve_graph_runner_worker_count({"graphRunner": {"workerCount": True}})
