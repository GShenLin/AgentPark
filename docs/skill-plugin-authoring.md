# Skill and Plugin Authoring

## Skill Layout

A skill is a directory under `skills/` with a required `SKILL.md`:

```text
skills/<skill_id>/
  SKILL.md
  skill.json
  references/
  scripts/
  assets/
  agents/
```

`SKILL.md` requires YAML frontmatter:

```markdown
---
name: demo
description: Demo skill
version: 1.0.0
---

Use this skill when...
```

Only `SKILL.md` is injected as instruction text. Resource directories are indexed and shown as metadata.
`version` is optional, but when present it is exposed through the skill prompt metadata and `CapabilityRegistry` descriptor payloads.

## Resource Directories

Recognized resource directories:

- `references/`: readable reference material
- `scripts/`: script templates or implementation references, not automatically executed
- `assets/`: static assets
- `agents/`: agent configs, including MCP dependency declarations

The prompt receives each resource's type, path, title, size, and short summary. It does not receive full resource contents.

## Reading Resources

When an Agent node selects a skill with resources, it automatically receives `skill_resource_tools`.

Use:

```text
read_skill_resource(skill="demo", path="references/guide.md")
list_skill_resources(skill="demo")
```

The tool only reads files indexed under the selected skill's resource directories. Absolute paths, `..`, hidden files, and files outside the skill root are rejected.

Large resource reads are truncated. Put concise instructions in `SKILL.md`; put detailed material in `references/`.

## Executable Skill Scripts

Scripts are inert unless declared in `skill.json`. A script declaration must specify its entry file, argument schema, working directory, timeout, and write capability:

```json
{
  "scripts": [
    {
      "id": "summarize",
      "name": "Summarize",
      "description": "Run the skill summarizer.",
      "entry": "scripts/summarize.py",
      "argsSchema": {
        "type": "object",
        "properties": {
          "path": { "type": "string" }
        },
        "required": ["path"],
        "additionalProperties": false
      },
      "cwd": ".",
      "timeoutSeconds": 30,
      "allowWrite": false
    }
  ]
}
```

`entry` must stay under `scripts/`, and `cwd` must stay inside the skill directory. Python scripts receive the JSON arguments on stdin and in `AGENTPARK_SKILL_SCRIPT_ARGS`.

Read-only scripts (`allowWrite: false`) are registered as tools by default. Write-capable scripts require both `allowWrite: true` and `enabled: true`; otherwise they remain declared but are not exposed as executable tools.

Script tools return structured JSON with `status`, `exit_code`, `timed_out`, `stdout`, and `stderr`. Argument mismatches return `status: error` with `exception_type: SkillScriptArgumentError` before the process is started.

## Plugin Contributions

Plugins can contribute:

- workspace tool references
- local Python tool declarations
- workspace skill references
- local skill directories
- MCP server references or config

Plugin contributions are surfaced through `CapabilityRegistry`, including dependencies and diagnostics. Plugin-local skill paths must stay inside the plugin directory.

## AgentPark Plugin Manifest

Use `agentpark.plugin.json` for native AgentPark plugins:

```json
{
  "id": "demo-plugin",
  "name": "Demo Plugin",
  "description": "Adds a local tool and a skill.",
  "version": "1.0.0",
  "tools": ["file_read_tools", "./tools"],
  "skills": ["demo-skill", "./skills"],
  "mcpServers": {
    "demo-mcp": {
      "transport": "stdio",
      "command": "./bin/demo-mcp.py",
      "args": ["./config.json"]
    }
  },
  "configSchema": {
    "enabled": {
      "type": "boolean"
    }
  }
}
```

Stable fields:

- `id`: required string
- `name`: optional display name
- `description`: optional display description
- `version`: optional version string
- `tools`: array of workspace tool ids or plugin-local `./` paths
- `skills`: array of workspace skill ids or plugin-local `./` paths
- `mcpServers`: array, inline config object, or relative JSON config file
- `configSchema`: object reserved for future node UI mapping

Only `agentpark.plugin.json` and `plugin.json` are read. OpenClaw-specific `contracts` fields are not part of the AgentPark plugin schema.
