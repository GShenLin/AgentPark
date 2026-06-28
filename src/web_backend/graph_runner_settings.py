from src.value_parsing import parse_optional_int_value


class GraphRunnerSettingsError(ValueError):
    pass


def resolve_graph_runner_worker_count(config: dict, default: int = 3) -> int:
    if not isinstance(config, dict):
        return default
    runner_config = config.get("graphRunner")
    if not isinstance(runner_config, dict):
        runner_config = config.get("graph_runner")
    if not isinstance(runner_config, dict):
        return default

    raw_workers = runner_config.get("workerCount")
    if raw_workers is None:
        raw_workers = runner_config.get("workers")
    if raw_workers is None or raw_workers == "":
        return default
    try:
        worker_count = parse_optional_int_value("graphRunner.workerCount", raw_workers)
    except ValueError as exc:
        raise GraphRunnerSettingsError(f"graphRunner.workerCount must be a number: {raw_workers!r}") from exc
    if worker_count is None:
        return default
    if worker_count <= 0:
        raise GraphRunnerSettingsError("graphRunner.workerCount must be greater than zero.")
    return worker_count
