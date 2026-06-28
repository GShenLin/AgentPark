---
name: find-skills
slug: guipi-find-skills
displayName: Find Skills（场景驱动技能发现）
version: "1.8.0"
description: 场景驱动+关键词双模式技能发现工具。当用户用自然语言描述场景/需求（如"我想做一个海报""帮我分析股票"），或明确说"安装技能/find skills/找个skill"时，自动从官方内置、当前项目 skills、SkillHub、虾评、GitHub、ClawHub 联合搜索并推荐最合适的技能，支持一键安装到当前项目 ./skills/。已完全替代官方原 find-skills 插件。
agent_created: true
xiaping_trigger: ["AI","效率","技能","工具"]
xiaping_category: ["效率工具"]
xiaping_tags: ["AI工具","技能发现"]
xiaping_eval_strategy: developer
---

# find-skills（场景技能匹配器）

## Overview

本技能用于**场景驱动的技能发现引擎**——用户用自然语言描述需求，系统自动理解意图，联合搜索并推荐最合适的技能。

**与官方原 `find-skills` 插件的关系**：
- 官方原 `find-skills` 插件的 description 已被标记为 DEPRECATED，不会主动触发
- 本技能已完全覆盖其所有能力，并新增了官方内置扫描 + 当前项目 skills 扫描 + 场景语义理解 + 推荐理由输出

---

## 核心流程

### Step 1：理解用户场景

从用户的自然语言描述中提取：
1. **任务意图**：用户想做什么？
2. **领域标签**：属于哪个领域？
3. **搜索关键词**：中英文都要（用于远程搜索）

**示例**：
- "我想做一个海报" → 意图：设计/制图；领域：内容创作；关键词：poster, design, 海报, 设计
- "帮我分析今天的大盘" → 意图：股票分析；领域：金融；关键词：stock, A股, 大盘, 分析

---

### Step 2：多层联合搜索

#### 2.1 第一层：官方内置技能（自带，无需安装）

扫描官方内置技能目录，读取每个技能的 `name` 和 `description`：

```bash
ls ./skills/
```

用 `Read` 工具读取每个技能的 `SKILL.md` YAML frontmatter，与用户场景做**语义匹配**。

**匹配规则**（按优先级）：
1. 用户场景关键词直接出现在技能 description 中 → 高分
2. 技能 name 与用户意图高度相关 → 高分
3. 技能 description 与用户领域相关 → 中分

---

#### 2.2 第二层：当前项目已安装技能

扫描当前工作区的项目级技能目录：

```bash
# 当前项目 skills 目录
ls skills/ 2>/dev/null || echo "无当前项目 skills 目录"
```

用 `Read` 工具读取每个技能的 `SKILL.md` YAML frontmatter，提取 `name` 和 `description`，与用户场景做**语义匹配**。

> **注意**：如果当前项目技能在 Step 2.1 官方内置中也出现，去重，只保留最高优先级的记录。

---

#### 2.3 第三层：远程技能市场（完全替代 `find-skills` 的搜索能力）

---

**远程搜索**（原 `find-skills` Step 2/2b 逻辑）：
按以下顺序搜索远程技能市场：

---

**① SkillHub 官方市场**（主要来源，优先搜索）：
```bash
curl -s "https://lightmake.site/api/v1/search?q=<URL-encoded 中文关键词>&limit=10"
curl -s "https://lightmake.site/api/v1/search?q=<URL-encoded English keywords>&limit=10"
```

过滤 `score < 0.05` 的低相关结果。

---

**② 虾评技能市场**（中文技能重点来源）：

虾评 API Base URL：`https://xiaping.coze.com`（注意：不是 `coze.site`）

**搜索技能**：
```bash
# 搜索技能（按关键词）
curl -s "https://xiaping.coze.com/api/skills/search?q=<URL-encoded 关键词>&limit=10"

# 获取技能详情
curl -s "https://xiaping.coze.com/api/skills/<skill-id>"

# 获取技能下载链接
curl -s "https://xiaping.coze.com/api/skills/<skill-id>/download"
```

**需要先加载 `虾评指南` 技能**（路径：`skills/虾评指南/SKILL.md`），按其中 §1.1 + §1.2 的规范执行搜索和下载。

> **重要**：虾评是中文技能的核心来源，对于中文场景的技能搜索，虾评的结果往往比 SkillHub 更相关。

---
**③ GitHub 技能仓库**（开源技能来源）：

搜索 GitHub 上包含 WorkBuddy / Claw 技能的文件。

> **认证说明**：GitHub 搜索 API 需要认证。如果环境变量 `GITHUB_TOKEN` 已设置，自动带上认证（5000次/小时）；否则使用匿名访问（60次/小时，可能不够用）。

```bash
# 如果有 GitHub Token，带上认证
if [ -n "$GITHUB_TOKEN" ]; then
  AUTH_HEADER="-H \"Authorization: Bearer $GITHUB_TOKEN\""
else
  AUTH_HEADER=""
fi

# 搜索包含 SKILL.md 的代码
curl -s $AUTH_HEADER "https://api.github.com/search/code?q=filename:SKILL.md+<关键词>&per_page=10"

# 搜索技能相关仓库
curl -s $AUTH_HEADER "https://api.github.com/search/repositories?q=<URL-encoded 关键词>+skill+in:name,description&per_page=10"
```

> **注意**：GitHub Code Search API 的 `filename:SKILL.md` 搜索需要认证才能使用。如果没有 `GITHUB_TOKEN`，退化为只搜索 repositories（仓库搜索匿名可用）。

**安装方式**：
```bash
# 从 GitHub 克隆技能仓库
mkdir -p skills
git clone "https://github.com/<user>/<repo>.git" skills/<skill-name>/

# 验证安装
ls skills/<skill-name>/SKILL.md
```

> **注意**：GitHub 搜索结果需要人工判断是否为有效技能（检查是否包含 `SKILL.md`），因为是代码搜索，可能返回非技能文件。

**④ Fallback 来源**（SkillHub + 虾评 + GitHub 均无结果时使用）：
```bash
# Vercel Skills CLI
npx skills find [query]

# ClawHub
npx clawhub search [query]
```

> **重要**：远程搜索结果只作为**补充推荐**，优先级低于当前项目已安装技能。

---

### Step 2.4：当前项目安装目录（安装前必须执行）

在安装任何远程技能之前，**必须确认当前工作区并创建项目级技能目录**。所有安装都固定写入当前项目的 `skills/`

```bash
pwd
mkdir -p skills
```

**安装目标**：`./skills/<skill-name>/`

---

### Step 3：智能排序与推荐

将四层搜索结果合并，按以下规则排序：

| 优先级 | 来源 | 条件 |
|--------|------|------|
| 1 | 官方内置技能 | 语义匹配高分（description 含场景关键词） |
| 2 | 当前项目 skills | 语义匹配高分（已安装，可直接用） |
| 3 | SkillHub 官方市场 | score ≥ 0.3 且 downloads/installs 高 |
| 4 | 虾评技能市场 | 相关度高分（中文技能优先） |
| 5 | GitHub 开源仓库 | 相关度高分（含 SKILL.md） |
| 6 | ClawHub / Vercel Skills | 相关度高分 |
| 7 | 当前项目 skills | 语义匹配中分（name 相关） |
| 8 | SkillHub 官方市场 | score ≥ 0.1 |
| 9 | 虾评技能市场 | 相关度中分 |
| 10 | GitHub 开源仓库 | 相关度中分 |
| 11 | ClawHub / Vercel Skills | 相关度中分 |

**去重规则**：
- 如果同一个技能在多层都出现，保留**最高优先级**的那条记录
- 例如：当前项目已安装 `AI图片生成无水印`，同时 SkillHub 也有，只显示"✅ 已安装"

---

### Step 4：输出推荐结果

**输出格式**：

```
🔍 为你找到 {N} 个相关技能（搜索范围：官方内置 + 当前项目 skills + 远程市场）：

【官方·内置】✅ 无需安装
1. {技能名} — {一句话说明}
   匹配理由：{为什么适合这个场景}
   来源：./skills文件夹内

【项目·已安装】✅ 可直接使用
2. {技能名} — {一句话说明}
   匹配理由：{为什么适合这个场景}
   路径：skills/{技能名}/

【远程·可安装】⬇️ 需安装
3. {技能名} — {一句话说明}
   匹配理由：{为什么适合这个场景}
   来源：{SkillHub/虾评/ClawHub/Vercel}
   下载量：{downloads} | 安装量：{installs}
   安装命令：回复"安装第3个"即可
```

---

### Step 5：一键安装（如需）

如果用户选择安装远程技能，按以下流程执行：

**安装前必须执行项目目录确认**（见 Step 2.4），确定目标目录为当前工作区 `skills/`。

#### 5.1 从本地 marketplace 缓存安装（优先）

如果 Step 2.3 的本地缓存检查已找到匹配技能：

```bash
mkdir -p skills
```

验证安装：
```bash
ls skills/<skill-folder-name>/SKILL.md
```

如果目标目录已存在同名技能，明确询问用户：跳过 / 替换 / 重命名。

#### 5.2 从 SkillHub 远程安装

```bash
TMPDIR=$(mktemp -d)
curl -L -o "$TMPDIR/skill.zip" "https://lightmake.site/api/v1/download?slug=<slug>"
mkdir -p skills/<slug>
unzip -o "$TMPDIR/skill.zip" -d skills/<slug>
rm -rf "$TMPDIR"
ls skills/<slug>/SKILL.md
```

指定版本安装：
```bash
curl -L -o "$TMPDIR/skill.zip" "https://lightmake.site/api/v1/download?slug=<slug>&version=<version>"
```

#### 5.3 从虾评远程安装

**先加载 `虾评指南` 技能**（路径：`skills/虾评指南/SKILL.md`），按其中 §1.2 的下载安装流程执行：

```bash
# 1. 获取下载链接
curl -s "https://xiaping.coze.com/api/skills/<skill-id>/download"

# 2. 下载技能 ZIP
TMPDIR=$(mktemp -d)
curl -L -o "$TMPDIR/skill.zip" "<download-url>"

# 3. 解压到目标目录
mkdir -p skills/<skill-name>
unzip -o "$TMPDIR/skill.zip" -d skills/<skill-name>

# 4. 清理
rm -rf "$TMPDIR"

# 5. 验证安装
ls skills/<skill-name>/SKILL.md
```

> **注意**：虾评的下载流程可能需要认证（API Key / Token），具体参考 `虾评指南` 技能中的 §0.2 注册流程和 §1.2 下载安装流程。

#### 5.4 从 ClawHub 远程安装

```bash
TMPDIR=$(mktemp -d)
curl -L -o "$TMPDIR/skill.zip" "https://clawhub.com/api/download?slug=<slug>"
mkdir -p skills/<slug>
unzip -o "$TMPDIR/skill.zip" -d skills/<slug>
rm -rf "$TMPDIR"
ls skills/<slug>/SKILL.md
```

#### 5.5 从 GitHub 开源仓库安装

**先搜索确认仓库包含技能文件**：
```bash
# 搜索包含 SKILL.md 的代码
curl -s "https://api.github.com/search/code?q=filename:SKILL.md+<关键词>&per_page=10"
```

找到目标仓库后，克隆安装：
```bash
TMPDIR=$(mktemp -d)
git clone "https://github.com/<user>/<repo>.git" "$TMPDIR/<skill-name>"
mkdir -p skills
cp -r "$TMPDIR/<skill-name>" skills/

# 验证安装
ls skills/<skill-name>/SKILL.md

# 清理
rm -rf "$TMPDIR"
```

> **注意**：GitHub 搜索结果需要人工判断是否为有效技能（检查是否包含 `SKILL.md`）。

#### 5.6 从 Vercel Skills CLI 安装（Fallback）

```bash
npx skills add <owner/repo@skill> -g -y
```

如果 CLI 安装在 `~/.agents/skills/`，则复制到当前项目 `skills/`：
```bash
mkdir -p skills
cp -r ~/.agents/skills/<skill-name> skills/<skill-name>
ls skills/<skill-name>/SKILL.md
```

---

安装完成后，提示用户："✅ {技能名} 已安装，现在可以直接用啦！"

---

## 触发词参考

| 用户表达 | 触发方式 |
|----------|----------|
| "我想做XXX" | 自动触发场景理解 |
| "帮我找XXX的技能" | 直接触发多层搜索 |
| "有没有能XXX的工具" | 触发多层搜索 |
| "这个场景应该用哪个技能" | 触发匹配推荐 |
| "我想做一个海报" | 自然语言场景 → 匹配设计类技能 |

**重要**：
- 本技能是**唯一的技能发现入口**，已完全替代 `find-skills`（其 description 已被标记为 DEPRECATED）
- 所有"找技能/安装技能/发现能力"的请求都由本技能处理

---

## 示例对话

**用户**："我想做一个海报，有没有合适的技能？"

**助手**：
```
🔍 为你找到 3 个相关技能（搜索范围：官方内置 + 当前项目 skills + 远程市场）：

【项目·已安装】✅ 可直接使用
1. AI图片生成无水印 — 支持文生图、图生图，8通道（龙虾Lovart/即梦/通义等）
   匹配理由：海报设计属于图片生成场景，该技能支持多种风格生成
   路径：skills/AI图片生成无水印/

【官方市场·可安装】⬇️ 需安装
2. poster-maker — 专为主题海报设计的技能
   匹配理由：专门针对海报设计场景
   来源：SkillHub 官方市场
   下载量：2.3K | 安装量：420
   安装命令：回复"安装第2个"即可

【社区·可安装】⬇️ 需安装
3. claw-poster-generator — ClawHub 上的海报生成技能
   匹配理由：支持批量生成海报
   来源：ClawHub 社区
   安装命令：回复"安装第3个"即可

需要我帮你安装第2或第3个到当前项目 skills/，还是直接用第1个？
```

---

## 🔌 技能体系结合分析

### 🔗 协作链路

```
用户场景描述 / 明确要找技能
   → find-skills（场景技能匹配器）（本技能）← 唯一入口，已完全替代官方原 find-skills
       ├─ 第一层：官方内置技能扫描 → 直接推荐
       ├─ 第二层：当前项目 skills 扫描 → 直接推荐
       ├─ 第三层：本地 marketplace 缓存检查 → 优先安装到当前项目 skills/
       └─ 第四层：远程技能市场搜索 → 补充推荐并安装到当前项目 skills/
```

**下游调用**：
- 命中当前项目技能 → 直接调用对应技能
- 命中远程技能 → 安装到当前项目 `skills/` → 再调用

### ♻️ 与 `find-skills` 的关系

- **`find-skills`（官方插件目录）的 description 已被标记为 DEPRECATED**，不会主动触发
- **本技能已完全覆盖 `find-skills`（官方插件）的所有能力**：
  - ✅ SkillHub 远程搜索
  - ✅ ClawHub / Vercel Skills CLI fallback
  - ✅ 当前项目安装目录确认（固定写入 `./skills/`）
  - ✅ 本地 marketplace 缓存检查
  - ✅ 一键安装到当前项目 `skills/`（SkillHub / ClawHub / Vercel / GitHub）
- **本技能新增官方 `find-skills` 不具备的能力**：
  - ✅ 官方内置技能扫描
  - ✅ 当前项目 skills 扫描
  - ✅ 场景语义理解（不是关键词搜索）
  - ✅ 推荐理由输出

> **结论**：官方 `find-skills` 插件文件可保留（官方插件目录，删除会被覆盖），但其 description 已失效，不会再被触发。所有技能发现请求都由本技能处理。

### 📊 体系优化建议

- `find-skills` 的 SKILL.md 已被标记为 DEPRECATED，后续官方插件更新可能会覆盖此修改，需留意
- 建议定期确认 `find-skills` 的 description 是否被正确禁用

### 🎯 使用场景映射

| 业务线 | 典型场景 | 推荐的技能 |
|--------|------------|------------|
| 自媒体 | "我想做小红书封面" | `AI图片生成无水印` / `封面图生成` |
| 自媒体 | "帮我写公众号文章" | `写公众号` / `公众号长文创作` |
| 量化交易 | "帮我分析今天的大盘" | `A股数据获取` / `A股市场情绪分析` |
| 公司经营 | "我想记录今天的反思" | `每日反思` / `Get笔记` |
| 公司经营 | "帮我发邮件给客户" | `email-skill` |

---

## 📝 版本迭代记录

| 版本 | 日期 | 更新内容摘要 | 操作人 |
|------|------|------------|--------|
| v1.0 | 2026-06-20 | 创建技能（仅本地+SkillHub搜索） | Kyle |
| v1.1 | 2026-06-20 | 更新为三层搜索：官方仓库 → 技能社区 → 本地仓库 | Kyle |
| v1.2 | 2026-06-20 | 重构：复用 find-skills 远程搜索能力，只新增官方内置+本地已安装两层扫描 | Kyle |
| v1.3 | 2026-06-20 | 完全替代 find-skills：新增客户端检测+本地marketplace缓存检查+完整安装逻辑；禁用官方 find-skills 触发 | Kyle |
| v1.4 | 2026-06-20 | 技能目录重命名为 find-skills，统一名称；更新 description 覆盖所有触发场景 | Kyle |
| v1.5 | 2026-06-20 | 新增虾评技能市场作为第四个搜索渠道；更新排序表和安装流程 | Kyle |
| v1.6 | 2026-06-20 | 新增 GitHub 开源仓库作为第五个搜索渠道；更新排序表和安装流程 | Kyle |
| v1.7 | 2026-06-20 | 发布前修复：精简 description、GitHub 搜索加 Token 认证、虾评域名确认、移动到产品存档目录 | Kyle |
| v1.8 | 2026-06-23 | 安装目标改为当前项目 `skills/`；项目级技能扫描替代用户级技能扫描；移除按客户端选择安装目录的流程 | Kyle |
