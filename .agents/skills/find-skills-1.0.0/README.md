# Find Skills

Find Skills 是 AgentPark 内置的跨平台 Skill 发现与安全安装编排技能。

## 能力

- 扫描当前项目 `.agents/skills/` 和当前用户 `~/.agents/skills/`。
- 覆盖 SkillsMP、LobeHub、skills.sh、Anthropic 官方仓库、SkillHub.club、AgentSkills.so、ClawHub、腾讯 SkillHub、ModelScope 和 GitHub。
- 区分 API、CLI、限定域名网页检索、限定仓库检索，避免把“能搜到”误写成“原生 API 集成”。
- 使用统一结果合同进行跨平台去重、排序和来源标注。
- 安装前检查脚本、依赖、网络、秘密与文件写入风险，并要求用户确认。

本技能不包含独立网络聚合程序，不会新增绕过 AgentPark 网络边界的 HTTP 客户端。

## AgentPark 安装位置

AgentPark 默认同时发现：

1. 当前项目 `.agents/skills/`；
2. 当前用户 `~/.agents/skills/`。

同名时项目级优先。Find Skills 默认把新 Skill 安装到当前项目；只有用户明确要求共享安装时才使用用户级目录。

本仓库副本位于：

```text
.agents/skills/find-skills-1.0.0/
```

## 文档结构

```text
find-skills-1.0.0/
├── SKILL.md
├── README.md
├── LICENSE
├── _meta.json
└── references/
    ├── platforms.md
    ├── result-contract.md
    └── security-and-installation.md
```

- `SKILL.md`：触发条件和主工作流。
- `references/platforms.md`：平台覆盖与检索策略。
- `references/result-contract.md`：统一字段、去重和排序。
- `references/security-and-installation.md`：安装前审查、确认和落盘规则。

## 使用示例

```text
帮我找一个适合 Python 代码审查的 Skill，只看能追溯到源码的结果。
```

```text
比较 skills.sh、Anthropic 官方仓库和腾讯 SkillHub 上的深度研究类 Skill，先不要安装。
```

## 版本

当前版本：`2.0.0`

## License

MIT License，参见 [LICENSE](LICENSE)。
