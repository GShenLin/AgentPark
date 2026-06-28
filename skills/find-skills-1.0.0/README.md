# Find Skills · WorkBuddy Skill

场景驱动+关键词双模式技能发现工具（完全替代官方原 find-skills 插件）。

当用户用自然语言描述场景/需求（如"我想做一个海报""帮我分析股票"），或明确说"安装技能/find skills/找个skill"时，自动从**官方内置、本地已安装、SkillHub、虾评、GitHub、ClawHub** 六层联合搜索并推荐最合适的技能，支持一键安装。

## 特性

- **场景语义理解**：自动从自然语言提取意图/领域/关键词
- **六层联合搜索**：官方内置 → 本地已安装 → 本地 marketplace 缓存 → SkillHub → 虾评 → GitHub → ClawHub
- **智能排序**：已安装技能优先推荐，去重规则确保不重复
- **推荐理由**：每个推荐附带为什么适合这个场景
- **一键安装**：自动检测客户端（WorkBuddy/CodeBuddy），支持所有来源安装
- **完全替代官方 find-skills**：覆盖所有原功能，并新增官方内置扫描+本地已安装扫描+场景语义理解

## 安装

### WorkBuddy 技能市场（推荐）

在 WorkBuddy 中搜索「Find Skills」一键安装。

### 手动安装

```bash
git clone https://github.com/guipi888/find-skills.git \
  ~/.workbuddy/skills/find-skills
```

## 使用

在 WorkBuddy 对话中直接描述场景即可：

```
用户：我想做一个海报
助手：🔍 为你找到 3 个相关技能...（推荐结果）
```

## 技能搜索渠道

| 优先级 | 渠道 | 说明 |
|--------|------|------|
| 1 | 官方内置技能 | WorkBuddy 自带，无需安装 |
| 2 | 本地已安装 | 你已经装好的 |
| 3 | 本地 marketplace 缓存 | 之前下载过的缓存 |
| 4-① | SkillHub 官方市场 | 官方认证技能 |
| 4-② | 虾评技能市场 | 中文技能重点来源 |
| 4-③ | GitHub 开源仓库 | 搜索含 SKILL.md 的仓库 |
| 4-④ | ClawHub / Vercel Skills | Fallback |

## 项目结构

```
find-skills/
├── SKILL.md           # 技能说明（本技能的核心）
├── LICENSE            # MIT License
├── README.md          # 本文件
└── .gitignore         # Git 忽略规则
```

## 作者

**Kyle** · 桂皮AI实战

> 💝 更多实用 AI 效率工具和技能，关注公众号「桂皮AI实战」

## License

MIT License — 详见 [LICENSE](./LICENSE)
## License

MIT License — 详见 [LICENSE](./LICENSE)
