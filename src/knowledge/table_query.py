"""Streaming, exact numeric aggregation over source rows, never retrieval hits."""
from decimal import Decimal, localcontext
import json
import threading

from .document_types import DocumentError, TABLE_EXTENSIONS
from .source_reader import checked_source
from .workbook_reader import open_workbook


def blank(value):
    return value is None or value == ""


def checked_value(cells, column, sheet, number):
    cell = cells.get(column)
    if cell is None:
        return None
    address = f"{sheet}!{column}{number}"
    if cell["missing_cache"]:
        raise DocumentError(f"{address} 公式缺少保存的结果；请在 Excel/LibreOffice 中重算并保存后重新扫描")
    if cell["error"]:
        raise DocumentError(f"{address} 包含错误：{cell['error']}")
    return cell["value"]


def numeric(value):
    return type(value) in {int, float}


def matches(value, condition):
    op, expected = condition.op, condition.value
    if op in {"is_blank", "not_blank"}:
        return blank(value) == (op == "is_blank")
    same_type = type(value) is type(expected) or numeric(value) and numeric(expected)
    if op == "eq":
        return same_type and value == expected
    if op == "ne":
        return not (same_type and value == expected)
    if op == "contains":
        return isinstance(value, str) and expected in value
    if blank(value):
        return False
    if not same_type or isinstance(value, bool):
        raise DocumentError("比较过滤条件类型不匹配；数值不会自动转换为文本或反向转换")
    if op == "gt":
        return value > expected
    if op == "ge":
        return value >= expected
    if op == "lt":
        return value < expected
    return value <= expected


class Accumulator:
    def __init__(self, metric):
        self.metric = metric
        self.count = self.empty = 0
        self.total = Decimal(0)
        self.low = self.high = None

    def add(self, value, address):
        if self.metric.op == "count_rows":
            self.count += 1
            return
        if blank(value):
            self.empty += 1
            return
        self.count += 1
        if self.metric.op == "count":
            return
        if not numeric(value):
            raise DocumentError(f"{address} 不是数值；不会在统计中静默忽略文本、日期或布尔值")
        number = Decimal(str(value))
        self.total += number
        self.low = number if self.low is None else min(self.low, number)
        self.high = number if self.high is None else max(self.high, number)

    def result(self):
        op = self.metric.op
        if op in {"count", "count_rows"}:
            value = self.count
        elif not self.count:
            value = None
        else:
            if op == "mean":
                with localcontext() as context:
                    context.prec = 50
                    value = self.total / self.count
            else:
                value = {"sum": self.total, "min": self.low, "max": self.high}[op]
            value = str(value)  # Decimal string avoids losing cents in JSON float conversion.
        return {"value": value, "nonblank_count": self.count, "blank_count": self.empty}


def query_table(store, config, request):
    with checked_source(store, config, request.document_id) as (path, metadata):
        if path.suffix.lower() not in TABLE_EXTENSIONS:
            raise DocumentError("表格计算仅支持 .xlsx 和 .xls")
        with open_workbook(path, config, threading.Event()) as book, localcontext() as decimal_context:
            # Covers the full finite IEEE float exponent range plus 1M additions.
            decimal_context.prec = 700
            groups, scanned, matched, last_row = {}, 0, 0, None
            if not request.group_by:
                groups[()] = ({}, [Accumulator(metric) for metric in request.metrics])
            for number, row in book.rows(request.sheet, request.start_row, request.end_row):
                last_row = number
                scanned += 1
                if scanned > 1_000_000:
                    raise DocumentError("单次统计超过 100 万行；请缩小行范围")
                # Count only data rows, not trailing/styled blank rows.
                if not any(not blank(cell["value"]) or cell["formula"] is not None for cell in row):
                    continue
                cells = {cell["column"]: cell for cell in row}
                value = lambda column: checked_value(cells, column, request.sheet, number)
                if not all(matches(value(item.column), item) for item in request.filters):
                    continue
                grouping = {column: value(column) for column in request.group_by}
                key = tuple((type(item).__name__, item) for item in grouping.values())
                if key not in groups:
                    if len(groups) >= 200:
                        raise DocumentError("分组超过 200 个；请过滤范围或减少分组列，未返回截断的统计结果")
                    groups[key] = (grouping, [Accumulator(metric) for metric in request.metrics])
                matched += 1
                for accumulator in groups[key][1]:
                    column = accumulator.metric.column
                    accumulator.add(value(column) if column else None, f"{request.sheet}!{column or ''}{number}")
            result = {**metadata, **book.metadata(), "sheet": request.sheet,
                    "start_row": request.start_row, "end_row": last_row,
                    "scanned_rows": scanned, "matched_rows": matched, "complete": True,
                    "query": request.model_dump(exclude={"action", "library_id", "document_id"}),
                    "numeric_encoding": "decimal_string; mean rounded to 50 significant digits",
                    "groups": [{"by": grouping, "metrics": {
                        accumulator.metric.name: accumulator.result() for accumulator in accumulators}}
                        for grouping, accumulators in groups.values()]}
            if len(json.dumps(result, ensure_ascii=False)) > 200000:
                raise DocumentError("分组结果超过 20 万字符，请缩小范围；未返回截断结果")
            return result
