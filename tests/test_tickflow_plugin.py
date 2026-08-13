from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import zoneinfo


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins"
PLUGIN_DIR = PLUGIN_ROOT / "tickflow"


class _FakeClient:
    def __init__(self):
        self.quotes = self
        self.klines = self
        self.financials = self
        self.instruments = self
        self.universes = self
        self.depth = self
        self.calls = []

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        return [{"symbol": "600519.SH", "last_price": 1500.0, "timestamp": 1}]


def _tool_definitions():
    from nodes.agent_plugin_loader import resolve_plugin_capabilities

    return resolve_plugin_capabilities(["tickflow"], plugin_root=str(PLUGIN_ROOT)).tool_definitions


def _source_callable(name):
    return next(item.callable for item in _tool_definitions() if item.source_name == name)


def _runtime_globals(function):
    return function.__globals__["run_tool"].__globals__


def test_tickflow_plugin_resolves_local_tools_and_skill():
    from nodes.agent_plugin_loader import resolve_plugin_capabilities

    capabilities = resolve_plugin_capabilities(["tickflow"], plugin_root=str(PLUGIN_ROOT))

    assert [plugin.id for plugin in capabilities.plugins] == ["tickflow"]
    assert [skill.name for skill in capabilities.skill_definitions] == ["tickflow"]
    assert len(capabilities.tool_definitions) == 8
    assert all(item.name.startswith("plugin__tickflow__") for item in capabilities.tool_definitions)


def test_tickflow_tool_schemas_are_strict_and_contain_no_credentials():
    payload = json.dumps(
        [item.declaration for item in _tool_definitions()],
        ensure_ascii=False,
    )

    assert "api_key" not in payload.casefold()
    for item in _tool_definitions():
        assert item.declaration["function"]["parameters"]["additionalProperties"] is False


def test_tickflow_tool_schemas_match_account_limits():
    declarations = {
        item.source_name: item.declaration["function"]["parameters"]["properties"]
        for item in _tool_definitions()
    }

    assert declarations["tickflow_get_quotes"]["symbols"]["maxItems"] == 500
    assert declarations["tickflow_get_klines"]["symbols"]["maxItems"] == 200
    assert declarations["tickflow_get_klines"]["count"]["maximum"] == 10000
    assert declarations["tickflow_get_intraday"]["symbols"]["maxItems"] == 200
    assert declarations["tickflow_get_intraday"]["count"]["maximum"] == 10000
    assert declarations["tickflow_get_financials"]["symbols"]["maxItems"] == 100
    assert declarations["tickflow_get_depth"]["symbols"]["maxItems"] == 200


def test_tickflow_quotes_forwards_validated_symbols_without_exposing_key(monkeypatch, tmp_path):
    function = _source_callable("tickflow_get_quotes")
    fake = _FakeClient()
    runtime_globals = _runtime_globals(function)
    monkeypatch.setitem(runtime_globals, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setitem(runtime_globals, "get_client", lambda: fake)

    result = function(symbols=["600519.SH"])

    assert result["status"] == "ok"
    assert result["source"] == "tickflow"
    assert result["request"] == {"symbols": ["600519.SH"]}
    assert result["data"][0]["last_price"] == 1500.0
    assert result["cache"]["status"] == "miss"
    assert fake.calls == [("get", {"symbols": ["600519.SH"], "as_dataframe": False})]
    assert "api_key" not in json.dumps(result).casefold()
    assert (tmp_path / ".cache" / "tickflow" / "responses.sqlite3").is_file()


def test_tickflow_cache_is_shared_and_checked_before_client(monkeypatch, tmp_path):
    function = _source_callable("tickflow_get_quotes")
    fake = _FakeClient()
    runtime_globals = _runtime_globals(function)
    monkeypatch.setitem(runtime_globals, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setitem(runtime_globals, "get_client", lambda: fake)

    first = function(symbols=["600519.SH"])
    monkeypatch.setitem(
        runtime_globals,
        "get_client",
        lambda: (_ for _ in ()).throw(AssertionError("cache hit must not initialize the client")),
    )
    second = function(symbols=["600519.SH"])

    assert first["cache"]["status"] == "miss"
    assert second["cache"]["status"] == "hit"
    assert first["retrieved_at"] == second["retrieved_at"]
    assert first["data"] == second["data"]
    assert len(fake.calls) == 1


def test_tickflow_cache_coalesces_parallel_node_misses(tmp_path):
    from plugins.tickflow.cache import get_or_fetch

    fetch_count = 0

    def fetch():
        nonlocal fetch_count
        fetch_count += 1
        return {"600519.SH": {"timestamp": [1], "close": [1500.0]}}

    def query(_index):
        return get_or_fetch(
            str(tmp_path),
            "instruments",
            {"symbols": ["600519.SH"]},
            fetch,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(query, range(8)))

    assert fetch_count == 1
    assert sum(item.cache_hit for item in results) == 7
    assert all(item.data == results[0].data for item in results)


def test_tickflow_quotes_rejects_oversized_symbol_batch_before_client_use(monkeypatch):
    function = _source_callable("tickflow_get_quotes")
    monkeypatch.setitem(
        _runtime_globals(function),
        "get_client",
        lambda: (_ for _ in ()).throw(AssertionError("client must not be used")),
    )

    result = function(symbols=[f"{index:06d}.SH" for index in range(501)])

    assert result["status"] == "invalid_arguments"
    assert result["error_type"] == "invalid_arguments"


def test_tickflow_minute_klines_enforce_10000_bars_and_365_days(monkeypatch):
    function = _source_callable("tickflow_get_klines")
    monkeypatch.setitem(
        _runtime_globals(function),
        "get_client",
        lambda: (_ for _ in ()).throw(AssertionError("client must not be used")),
    )

    too_many_bars = function(symbols=["600519.SH"], period="5m", count=10001)
    too_wide = function(
        symbols=["600519.SH"],
        period="5m",
        count=10000,
        start_time=0,
        end_time=366 * 24 * 60 * 60 * 1000,
    )

    assert too_many_bars["status"] == "invalid_arguments"
    assert "10000" in too_many_bars["error"]
    assert too_wide["status"] == "invalid_arguments"
    assert "365 days" in too_wide["error"]

    from plugins.tickflow.runtime import prepare_klines

    daily = prepare_klines(
        ["600519.SH"],
        "1d",
        10000,
        "forward",
        0,
        366 * 24 * 60 * 60 * 1000,
    )
    assert daily["period"] == "1d"


def test_tickflow_klines_use_single_and_200_symbol_batch_endpoints():
    from plugins.tickflow.runtime import invoke_klines

    class Klines:
        def __init__(self):
            self.calls = []

        def get(self, symbol, **kwargs):
            self.calls.append(("single", symbol, kwargs))
            return {"timestamp": [1]}

        def batch(self, symbols, **kwargs):
            self.calls.append(("batch", symbols, kwargs))
            return {symbol: {"timestamp": [1]} for symbol in symbols}

    class Client:
        def __init__(self):
            self.klines = Klines()

    request = {
        "symbols": ["600519.SH"],
        "period": "5m",
        "count": 10000,
        "adjust": "forward",
        "start_time": None,
        "end_time": None,
    }
    client = Client()

    invoke_klines(client, request)
    request["symbols"] = [f"{index:06d}.SH" for index in range(200)]
    invoke_klines(client, request)

    assert client.klines.calls[0][0] == "single"
    assert client.klines.calls[1][0] == "batch"
    assert client.klines.calls[1][2]["batch_size"] == 200


def test_tickflow_skill_documents_alias_without_secret_material():
    content = (PLUGIN_DIR / "skills" / "tickflow" / "SKILL.md").read_text(encoding="utf-8")

    assert ".auth/api-keys/aliases.json" in content
    assert "TickFlow" in content
    assert "10000 bars" in content
    assert "200 symbols/request" in content
    assert ".cache/tickflow/responses.sqlite3" in content
    assert "tk_" not in content


def test_tickflow_runtime_reads_only_the_named_workspace_alias(monkeypatch, tmp_path):
    import plugins.tickflow.runtime as tickflow_runtime

    store_path = tmp_path / ".auth" / "api-keys" / "aliases.json"
    store_path.parent.mkdir(parents=True)
    store_path.write_text(
        json.dumps({"Other": "other-value", "TickFlow": "test-tickflow-value"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(tickflow_runtime, "get_workspace_root", lambda: str(tmp_path))

    assert tickflow_runtime.load_api_key() == "test-tickflow-value"


def test_tickflow_runtime_import_uses_bundled_tzdata_when_system_database_is_missing(monkeypatch):
    import plugins.tickflow.runtime as tickflow_runtime

    original_path = tuple(zoneinfo.TZPATH)
    observed = {}
    real_import = tickflow_runtime.importlib.import_module

    def missing_system_zone(_key):
        raise zoneinfo.ZoneInfoNotFoundError("simulated missing system time zone database")

    def import_with_bundled_zoneinfo(name):
        if name != "tickflow":
            return real_import(name)
        observed["path"] = tuple(zoneinfo.TZPATH)
        return object()

    calls = 0

    def zoneinfo_after_fallback(key):
        nonlocal calls
        calls += 1
        if calls == 1:
            return missing_system_zone(key)
        return key

    monkeypatch.setattr(zoneinfo, "ZoneInfo", zoneinfo_after_fallback)
    monkeypatch.setattr(tickflow_runtime.importlib, "import_module", import_with_bundled_zoneinfo)

    assert tickflow_runtime._import_tickflow_api() is not None
    assert any("tzdata" in path.casefold() for path in observed["path"])
    assert tuple(zoneinfo.TZPATH) == original_path
