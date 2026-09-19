# Knowledge：Word、Excel

目录扫描支持 `.pdf`、`.md`、`.markdown`、`.txt`、`.docx`、`.doc`、`.xlsx`、`.xls`。
Office 的 `~$` 临时锁文件不进入索引。更新后对现有知识库运行增量扫描即可发现新格式；无需删除已有 PDF/文本向量。

## 配置与部署

Python 依赖随 `pip install -e .` 安装：python-docx、openpyxl、xlrd、defusedxml。
旧版 `.doc` 额外需要 LibreOffice：默认寻找 PATH 或 Windows 标准安装路径，也可设置
`AGENTPARK_LIBREOFFICE` 为 soffice 可执行文件绝对路径。Windows 优先 `soffice.com`。
转换使用源文件副本、独立临时用户配置、高宏安全级别和独立进程，120 秒超时，不修改原文件。
缺少转换器、加密、损坏或转换失败均显示为文档解析错误；修复环境后“重试失败文件”。

设置中的 **Excel 表头行** 默认为 0，不猜测表头。若同一库的工作表有统一表头行，可在创建时指定行号，
后续数据块会附上该行列名；其值与分块配置一样创建后固定。表头位置不统一时用坐标读取，统计时明确指定数据起始行。

## 内容与出处

- Word 按正文顺序提取段落和表格，保留标题上下文，并读取独立页眉/页脚。
  出处包含文档部分、段落编号或表格/行位置，不伪造渲染页码。
- Excel 按工作表/行读取，相邻完整行合并到片段上限，长行按字符分块；出处包含工作表与行列范围。
  表头、公式文本、保存的结果可参与索引；缺失缓存和 Excel 错误值有可见警告。
- 所有源文本都不作为工具指令。图片、图表、宏不参与解析；Word 文本框、修订记录等非普通正文不宣称完整支持。

旧索引增加 `chunks.location` 字段，保留原片段 ID、向量和发布状态。扫描与解析失败不发布半份文档。
原文读取/计算通过已登记 `document_id` 解析路径，验证库权限、目录边界、文件大小和修改时间。
文件在扫描后或读取期间变化时拒绝返回结果，提示重新扫描。原文是当前已扫描版本，返回 `index_current` 表明索引是否追上。

## Agent Skill

仍使用一个 `knowledge` Skill，暴露四个用途明确的工具：

1. `list`：列库或分页列已扫描文档。
2. `search`：混合、语义或关键词检索，返回带出处的片段。
3. `read`：读取索引片段，或分页读取 Word/PDF/文本原文、列 Excel 工作表和读取行。
4. `table`：对指定工作表与行范围执行显式过滤、分组、count/sum/mean/min/max。

计算契约和示例见 [Skill 表格指南](../skills/knowledge/references/tables.md)。不以检索片段代替全表统计，不执行模型提供的代码。
所有统计包含隐藏行/列，不自动填充合并单元格。公式不重算，只用文件保存值；XLSX 缺缓存参与统计时报错。
XLS 只提供保存值，无法分辨公式和检查其缓存状态。缓存是否过期须由用户重算保存确认。

## 资源边界

XLSX 使用 read-only 行迭代；XLS 一次加载一张工作表并释放。Office 解压内容上限为配置单文件上限与 256 MB 的较小值，
压缩包最多 100000 项。每次工作表读取最多 500 万单元格；统计最多 100 万扫描行、200 分组，超限报错，不输出部分总计。
原文读取最多 100 行/片段，返回最多约 20 万字符，通过 `next_offset` 分页。长文档仍有原始解析器的内存开销，
解析进程沿用 Knowledge 的进程隔离和暂停/断点流程；不宣称支持无限大小的 Office 文件。

运行验证：`python -m pytest tests/test_knowledge_office.py tests/test_knowledge_skill.py tests/test_knowledge_pipeline.py`。
`tests/fixtures/knowledge/legacy.xls` 和 `legacy.doc` 为项目测试生成的人工数据，无用户资料。
DOC 集成测试在缺少 LibreOffice 的环境中会明确跳过，其他格式不依赖它。
