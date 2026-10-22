# Editable tool prompts

Open **Settings → Tools → Tool prompts**, select a tool, edit its description and
use **Save** in the settings toolbar. The editor preserves multiline text and
shows the original description separately. **Restore default** removes the
override; save that change to persist it.

Overrides live in `config/toolsets.json` alongside toolsets:

```json
{
  "toolsets": {},
  "tool_prompts": {
    "read_file": "Read the relevant section, then summarize the findings.",
    "mcp__docs__search": "Search the documentation before proposing changes."
  }
}
```

The key is the exact model-facing tool name, not a toolset or module name. The
editor lists built-in tools and task controls. Use **Add another tool** with the
complete name from a tool call for unlisted MCP, plugin and skill tools. These
entries need not be installed or enabled when their descriptions are saved.

Descriptions apply globally to newly created node Agent runtimes. An active run
keeps its snapshot, including tools added by later skill activation. Overrides
replace only the tool declaration's `description`; they do not change parameter
schemas/descriptions, callable implementations, permissions or tool membership.
They also do not replace runtime result messages or a Skill's full instructions.

Each registration receives a separate copy of the declaration. Cached MCP schemas
and Python defaults stay intact. Same-name tools share an override; the editor
shows all known source defaults when a name has multiple declarations. An empty
string is an explicit empty description; deleting the key restores the original.
Descriptions are limited to 32,000 characters. Unknown fields, invalid tool names
and non-string descriptions are rejected before saving.
