import json
from pathlib import Path

from nodes.agent_skill_loader import list_available_skill_options, load_node_skills


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = PROJECT_ROOT / ".agents" / "skills"
SKILL_DIR = SKILLS_ROOT / "find-skills-1.0.0"


def _read(relative_path: str) -> str:
    return (SKILL_DIR / relative_path).read_text(encoding="utf-8")


def test_find_skills_is_discoverable_and_version_metadata_is_synchronized():
    options = list_available_skill_options(str(SKILLS_ROOT))
    option = next(item for item in options if item["value"] == "find-skills-1.0.0")
    skill = load_node_skills(
        ["find-skills-1.0.0"],
        node_id="find-skills-test",
        skill_root=str(SKILLS_ROOT),
    )[0]
    metadata = json.loads(_read("_meta.json"))

    assert skill.name == "find-skills"
    assert skill.version == "2.0.0"
    assert option["version"] == skill.version
    assert metadata["slug"] == "find-skills"
    assert metadata["version"] == skill.version
    assert skill.path == str(SKILL_DIR / "SKILL.md")


def test_find_skills_platform_matrix_covers_required_sources_and_access_modes():
    platforms = _read("references/platforms.md")

    required_sources = {
        "| `skillsmp` | SkillsMP | api |",
        "| `skills-sh` | skills.sh / Vercel Skills CLI | cli |",
        "| `lobehub` | LobeHub Skills | cli |",
        "| `anthropic-official` | Anthropic Skills | repo-search |",
        "| `skillhub-club` | SkillHub.club | site-search |",
        "| `agentskills-so` | AgentSkills.so | site-search |",
        "| `clawhub` | ClawHub / OpenClaw Skills | cli |",
        "| `tencent-skillhub` | 腾讯 SkillHub | api |",
        "| `modelscope` | ModelScope Skills | site-search |",
    }
    for platform_row in required_sources:
        assert platform_row in platforms

    assert "GET https://skillsmp.com/api/v1/skills/search?q=<query>" in platforms
    assert "npx skills find <query>" in platforms
    assert "npx skills add <package>" in platforms
    assert "lh skill search <query>" in platforms
    assert "github.com/anthropics/skills" in platforms
    assert "未确认稳定公开 API" in platforms
    assert "限定 `skillhub.cn` 的 `site-search`" in platforms
    assert "不得把 Lightmake、SkillHub.club 和腾讯 SkillHub 混称" in platforms


def test_find_skills_defines_cross_platform_contract_and_safe_deduplication():
    contract = _read("references/result-contract.md")

    for field in (
        "name:",
        "description:",
        "source:",
        "access_mode:",
        "locator:",
        "repository:",
        "author:",
        "version:",
        "trust_tier:",
        "security_evidence:",
        "install_method:",
        "match_reason:",
    ):
        assert field in contract

    assert "normalized_repository + repository_path" in contract
    assert "名称相同但作者或仓库不同，不自动合并" in contract
    assert "项目级 `.agents/skills/<name>/` 优先于用户级" in contract
    assert "评分、下载量或安全标签都不能覆盖本地安全检查" in contract


def test_find_skills_requires_review_and_explicit_confirmation_before_install():
    security = _read("references/security-and-installation.md")
    skill_content = _read("SKILL.md")

    assert "Skill 可能包含提示词、脚本、依赖、MCP 配置和可执行文件" in security
    assert "`high` 和 `unknown` 候选不得自动安装" in security
    assert "只有用户对该候选和该目标目录明确确认后才能执行" in security
    assert "不得使用 `curl ... | sh`、`irm ... | iex`" in security
    assert "默认：当前项目 `.agents/skills/<skill-name>/`" in security
    assert "用户明确要求共享安装时：`~/.agents/skills/<skill-name>/`" in security
    assert "不得执行候选 Skill 仓库中的安装脚本" in skill_content
    assert "不得把 OAuth token、API key、Cookie" in skill_content


def test_find_skills_main_document_is_split_by_responsibility():
    skill_content = _read("SKILL.md")
    readme = _read("README.md")

    assert len(skill_content.splitlines()) < 400
    for reference in (
        "references/platforms.md",
        "references/result-contract.md",
        "references/security-and-installation.md",
    ):
        assert reference in skill_content
        assert (SKILL_DIR / reference).is_file()

    assert "当前项目 `.agents/skills/`" in readme
    assert "当前用户 `~/.agents/skills/`" in readme
    assert "同名时项目级优先" in readme
    assert "AgentPark 仅从项目级" not in readme
