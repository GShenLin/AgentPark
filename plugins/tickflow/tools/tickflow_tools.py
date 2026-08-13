from plugins.tickflow.runtime import (
    ADJUSTMENTS,
    FINANCIAL_STATEMENTS,
    INTRADAY_PERIODS,
    MAX_DEPTH_SYMBOLS,
    MAX_FINANCIAL_SYMBOLS,
    MAX_INSTRUMENT_SYMBOLS,
    MAX_KLINE_COUNT,
    MAX_KLINE_SYMBOLS,
    MAX_QUOTE_SYMBOLS,
    PERIODS,
    TOOL_TIMEOUT_SECONDS,
    TickFlowToolInputError,
    choice,
    integer,
    invoke_depth,
    invoke_financials,
    invoke_intraday,
    invoke_klines,
    prepare_financials,
    prepare_klines,
    run_tool,
    string_list,
    universe_detail,
)


def tickflow_get_quotes(symbols, agent=None):
    return run_tool(
        "quotes",
        lambda: {"symbols": string_list(symbols, "symbols", MAX_QUOTE_SYMBOLS)},
        lambda client, request: client.quotes.get(symbols=request["symbols"], as_dataframe=False),
    )


def tickflow_get_klines(
    symbols,
    period="1d",
    count=100,
    adjust="forward",
    start_time=None,
    end_time=None,
    agent=None,
):
    return run_tool(
        "klines",
        lambda: prepare_klines(symbols, period, count, adjust, start_time, end_time),
        invoke_klines,
    )


def tickflow_get_intraday(symbols, period="1m", count=100, agent=None):
    return run_tool(
        "intraday",
        lambda: {
            "symbols": string_list(symbols, "symbols", MAX_KLINE_SYMBOLS),
            "period": choice(period, "period", INTRADAY_PERIODS),
            "count": integer(count, "count", 1, MAX_KLINE_COUNT),
        },
        invoke_intraday,
    )


def tickflow_get_financials(
    symbols,
    statement="metrics",
    start_date=None,
    end_date=None,
    latest=True,
    agent=None,
):
    return run_tool(
        "financials",
        lambda: prepare_financials(symbols, statement, start_date, end_date, latest),
        invoke_financials,
    )


def tickflow_get_instruments(symbols, agent=None):
    return run_tool(
        "instruments",
        lambda: {"symbols": string_list(symbols, "symbols", MAX_INSTRUMENT_SYMBOLS)},
        lambda client, request: client.instruments.batch(request["symbols"]),
    )


def tickflow_list_universes(query="", limit=50, agent=None):
    def prepare():
        if not isinstance(query, str) or query != query.strip():
            raise TickFlowToolInputError("query must be a string without surrounding whitespace.")
        return {"query": query, "limit": integer(limit, "limit", 1, 100)}

    def invoke(client, request):
        universes = list(client.universes.list())
        needle = request["query"].casefold()
        if needle:
            universes = [
                item
                for item in universes
                if needle in str(item.get("id") or "").casefold()
                or needle in str(item.get("name") or "").casefold()
            ]
        return {
            "items": universes[: request["limit"]],
            "matched_total": len(universes),
            "truncated": len(universes) > request["limit"],
        }

    return run_tool("universes.list", prepare, invoke)


def tickflow_get_universe(universe_id, symbol_limit=200, agent=None):
    return run_tool(
        "universes.get",
        lambda: {
            "universe_id": string_list([universe_id], "universe_id", 1)[0],
            "symbol_limit": integer(symbol_limit, "symbol_limit", 1, 1000),
        },
        universe_detail,
    )


def tickflow_get_depth(symbols, agent=None):
    return run_tool(
        "depth",
        lambda: {"symbols": string_list(symbols, "symbols", MAX_DEPTH_SYMBOLS)},
        invoke_depth,
    )


def _tool_schema(name: str, description: str, properties: dict, required: list[str]):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


_symbols_schema = {
    "type": "array",
    "items": {"type": "string"},
    "minItems": 1,
    "description": "Canonical code.market symbols, for example 600519.SH or AAPL.US.",
}

tickflow_get_quotes_declaration = _tool_schema(
    "tickflow_get_quotes",
    "Get cached real-time TickFlow quotes for up to 500 explicit symbols per request.",
    {"symbols": {**_symbols_schema, "maxItems": MAX_QUOTE_SYMBOLS}},
    ["symbols"],
)

tickflow_get_klines_declaration = _tool_schema(
    "tickflow_get_klines",
    (
        "Get cached historical K-lines for up to 200 symbols. The account contract allows "
        "up to 10000 bars per symbol; minute K-line history may span at most 365 days."
    ),
    {
        "symbols": {**_symbols_schema, "maxItems": MAX_KLINE_SYMBOLS},
        "period": {"type": "string", "enum": list(PERIODS), "default": "1d"},
        "count": {"type": "integer", "minimum": 1, "maximum": MAX_KLINE_COUNT, "default": 100},
        "adjust": {"type": "string", "enum": list(ADJUSTMENTS), "default": "forward"},
        "start_time": {
            "type": "integer",
            "minimum": 0,
            "description": "Optional inclusive start time as a Unix timestamp in milliseconds.",
        },
        "end_time": {
            "type": "integer",
            "minimum": 0,
            "description": "Optional inclusive end time; minute K-line ranges may span at most 365 days.",
        },
    },
    ["symbols"],
)

tickflow_get_intraday_declaration = _tool_schema(
    "tickflow_get_intraday",
    "Get cached current-trading-day minute bars for up to 200 explicit symbols.",
    {
        "symbols": {**_symbols_schema, "maxItems": MAX_KLINE_SYMBOLS},
        "period": {"type": "string", "enum": list(INTRADAY_PERIODS), "default": "1m"},
        "count": {"type": "integer", "minimum": 1, "maximum": MAX_KLINE_COUNT, "default": 100},
    },
    ["symbols"],
)

tickflow_get_financials_declaration = _tool_schema(
    "tickflow_get_financials",
    "Get a cached financial statement or metrics dataset for up to 100 explicit symbols.",
    {
        "symbols": {**_symbols_schema, "maxItems": MAX_FINANCIAL_SYMBOLS},
        "statement": {"type": "string", "enum": list(FINANCIAL_STATEMENTS), "default": "metrics"},
        "start_date": {"type": "string", "format": "date"},
        "end_date": {"type": "string", "format": "date"},
        "latest": {"type": "boolean", "default": True},
    },
    ["symbols"],
)

tickflow_get_instruments_declaration = _tool_schema(
    "tickflow_get_instruments",
    "Get TickFlow instrument identity and exchange metadata for explicit symbols.",
    {"symbols": {**_symbols_schema, "maxItems": MAX_INSTRUMENT_SYMBOLS}},
    ["symbols"],
)

tickflow_list_universes_declaration = _tool_schema(
    "tickflow_list_universes",
    "List or search TickFlow market universes without expanding their symbols.",
    {
        "query": {"type": "string", "default": ""},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
    },
    [],
)

tickflow_get_universe_declaration = _tool_schema(
    "tickflow_get_universe",
    "Get one TickFlow universe with an explicit symbol output limit.",
    {
        "universe_id": {"type": "string"},
        "symbol_limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
    },
    ["universe_id"],
)

tickflow_get_depth_declaration = _tool_schema(
    "tickflow_get_depth",
    "Get cached read-only five-level TickFlow market depth for up to 200 explicit symbols.",
    {"symbols": {**_symbols_schema, "maxItems": MAX_DEPTH_SYMBOLS}},
    ["symbols"],
)

for _tool in (
    tickflow_get_quotes,
    tickflow_get_klines,
    tickflow_get_intraday,
    tickflow_get_financials,
    tickflow_get_instruments,
    tickflow_list_universes,
    tickflow_get_universe,
    tickflow_get_depth,
):
    _tool.tool_timeout_seconds = TOOL_TIMEOUT_SECONDS


__all__ = [name for name in globals() if name.startswith("tickflow_")]
