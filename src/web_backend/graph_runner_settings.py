def find_deprecated_graph_runner_worker_count(config: dict) -> object | None:
    if not isinstance(config, dict):
        return None
    runner_config = config.get("graphRunner")
    if not isinstance(runner_config, dict):
        runner_config = config.get("graph_runner")
    if not isinstance(runner_config, dict):
        return None

    raw_workers = runner_config.get("workerCount")
    if raw_workers is None:
        raw_workers = runner_config.get("workers")
    if raw_workers is None or raw_workers == "":
        return None
    return raw_workers
