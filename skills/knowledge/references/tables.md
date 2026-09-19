# Excel 阅读和统计

先用 `list(library_id)` 或 `search` 取得 `document_id`，再用 `read(library_id, document_id)` 列出工作表。
读取工作表前几行，确认表头位置和列含义。列标识始终用大写字母 A、B、AA；不自动猜测表头，不把重复列名合并。

`table` 参数：`library_id`、`document_id`、`sheet`、`start_row`（默认 1）、可选 `end_row`（含末行）。
若第一行是表头，明确传 `start_row: 2`；末尾合计行也必须通过行范围或过滤排除，避免重复统计。

- `filters`：最多 12 个条件，全部满足才保留。每项 `{column, op, value}`。
  `op` 可为 `eq/ne/gt/ge/lt/le/contains/is_blank/not_blank`；空值条件不传 value。
  数值和文本不自动互转；日期以 ISO 字符串返回，日期条件使用相同格式。
- `group_by`：最多 3 个列字母，按其原始值分组。超过 200 个组报错，须缩小范围。
- `metrics`：最多 12 项，每项 `{name, op, column}`。`op` 为 `count_rows/count/sum/mean/min/max`。
  `count_rows` 不传 column，计算非空数据行数；`count` 计算指定列非空单元格数。
  其他操作要求数值，跳过空白并报告 `blank_count`，遇文本、日期、布尔值或 Excel 错误会报错。

例如按 A 列地区汇总 C 列销售额，排除 B 列已取消记录：

```json
{
  "library_id": "实际知识库 ID",
  "document_id": 12,
  "sheet": "销售",
  "start_row": 2,
  "filters": [{"column": "B", "op": "ne", "value": "已取消"}],
  "group_by": ["A"],
  "metrics": [
    {"name": "销售额", "op": "sum", "column": "C"},
    {"name": "订单数", "op": "count_rows"}
  ]
}
```

统计包含隐藏行/列/工作表，不自动填充合并单元格，只有合并区域左上角有值。
计算使用十进制；数值结果以字符串返回，均值保留最多 50 位有效数字。没有数值时结果为 null；不能解释成 0。
返回 `complete`、实际扫描/匹配行数、查询参数和源文件时间，回答应交代统计范围、筛选条件和空白数量。

公式只读取文件已保存的计算结果，不执行公式、宏或外部链接。XLSX 同时显示公式和缓存；缺失缓存或错误值若参与计算则报错，不能把它们当作零。
XLS 只能读取保存值，不能识别公式或判断缓存缺失；报告该限制。缓存可能过期，需要用户在 Excel/LibreOffice 中重算保存并增量扫描后再统计。
需要跨表比较时分别对明确范围计算后比较结果；此工具不执行任意代码或自动关联不同表。
单次最多扫描 100 万行/500 万单元格，超限报错，不返回冒充全表结果的截断值。
