# Provider authorization

AgentPark owns its authorization state. It does not read or write credentials in vendor CLI
directories such as `~/.codex` or `~/.claude`.

## Storage contract

All secrets are stored below the workspace `.auth` directory:

```text
.auth/
  api-keys/
    aliases.json
  openai/
    accounts.json
    accounts/<account-id>.json
  kimi/
    accounts.json
    accounts/<account-id>.json
  <provider>/
    accounts.json
    accounts/<account-id>.json
```

`accounts.json` contains only account metadata and the active account pointer. Secret material is
kept in the per-account file. The stable account id is derived from the provider and authenticated
identity, so refreshing a token updates the same account instead of creating duplicates.

`.auth/` is ignored by Git. On POSIX, written credential files are restricted to mode `0600`.

## Supported authorization protocols

- `openai`: ChatGPT/Codex authorization-code OAuth with PKCE and automatic refresh.
- `anthropic`: Claude Pro/Max OAuth with PKCE, callback or manual authorization-code submission,
  OAuth-specific Messages headers, tool-name mapping, and automatic refresh.
- `kimi`: Kimi Code device authorization with polling and automatic refresh.
- `xai`: xAI/Grok authorization-code OAuth with discovery, PKCE, endpoint allowlisting, and refresh.
- every configured provider: API-key accounts through the provider authorization API.

OpenAI and Kimi accept multiple OAuth identities. API-key providers accept multiple named
identities. One account is active per provider; a provider config may pin a particular account with
`authAccountId`.

The Model Provider settings UI lists the accounts belonging to the selected provider. Selecting an
account updates both the provider's `authAccountId` pin and the provider store's active account.
API-key accounts can be created in the same panel; the secret input is sent directly to the local
authorization API and is never written into `modelProvider.json`.

Provider configuration uses:

```json
{
  "type": "kimi",
  "authMode": "oauth",
  "authProvider": "kimi",
  "baseUrl": "https://api.kimi.com/coding/v1"
}
```

For an API-key account stored under `.auth/<provider>`, use `authMode: "api_key"` and
`authProvider: "<provider>"`. Existing key-name references resolve through
`.auth/api-keys/aliases.json`.

## Management API

- `GET /api/provider-auth/{provider}/status`
- `POST /api/provider-auth/{provider}/login`
- `POST /api/provider-auth/{provider}/api-key`
- `POST /api/provider-auth/{provider}/accounts/{account}/activate`
- `DELETE /api/provider-auth/{provider}/accounts/{account}`

Status responses contain masked metadata only and never return access tokens, refresh tokens, or
API keys.
