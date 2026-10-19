# Provider authorization

AgentPark owns its Provider authorization state and normally stores it under the workspace
`.auth/` directory. Settings also provides an explicit **同步本机 Codex 凭据** action: it reads
the backend user's Codex file credential store once and imports or updates the matching account
in AgentPark. It does not write back to Codex or continuously synchronize its credentials.
Native Harnesses such as OpenCode and Antigravity retain their own login storage.

For the complete settings workflow, see [Model Provider and Harness](settings/models.md).

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

## Explicit local Codex import

The source is the Codex home selected by `CODEX_HOME`, or the backend user's `~/.codex`.
Import requires file-based credential storage, a valid ChatGPT OAuth login and an unexpired
access token. Keyring-only storage, API-key logins, malformed or mismatched accounts and expired
tokens fail explicitly. The browser's device or operating-system user is not the source.
See `src/provider_auth/codex_credential_sync.py` for the import contract.
