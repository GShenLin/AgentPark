# 权限与公共模型网关

[Settings 索引](README.md) · [设备互联](connectivity.md)

<a id="authorization"></a>
## 权限 / Authorization

入口：**Settings → 权限**，策略保存在 `.auth/access-control.json`。这里管理访问身份和非 Developer 的工具过滤，不是模型服务的 OAuth 登录。

### 用户列表

普通远程客户端首次访问会登记用户名及客户端/IP，同用户名的设备归入同一用户。表单显示：

| 字段/按钮 | 用途 |
| --- | --- |
| Username | 用户显示身份与归属名称；修改后保存 |
| Developer | 是否保留开发者级节点配置工具及相关权限 |
| Clients / IP | 已登记客户端标识和地址，帮助核对来源 |
| Last access | 最近访问记录 |
| Delete | 移除该用户记录；不删除其机器或 Graph 数据 |
| Reload / Save | 重新读取策略 / 保存当前策略 |

操作流程：先用远程浏览器访问并登记用户名，再从本机权限页找到用户，核对客户端记录，按需要调整 Developer 和工具过滤并保存，最后在远程端新任务中验证。

本机访问视作 Developer。普通 IP 访问、已授权设备之间的 P2P 调用、云端管理员打开的 Board，具有不同身份来源。云端管理员 Board 按专用拥有者身份管理设备；后端之间共享请求仍受非 Developer 和共享权限约束。

### 非 Developer 过滤工具

1. 在工具列表勾选要对非 Developer 隐藏的工具模块或函数。
2. 已注册列表之外的精确名称，可通过 Additional tool 输入后添加。
3. 点击本面板 Save。
4. 从对应远程身份发起新消息，查看实际允许的工具与拒绝原因。

这里的勾选表示“过滤”，不是“授予”。Developer 不应用这组过滤；Provider 的 private 属性、公开 Graph/节点规则、共享权限和不同 Harness 的执行权限还会分别约束请求。

该面板是项目访问策略，不提供完整的独立账号密码系统。删除用户名记录不等于回滚已经排队的任务；对执行中的任务应使用节点停止操作。

<a id="gateway"></a>
## 网关 / Gateway

入口：**Settings → 网关**。用途是让外部模型客户端通过 AgentPark 请求选定 Provider，区别于给别人打开 Board。模型映射保存在 `config/publicGateway.json`，网关 Key 管理数据在 `.auth/gateway/keys.json`。

### 1. 启用与配置公开模型

1. 先在模型提供商中配置并验证上游账号及模型。
2. 打开 Gateway，勾选 Enable 和是否 Require API Key。
3. 添加 Provider Group，选择 Provider。
4. 需要固定账号时选 Fixed account；留空使用 Provider 默认账号。
5. 填 Public model IDs，选择允许协议，启用该组。
6. 点击网关页的保存选项；有 Unsaved 标记时测试仍按已保存配置执行。

| 字段 | 含义 |
| --- | --- |
| Enable | 开放/关闭公共模型网关 |
| Require API Key | 外部调用是否要求 Endpoint Key |
| Provider | 请求使用哪个本地连接与凭据 |
| Fixed account | 对该组固定账号，避免依赖活动账号切换 |
| Enabled | 该组模型是否允许访问 |
| Public model IDs | 外部请求的模型 ID，按实际上游模型名称填写 |
| Protocols | 该组允许的客户端协议，仅显示当前 Provider 可支持的集合 |

同一组可有多个模型 ID，共用连接和账号。图片协议明确使用请求中的实际模型名，不把它当作 Provider 默认模型的任意别名。不要将未知或重复的模型 ID 当作自定义路由规则。

### 2. 网关协议与地址

外部客户端的 Base URL 使用实际可达的 AgentPark 地址加 `/v1`，例如本机 `http://127.0.0.1:8766/v1`。页面显示的地址来自浏览器 origin；从云端 P2P Board 打开时，不能据此推断同一个 origin 已提供普通 HTTP 模型代理。外部客户端需有能直接到达网关的 HTTP(S) 入口。

| 接口 | 作用 |
| --- | --- |
| `GET /v1/models` | 列出公开模型 |
| `POST /v1/responses` | Responses 对话入口 |
| `POST /v1/chat/completions` | Chat Completions 对话入口 |
| `POST /v1/messages` | Anthropic Messages 形式入口 |
| `POST /v1/images/generations` | JSON 图片生成 |
| `POST /v1/images/edits` | JSON 图片编辑 |

对话协议按网关适配器处理；图片仅对实现对应 wire contract 的 Provider 开放，不因某个服务能生成图就宣称兼容 Images API。图片编辑当前用 JSON `images` 数组，不接受 multipart，也不读取网关主机本地路径。

### 3. Endpoint Key

1. 填 Key name。
2. Custom value 留空由服务生成，或填明确的自定义 Key。
3. 点击添加，立即复制返回的完整 Key；常规列表只显示元数据和前缀。
4. 在外部客户端配置独立网关 Key，而不是泄露上游 OAuth token 或真实服务 Key。
5. 不再使用时删除对应 Key，持有它的客户端后续请求将失败。

Key 添加/删除是独立即时操作，不随模型草稿的丢弃操作撤回。Require API Key 开启时，外部 OpenAI 兼容客户端按 Bearer Key 配置；具体协议头由客户端和入口适配负责。

### 4. 内置请求测试

1. 先保存网关配置，确保有启用的公开模型。
2. 在测试区选模型和允许协议，填写短提示词。
3. 图片编辑还需可用参考图 URL 或 data URL。
4. 点击 Test，查看 HTTP 状态、JSON、生成图片或原始错误。
5. 再从实际外部客户端验证 Base URL、Key、模型与协议。

测试会真实请求上游并可能产生费用。设置页内部测试成功，不等于外部网络入口、外部 Key 和客户端格式已经验证成功。Source unavailable 应先修复对应 Provider，而不是重复添加模型组。

### 5. 用量与排错

按日期刷新用量，查看总请求、输入/输出/总 Token，再按来源 IP 和模型细分。服务未返回 usage 的请求单独提示，不计成零消费，也不等同于服务商账单。

| 现象 | 先检查 |
| --- | --- |
| 401 | 网关 Require Key、使用的 Endpoint Key，以及上游账号授权，区分错误来自哪一层 |
| 模型不可用 | 已保存且启用、ID 与协议正确、Provider 无 source error |
| 图片编辑失败 | JSON images 格式、参考图可访问、不是 multipart 或主机路径 |
| 内部成功、外部失败 | 外部 Base URL 是否真实可达、是否用错浏览器 P2P origin、请求格式与 Key |
| 用量为部分/缺失 | 上游是否返回 usage；结合请求日志查看，不用零值推断免费 |

访问日志在 `.runtime/public-gateway-access.log`，通过响应 `x-request-id` 关联请求路径、状态与耗时。图片协议与边界见 [网关图片](../public-gateway-images.md)。
