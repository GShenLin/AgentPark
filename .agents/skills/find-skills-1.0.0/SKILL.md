---
name: find-skills
slug: guipi-find-skills
displayName: Find Skills（跨平台技能发现）
version: "2.0.0"
description: 跨平台查找、比较和安全安装 Agent Skills。覆盖本地项目与用户目录、SkillsMP、LobeHub、skills.sh、Anthropic 官方仓库、skillhub.club、agentskills.so、ClawHub、腾讯 SkillHub、ModelScope、GitHub 等来源；区分直接 API/CLI、限定站点网页检索与限定仓库检索，并在安装前执行来源核验和代码审查。
agent_created: true
xiaping_trigger: ["AI", "效率", "技能", "工具"]
xiaping_category: ["效率工具"]
xiaping_tags: ["AI工具", "技能发现"]
xiaping_eval_strategy: developer
---

# Find Skills

用于根据自然语言场景或关键词，跨本地目录、官方仓库和第三方目录发现 Agent Skills。

本技能是**发现与安装编排说明**，不是自建聚合服务。不得为了搜索临时添加新的 Python HTTP 客户端；使用宿主已有的网页检索/读取能力、官方 CLI，或项目现有网络传输边界。

## 触发场景

- 用户描述任务并询问是否有合适的 Skill。
- 用户明确说“找技能”“find skills”“搜索/安装某个 skill”。
- 用户要求比较多个 Skill 市场、可信度或安装方式。

## 必读参考

执行前按需要读取：

1. [`references/platforms.md`](references/platforms.md)：平台矩阵、检索方式与来源优先级。
2. [`references/result-contract.md`](references/result-contract.md)：统一结果字段、去重与排序规则。
3. [`references/security-and-installation.md`](references/security-and-installation.md)：安装前检查、确认与落盘规则。

不得仅凭平台展示的下载量、安全等级或营销文案跳过本地审查。

## 工作流

### 1. 理解需求

从用户输入中提取：

- 任务意图与领域；
- 中文和英文关键词；
- 运行环境、Agent 类型、操作系统；
- 是否只接受官方来源、是否允许执行脚本；
- 用户想安装到当前项目还是当前用户。

如果用户只要求“找”，先搜索和比较，不自动安装。

### 2. 先查已安装 Skill

依次检查：

1. 当前项目 `.agents/skills/`；
2. 当前用户 `~/.agents/skills/`。

读取候选目录中的 `SKILL.md` frontmatter 与正文，判断是否真正满足场景。项目级与用户级存在同名 Skill 时，项目级优先。

### 3. 分层搜索远程来源

按 `references/platforms.md` 执行，默认顺序是：

1. 官方或限定仓库来源：Anthropic 官方仓库、明确指定的发布者仓库；
2. 有官方 CLI/API 的目录：skills.sh、SkillsMP、LobeHub、腾讯 SkillHub、ClawHub；
3. 可限定域名检索的目录：skillhub.club、agentskills.so、ModelScope；
4. GitHub 通用检索及兼容来源，用于补充召回。

“覆盖平台”不等于“平台提供稳定 API”：必须在结果中标明 `access_mode`，不能把网页检索写成 API 原生集成。

### 4. 标准化、去重和排序

将候选转换为 `references/result-contract.md` 规定的字段。至少包含：

`name`、`description`、`source`、`access_mode`、`locator`、`repository`、`version`、`author`、`trust_tier`、`security_evidence`、`install_method`、`match_reason`。

去重时优先使用规范化仓库 URL 与仓库内路径；其次使用发布者、名称和版本。不得只按名称合并不同作者的 Skill。

排序综合考虑：任务匹配度、是否已安装、来源可信层级、元数据完整度、安全可审查性和维护状态。动态下载量只能作为弱信号。

### 5. 展示候选

默认给出 3 至 5 个候选，逐项展示：

- 名称和简述；
- 来源平台与访问方式；
- 为什么匹配；
- 仓库/详情定位信息；
- 已知版本和作者；
- 安全证据及未知项；
- 建议安装方式与目标目录。

如果某个平台不可访问或没有结果，应明确说明，不得伪造候选或数量。

### 6. 安装前确认

安装任何远程 Skill 前：

1. 按 `references/security-and-installation.md` 检查仓库和文件；
2. 展示来源、目标目录、将执行的命令以及关键风险；
3. 获得用户明确确认；
4. 安装后重新读取本地 `SKILL.md`，报告实际路径和版本。

默认安装目标是当前项目 `.agents/skills/<skill-name>/`。仅当用户明确要求用户级安装时，才写入 `~/.agents/skills/<skill-name>/`。

## 禁止事项

- 不得因平台声称“已扫描”“A 级”“官方认证”就跳过本地检查。
- 不得执行候选 Skill 仓库中的安装脚本、生命周期脚本或二进制文件后再询问用户。
- 不得把 OAuth token、API key、Cookie 或其他秘密写入 Skill 目录、日志或对话正文。
- 不得把网页搜索结果误标为官方 API 结果。
- 不得使用未经验证的市场规模、恶意样本数量或安全比例作为事实。
- 不得静默覆盖同名项目级 Skill。

## 简短输出示例

```text
找到 3 个候选：

1. example-skill
   来源：Anthropic 官方仓库（限定仓库检索）
   匹配：覆盖用户要求的文档处理流程
   安全：可审查；包含脚本，尚未执行
   安装：建议安装到 .agents/skills/example-skill/，需你确认

2. another-skill
   来源：skills.sh（官方 CLI）
   匹配：提供相同领域能力，但维护信息不完整
   安全：平台指标仅供参考，仍需检查仓库内容
```

## 版本记录

- **2.0.0（2026-09-29）**：拆分平台、结果合同与安全安装职责；新增 SkillsMP、LobeHub、skills.sh、Anthropic、skillhub.club、agentskills.so、ClawHub、腾讯 SkillHub 和 ModelScope 的分层覆盖；同步项目级与用户级目录语义。
- **1.9.0（2026-09-28）**：项目级技能目录迁移为 `.agents/skills/`。
