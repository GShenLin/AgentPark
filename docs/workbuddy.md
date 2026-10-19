# WorkBuddy

AgentPark includes a WorkBuddy provider and a local service manager in **Settings →
Model Providers → WorkBuddy → WorkBuddy 服务与账号**. The WorkBuddy desktop application
may remain installed and running, but is not required by this integration.

## Setup

1. Add a provider and select type **WorkBuddy**. Save the provider settings.
2. Select **安装服务依赖**, then **启动服务**. Git and uv must be installed on the
   AgentPark server device. Installation progress and errors appear in the panel.
3. Select **使用本机服务地址** if using a non-default port, then save the provider.
4. Select **登录 WorkBuddy**, open the authorization link, and authorize the account.
   The panel checks completion automatically. Links expire after five minutes.
5. Refresh the account and model catalog. Add desired model IDs and save settings.
   Select this provider and an allowed model in an Agent node or Node Preset.

**随 AgentPark 启动** persists the local service preference. Stop the service before
changing its port or reinstalling dependencies. Stopping interrupts in-flight model
requests. Logging out clears only this service's WorkBuddy session; it does not log
the desktop application out. The panel operates on the device hosting the selected
AgentPark backend, not necessarily the browser device.

Model metadata comes from the authorized account. The catalog displays exact IDs,
context/output limits, image support, reasoning efforts and explicit pricing labels.
Unknown pricing is never classified as free. Account credit balance and package
expiry are not exposed by the pinned service's account-status contract.

## Boundaries

- `src/workbuddy/manager.py` owns installation, process handles, readiness and shutdown.
  Readiness checks include a per-process instance ID; an occupied port cannot be
  mistaken for a successfully started child. The child's stdin lifetime tracks its
  owner, so a parent exit closes the service even without a normal shutdown callback.
- `src/workbuddy/gateway.py` owns authenticated control requests using
  `CurlHttpTransport`. Responses are validated against explicit public contracts.
  Redirects and raw upstream error bodies are not exposed by account controls.
- `WorkBuddyAgent` reuses the existing Chat Completions streaming/tool loop. It
  checks the live model catalog before inference, validates image/reasoning support,
  and sets the model's advertised output limit. It does not support Responses API,
  image generation, or native web search.
- The separately installed protocol service uses the third-party upstream HTTP
  implementation. No upstream source or networking client is copied into AgentPark.
  The service binds only to `127.0.0.1`, requires a generated gateway bearer key,
  and removes that key before handing requests to the upstream protocol service.

## Storage and versions

- Dependencies: `.runtime/workbuddy/{dsh-workbuddy,workbuddy2api}`.
- Diagnostics: `.runtime/workbuddy/logs/{install,service}.log`. Request/response body
  logging is disabled. Installation errors retain their stage logs for inspection.
- WorkBuddy tokens and service preferences: `.auth/workbuddy-service/`.
- Gateway credential: `.auth/workbuddy-service/gateway-key`, also registered as an
  AgentPark API-key account under `.auth/workbuddy/`. No secret is saved in provider JSON.
- DSH service revision: `736d15e5ef4a3f54a715d646529a447d715da59e`.
- workbuddy2api revision: `1cc32c9a98abb53796d8d4e8d477736fe1f0c4cc`.

The source revisions are pinned; Python dependency versions are resolved by uv on
first installation and retained in that local checkout's uv.lock. An installation
checks for local source changes before checking out the pinned revision.

References and licenses: [dsh-workbuddy](https://github.com/a2d2-dev/dsh-workbuddy)
(Apache-2.0) and [workbuddy2api](https://github.com/Zhengyuuuui/workbuddy2api). These
are external dependencies with their own licenses, retained in their checkouts.

## Verification

`tests/test_workbuddy.py` covers strict account/model contracts, unsafe URLs,
redacted errors, lifecycle error reporting and shutdown, the settings API, and a
real local curl/SSE tool-call round trip. This local fixture proves AgentPark's
transport and tool execution, not upstream account availability. Real acceptance
also requires browser authorization, live model discovery, streamed text and a
tool-call round trip against the user's WorkBuddy account.

On 2026-10-16, the local deployment was authorized and returned 25 models. A live
`deepseek-v4.1-flash` check returned `WORKBUDDY_OK` in five text chunks. A second
check called `add_numbers(17, 25)` once and returned `TOOL_OK:42` in five text chunks
after receiving the tool result. The catalog marked this model as free at test time;
future pricing and account entitlements are determined by WorkBuddy.
