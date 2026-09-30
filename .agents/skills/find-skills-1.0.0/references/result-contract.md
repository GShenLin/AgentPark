# 统一结果合同

所有平台结果必须先标准化，再参与去重、排序和展示。

## 字段

```yaml
name: string                 # Skill 声明名称
description: string          # 简述，不以营销文案代替能力说明
source: string               # platforms.md 中的 source id
source_label: string         # 给用户看的平台名称
access_mode: local|api|cli|site-search|repo-search|github-search
locator: string              # 详情页、仓库路径或 CLI 返回的稳定标识
repository: string|null      # 规范化仓库 URL；未知时为 null
repository_path: string|null # 仓库内 SKILL.md 所在目录
author: string|null
version: string|null
license: string|null
installed: boolean
installed_path: string|null
trust_tier: official|traceable|community|unknown
inspectable: boolean         # 是否能在安装前读取完整内容
security_evidence:           # 只记录有出处的事实
  - type: string
    value: string
    provenance: string
install_method: string|null  # 建议方法；不是已获执行许可
match_reason: string
warnings:
  - string
```

未知字段使用 `null`、`false` 或空列表，禁止用猜测值填充。

## 规范化

- `source` 使用平台表中的稳定 id，不能都写成含混的“SkillHub”。
- 仓库 URL 去除末尾 `/`、`.git` 和无关查询参数，并统一主机名大小写。
- `repository_path` 使用 `/` 分隔，指向包含 `SKILL.md` 的目录。
- 版本仅来自 frontmatter、发布记录或平台明确字段；没有就留空。
- 下载量、评分和安全等级若展示，必须放入带 `provenance` 的证据或扩展指标中。

## 去重键

按以下顺序判断同一份 Skill：

1. `normalized_repository + repository_path`；
2. 平台提供的不可变项目 id；
3. `author + name + version`；
4. 内容哈希（已经安全下载到临时目录时）。

名称相同但作者或仓库不同，不自动合并。合并多个索引记录时保留所有来源证据，并选择可追溯到原仓库的记录作为主记录。

## 本地覆盖规则

- 项目级 `.agents/skills/<name>/` 优先于用户级 `~/.agents/skills/<name>/`。
- 已安装版本不等于最新或安全版本；仍要报告路径和版本。
- 远程同名候选不得静默覆盖项目级目录。

## 排序

先过滤与需求无关或不可审查且要求安装的候选，再按以下信号排序：

1. 任务匹配度；
2. 已安装且路径有效；
3. 官方发布者或可追溯原仓库；
4. 元数据完整和许可证清晰；
5. 最近维护证据；
6. 平台热度等弱信号。

任何单一平台的评分、下载量或安全标签都不能覆盖本地安全检查结果。
