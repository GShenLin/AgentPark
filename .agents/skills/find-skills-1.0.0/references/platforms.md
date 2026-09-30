# 平台矩阵与检索策略

本文件定义 Find Skills 的远程来源边界。入口或命令可能随平台更新；执行时应优先核对平台当前官方帮助，不凭记忆拼接下载 URL。

## 访问方式定义

- `api`：平台公开、可核验的搜索 API。通过宿主已有网络能力或项目既有传输边界访问。
- `cli`：平台维护的 CLI 搜索/安装流程。执行安装命令前仍需用户确认。
- `site-search`：限定官方域名的网页检索与详情页读取，不代表存在公开 API。
- `repo-search`：限定 owner/repository 的仓库检索。
- `github-search`：GitHub 通用补充检索，可信度取决于具体发布者和仓库。

## 平台覆盖表

| source id | 平台 | access_mode | 官方定位 | 默认用途 |
|---|---|---|---|---|
| `local-project` | 当前项目 Skills | local | `.agents/skills/` | 最高优先级，直接复用 |
| `local-user` | 当前用户 Skills | local | `~/.agents/skills/` | 项目未覆盖时复用 |
| `anthropic-official` | Anthropic Skills | repo-search | `github.com/anthropics/skills` | 高可信参考与候选 |
| `skills-sh` | skills.sh / Vercel Skills CLI | cli | `skills.sh` | 广泛搜索与标准安装描述 |
| `skillsmp` | SkillsMP | api | `skillsmp.com/docs/api` | 大范围关键词召回 |
| `lobehub` | LobeHub Skills | cli | LobeHub 官方 `lh` CLI | 搜索 LobeHub 目录 |
| `tencent-skillhub` | 腾讯 SkillHub | api | `skillhub.cn`、Tencent/skillhub | 中文目录与公开元数据 |
| `clawhub` | ClawHub / OpenClaw Skills | cli | OpenClaw 官方 CLI 与文档 | OpenClaw 生态候选 |
| `skillhub-club` | SkillHub.club | site-search | `skillhub.club` | 人工浏览和限定域名检索 |
| `agentskills-so` | AgentSkills.so | site-search | `agentskills.so` | 分类与详情页检索 |
| `modelscope` | ModelScope Skills | site-search | `modelscope.cn/skills` | 国内 Skills 中心检索 |
| `github` | GitHub | github-search | `github.com` | 其他来源无结果时补充 |

## 具体检索规则

### Anthropic 官方仓库

- 仅把 `github.com/anthropics/skills` 仓库内的结果标记为 `anthropic-official`。
- 仓库 fork、镜像和同名组织不得继承官方标记。
- 访问方式是 `repo-search`，不是市场 API。

### skills.sh

- 搜索：`npx skills find <query>`。
- 安装候选命令：`npx skills add <package>`；执行前先用当前 CLI 帮助确认参数和目标目录。
- CLI 输出中的热度属于动态弱信号，不代表代码安全。

### SkillsMP

- 公开搜索入口：`GET https://skillsmp.com/api/v1/skills/search?q=<query>`。
- API key、分页和限流以当前官方文档为准。
- 结果属于索引信息；安装前必须回到原仓库核验内容。

### LobeHub Skills

- 搜索：`lh skill search <query>`。
- 安装候选命令：`lh skill install <slug>`；执行前核对 `lh skill --help` 和安装目标。
- 如果 CLI 不可用，降级为限定 LobeHub 官方域名的 `site-search`，并明确标注降级。

### 腾讯 SkillHub

- 优先使用 `skillhub.cn` 或 `Tencent/skillhub` 当前官方文档公开的搜索入口。
- 可将官方 `find-skill-skillhub` 作为平台查询辅助，但不能把其结果视为已安装。
- 官方 API 不可用时可降级为限定 `skillhub.cn` 的 `site-search`，并在结果中记录实际访问方式。
- 未核实具体 API 路径前不得猜测接口。

### ClawHub / OpenClaw

- 使用当前 OpenClaw 官方文档提供的 Skills 搜索/安装命令；执行前通过 CLI `--help` 校验命令和参数。
- 旧版 `npx clawhub` 命令只能在本机实际存在且帮助信息匹配时使用。
- 社区条目必须追溯到作者、仓库与具体文件。

### SkillHub.club、AgentSkills.so、ModelScope

- 使用 `site-search`：限定各自官方域名搜索分类、详情页和仓库链接。
- 未确认稳定公开 API，因此不得标注为 `api`。
- 如果详情页缺少仓库或可审查源码，标记 `inspectable=false`，不推荐自动安装。

### GitHub 通用补充

- 搜索包含 `SKILL.md` 的仓库和路径，并结合任务关键词。
- 对 owner、仓库年龄、维护状态、许可证、提交记录和文件内容进行核验。
- 不因 star 数量高就提升为官方或安全来源。

## 兼容来源

旧版本使用的 Lightmake/SkillHub 和虾评入口可作为低优先级兼容来源，但只有在当前入口可核验、能追溯到源码且结果明确标注真实平台名时才使用。不得把 Lightmake、SkillHub.club 和腾讯 SkillHub 混称为“SkillHub”。

## 来源优先级

同等匹配度下，建议顺序：

1. 当前项目已安装；
2. 当前用户已安装；
3. 官方发布者仓库；
4. 能追溯源码的官方 CLI/API 目录；
5. 能追溯源码的限定域名目录；
6. GitHub 通用结果；
7. 无源码或来源不明的条目。

优先级是审查顺序，不是安全保证。
