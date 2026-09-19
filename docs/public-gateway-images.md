# Gateway 图片请求转发

外部客户端沿用现有 Gateway 端口、`/v1` Base URL 和 Endpoint Key。
图片请求不经过对话协议转换，使用图片 Provider 的登录凭据转发；请求中的
模型 ID 必须是实际的上游模型名，网关使用请求中的 ID 调用上游，
其余参数及图片返回内容保留。一个 Provider 配置下可添加多个模型 ID，
共用连接、凭据、账户及协议设置；Provider 的默认 `model` 不覆盖请求的 ID。

| 外部入口 | Gateway 协议 | 上游路径 |
| --- | --- | --- |
| `POST /v1/images/generations` | `images_generations` | `/images/generations` |
| `POST /v1/images/edits` | `images_edits` | `/images/edits` |

配置示例（只添加该 Provider 上游实际支持的模型 ID）：

| 公共模型名 | Provider | 上游模型 |
| --- | --- | --- |
| `gpt-image-1.5` | `GPT_Image_1_5` | `gpt-image-1.5` |
| `gpt-image-2` | `GPT_Image_2` | `gpt-image-2` |
| `gpt-image-2.5` | `GPT_Image_2_5` | `gpt-image-2.5` |

同一 Provider 可同时配置 `gpt-image-1.5`、`gpt-image-2` 等多个 ID，
请求哪个 ID 就调用哪个模型。ID 不作为 Provider 默认模型的别名。
例如配置 `gpt-image-2.0` 后，上游收到的模型名也是 `gpt-image-2.0`。
这些 Provider 使用现有 OpenAI/Codex 账号，默认上游是
`https://chatgpt.com/backend-api/codex`。图片模型不会被路由到对话模型。

生成请求示例（JSON）：

```json
{"model":"gpt-image-2.5","prompt":"A blue circle on a white background","size":"auto","quality":"auto","background":"auto"}
```

编辑入口使用 JSON `images` 数组，元素为 `{"image_url":"https://…"}`、
图片 data URL 或 `{"file_id":"…"}`；不读取 Gateway 主机本地路径。
当前入口不接受 multipart 文件上传。`stream: true` 保留上游图片 SSE 事件。
生成失败不会自动重试，避免超时后重复生成；OAuth 401 只刷新凭据重试一次。

`.runtime/public-gateway-access.log` 记录客户端地址、请求路径、公共/上游模型、
状态和耗时，包含未匹配入口及请求体校验失败。不记录提示词、Key 或图片数据。
所有响应携带 `x-request-id`，可据此定位日志。客户端 Skill 若绕过此端口直连
其他服务，该请求不会出现在此 Gateway 的日志中。

回归验证：`python -m pytest tests/test_public_gateway_images.py tests/test_public_gateway.py tests/test_public_gateway_usage.py -q`。
真实验证应从 HTTP 入口带 Key 发送请求，检查返回的图片数据能解码，并记录请求 ID；
单元测试及设置页测试不等同于外部客户端已经成功调用。
