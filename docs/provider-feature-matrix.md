# Provider Feature Matrix

Provider configuration is normalized by `ConfigLoader`. Each provider includes:

```json
{
    "features": {
      "schema_version": 1,
      "responses_api": {"supported": true, "values": ["enabled", "disabled"]},
      "web_search": {"supported": true, "values": ["enabled", "disabled"]},
      "thinking": {"supported": false, "values": []},
      "reasoning_effort": {"supported": true, "values": ["minimal", "low", "medium", "high", "xhigh"]}
  }
}
```

The WebUI provider list exposes the same `features` object through `GET /api/providers`.

## Current Semantics

| Provider type | responses_api | web_search | thinking | reasoning_effort |
| --- | --- | --- | --- | --- |
| `openai` with `responsesApi=true` | supported | supported through Responses tools | not supported | supported |
| `openai` without `responsesApi=true` | not supported | not supported; requires `responsesApi=true` | not supported | supported |
| `doubao` with `responsesApi=true` | supported through Ark Responses | supported through Ark Responses `web_search` tool | `enabled`, `disabled`, `auto` through Ark Responses; probe per model | `low`, `medium`, `high` through Ark Responses `reasoning.effort` |
| `doubao` without `responsesApi=true` | not supported | not supported; requires `responsesApi=true` | not supported; requires `responsesApi=true` | not supported; requires `responsesApi=true` |
| `zhipu` | not supported | not supported | `enabled`, `disabled` | supported |
| `claude` | not supported; uses native Messages API | supported through Messages web search tool | `enabled`, `disabled`, `auto` | `low`, `medium`, `high`, `xhigh`, `max` through Messages `output_config.effort` |
| `gemini` | not supported | not supported | not supported | not supported |

Unsupported fields should be shown as unsupported in UI instead of silently pretending the provider will honor them. Runtime providers still validate their own payloads and may raise provider-specific errors when a config asks for unsupported behavior.
