# AgentPark 后端 P2P 互联

## 范围

两台运行 AgentPark 的设备通过云端协调服务鉴权和交换连接信息，业务数据使用端到端加密的 WebRTC DataChannel 传输，优先直连，必要时使用云端 TURN 中继。两类用途共用传输层，接收方分别授权：

- **查看和操作远程节点**：列出共享画板和节点、读取最近 50 条对话及当前输出、发送节点消息、停止节点。
- **Agent 协作**：Agent 使用 `peer_network_tools` 查询设备并向远程节点投递消息；目标 Agent 可通过同一工具回复来源设备和来源节点。

这些是已配对后端之间的业务接口。另有**云端设备中心**：管理员登录云端网页，查看当前接入设备，点击进入该设备的现有 AgentPark Board。浏览器使用独立的、限时授权的 P2P 通道。双方实例的节点、内存和任务仍由各自后端持有。

ICE 同时收集直连和 TURN 候选，按 WebRTC 的候选优先级和连通性检查选择路径。能够直连时使用直连；直连不可用时使用已配置的 TURN 中继。不会把 Board 请求改成云端 HTTP 代理，也不会重复发送业务操作。所有候选均不可达时明确报错。

## 模块边界

| 模块 | 职责 |
| --- | --- |
| `src/peer_network/contracts.py` | 严格的配置、授权、信令、请求和响应协议 |
| `identity.py` / `store.py` | Ed25519 设备身份、密钥指纹、持久化授权 |
| `signaling.py` | 独立云端进程，接入认证、设备在线连接、签名信令交换 |
| `portal_auth.py` / `portal_routes.py` / `coordinator_registry.py` | 云端管理员登录、在线设备目录、浏览器授权票据、前端静态资源 |
| `connections.py` | ICE/STUN、确定性连接发起者、签名 SDP、直连生命周期 |
| `channel.py` | 有界分块、背压、请求关联、超时和断线失败 |
| `service.py` | 后端协调服务连接、配对、重连、撤销和状态 |
| `delivery.py` | 持久化消息接收凭证与不确定结果处理 |
| `src/web_backend/peer_operations.py` | 明确列出的业务操作和每次调用的权限检查 |
| `src/web_backend/peer_api.py` | 本机设置、授权、状态和业务请求入口 |
| `src/web_backend/peer_board_http.py` | 允许的 Board HTTP 操作、远程身份、事件流投影和会话内撤销 |
| `functions/peer_network_tools.py` | Agent 设备查询与协作工具 |
| `webui/src/components/settings/Peer*Panel.vue` | 设置及远程工作区界面 |
| `webui/src/portal/` / `webui/public/portal-sw.js` | 设备中心、浏览器 WebRTC、现有 Board 请求及事件流的直连传输 |

已有 `remote_api` 是地址目录，已有 `remote_workspace` 是 HTTP 工作机协议；两者不是跨 NAT 传输层。新模块没有把云端部署成 AgentPark 业务后端，也没有把 P2P 请求转发成具有本机权限的 loopback HTTP 请求。

## 身份、授权与可靠性

1. 每个实例在 `.auth/peer-network/identity.json` 保存自己的 Ed25519 私钥。设备编号是公钥的 SHA-256 指纹；复制实例时不得复制该身份目录，否则两个实例会使用同一设备身份，协调服务会拒绝同时注册。
2. 协调服务先通过一次性挑战验证设备私钥，未知身份进入待确认列表。管理员登录云端后按设备公钥指纹确认一次，确认结果写入云端 `devices.json`，重启后保留。未确认或被拒绝的设备不能注册为在线设备、获取目录或转发信令；不再使用共享接入密钥。公网必须使用 WSS。云端接入许可与后端之间的业务授权分开，后者仍按本机共享设置检查。
3. 每条连接信令携带目标设备、会话编号、有效期和签名，SDP 中的 DTLS 指纹包含在签名里。信令有效期为 120 秒，接收方只对未来时间上界允许 5 秒时钟误差，已过期信令不会因此获得额外有效期。接收端按已配对的公钥指纹核验，不仅信任协调服务器转发的设备名。
4. `view`、`control`、`collaborate` 独立检查；`graph_ids` 明确限制共享画板。当前仍遵守原有可见性规则，只允许访问公开画板中的公开节点。空列表不共享画板。
5. P2P 请求携带内部生成的 `PeerPrincipal`，执行上下文保持 `nondeveloper`，不会因后台接收数据而取得本机开发者身份。节点来源由已认证设备声明；设备拥有者是此处的信任边界。
6. 每条消息要求稳定的 `message_id`。接收日志以设备、目标画板、节点、消息编号去重。相同编号不同内容拒绝；同一内容已接收则返回原接收结果。若进程在入队与记录完成之间崩溃，则结果为未知，禁止自动重放。
7. `queued: true` 只代表接收方已入队，`completed: false` 不代表 Agent 已执行完成。执行状态和结果通过对话查询或目标 Agent 的后续回复获得。
8. 撤销配对关闭本机通道，并阻止后续调用。已经进入本机节点队列或已经开始执行的工作不会因此回滚，需要另行停止节点。已建立通道可以在协调服务短暂中断时继续工作；新建和重连需要协调服务可用。

通道每条消息上限 8 MiB，16,000 字节分块，最多 8 个并发请求，发送缓冲有背压。浏览器端最多同时发送 6 个请求；每个 Board HTTP 请求体和响应体分别限制 4 MiB。调用超时不会自动重试业务操作。超过上限会明确报错，不截断协议包。

## 云端设备中心与 Board

1. 打开鉴权服务器的 HTTPS IP 首页，例如 `https://203.0.113.10`，使用云端管理员密码登录。首次接入的设备会出现在“待确认的新设备”，核对本机显示的设备身份后点击“允许这台设备”。设备自动重连并进入在线列表。
2. 设备卡片显示名称、完整设备编号、接入时间以及“已连接云端”。列表每 5 秒刷新，只列出当前登记的在线连接，不保留离线设备历史。
3. 点击 **打开 Board**，进入 `/board/<设备编号>`。页面先建立浏览器与设备的 WebRTC 通道，成功后根据实际选中的 ICE 候选显示“已直连”或“已通过中继连接”，再加载现有 AgentPark Board。
4. 云端提供页面、字体等静态资源以及鉴权和连接信令。Board 的画板、节点、对话、输入和实时更新在浏览器与设备之间传输；直连不经过 ECS；中继时 ECS TURN 转发端到端加密的数据包，不解释 Board HTTP 请求。
5. 通过云端管理员登录和设备绑定票据认证的 Board 默认拥有开发者及设备拥有者权限。移动端显示节点配置和设置入口，可管理节点、模型与工具、配置档案、文件及私有画板。新消息携带开发者角色，不再应用普通远程用户的工具过滤。请求仍标记为远程来源，通过专用 `CloudBoardAdministrator` 身份授予权限，不伪装成本机请求；普通设备协作仍受原有授权约束。后端地址切换仍通过云端设备列表进行。

云端管理员密码只用于管理页面，设备通过各自的持久化私钥证明身份，无需填写或保存管理员密码。登录会话有效期 1 小时，使用 HttpOnly、SameSite=Strict Cookie（公网同时设置 Secure），不把设备密钥放入 URL 或浏览器存储。浏览器生成临时 Ed25519 身份；协调服务签发绑定浏览器身份、目标设备、连接会话和到期时间的票据。后端每次调用重新检查票据有效期。

本机名称默认取操作系统的计算机名，可在「设置 → 设备互联」修改并保存。启用互联时保存会重新连接，让云端设备列表显示新名称。名称与用于认证的设备身份码分别保存，修改名称不会改变设备身份或已有授权。

启用设备互联并获云端确认后，允许云端管理员以拥有者权限打开本机 Board。关闭设备互联会关闭本机所有互联通道。管理员浏览器不需要手工加入双方设备配对列表。后端之间的协作仍需在可选的共享设置中独立授权。

云端 Board 顶部提供「更新并重启」，调用所选设备原有的 `/api/system/restart`，继续沿用该设备的 Git 更新和重启脚本。页面通过新建 P2P 连接检查后端进程编号，确认编号变化后恢复 Board，最多等待 5 分钟。重启请求仅发送一次，丢失回执时只检查结果，不重放重启命令。连接失败可用「重新连接」再次打开设备。

短暂断线、手动重连或设备重启期间，已打开的 Board 保持挂载，显示重连提示并暂时禁止操作，保留当前 Agent、输入草稿、滚动位置和已展开的过程。恢复连接后先重新校验访问身份，再刷新当前页面的数据并重建事件订阅；旧连接的读取会取消，已发出的写操作不会因重连自动重放。节点不存在或不可访问时明确提示，用户可重试或返回 Board 列表。

刷新网页后，手机端从 URL 的 `mobile_graph`、`mobile_node` 直接读取目标位置，目标数据准备好后一次显示聊天，不逐级显示电脑、Board、Node 列表。编辑器目录和图配置在打开编辑界面时加载。首次打开聊天定位到底部；保留页面的重连不重置阅读位置。浏览器关闭或回收整个页面后，内存中的输入草稿和滚动位置不属于 URL 恢复内容。

退出登录关闭此登录会话中的 Board 信令连接并通知设备撤销通道。正常浏览器关闭也会清理该通道；浏览器连接丢失时页面明确报错。极端网络分区下，设备仍以票据到期时间作为授权上限。重新连接需要重新打开 Board。直连不可用时可选择 TURN 中继路径。

公网入口必须使用 HTTPS，浏览器需要支持 WebRTC DataChannel、Service Worker 和 WebCrypto Ed25519。本机开发可用 `http://127.0.0.1`。手机打开云端 Board 入口也使用 Board 界面，不再跳进另一个后端地址目录。

## 两端 AgentPark 设置

设备互联依赖随常规安装提供，不再要求额外安装 `p2p` 扩展。更新安装后，启动使用新代码的后端，在本机页面打开 **设置 → 设备互联**：

1. **鉴权服务器 IP** 默认是 `203.0.113.10`，可按需修改后保存。
2. **启用设备互联** 默认勾选。新设备启动后会连接默认服务器；已有配置保留原来的启用状态和服务器地址。

程序默认使用电脑名称，并使用持久化设备身份、`wss://<IP>/connect` 和 `stun:<IP>:3478`。支持 IPv4 和 IPv6 字面地址，不接受域名、URL、端口或路径；公网入口固定 HTTPS 443、STUN UDP 3478。修改服务器地址并保存后会重新连接。公网证书校验失败会明确显示连接错误，不降级到明文连接。

首次接入需在云端设备中心确认一次；本机显示“等待云端确认此设备”。批准后在下一次自动重连时上线，无需再次输入配置。申请列表只对已登录管理员开放，新身份申请有速率和数量限制，待确认申请离线 10 分钟后过期。拒绝结果不会被设备重连覆盖。确认绑定设备公钥指纹，设备名称仅用于显示。

**设备之间的共享与 Agent 协作** 收在默认折叠的可选设置中。此处仍按设备和公开画板授权查看、操作、协作；不因加入同一服务器而自动获得另一台后端的业务权限。需要协作的 Agent 节点还需启用 `peer_network_tools`。本机接入云端并从云端打开 Board 不依赖这些可选设置。

管理接口要求从 `http://127.0.0.1:<端口>` 或 `http://localhost:<端口>` 访问，浏览器 Origin 与 Host 相同。内部传输测试允许 loopback WS 和空 STUN 列表，这些参数不在用户配置接口中开放。

## 云端协调服务

可使用同一台 ECS 部署协调服务和带鉴权的 STUN/TURN 服务。协调服务不加载 AgentPark 图、模型配置或用户对话，不需要安装 WebRTC/音视频依赖。

最小 Python 服务目录包含仓库的 `src/__init__.py`（如存在）、`src/file_transaction.py` 和整个 `src/peer_network/`。云端页面还需要在 `webui` 下运行 `npm ci`、`npm run build`，把完整 `webui/dist/` 一并部署，其中必须包括 `portal-sw.js`。也可以用单独的代码检出目录，但不要复制本地 `.auth`、配置密钥或记忆数据。云端无需运行本地 AgentPark 业务后端。

本地 Board 和云端 Board 分别使用各自服务器上的前端构建。顶部「更新并重启」只更新所连接的设备，不会发布云端前端；涉及手机页面或请求协议的前端修改，必须同步部署云端 `webui/dist/`。发布后核对公网首页引用的 JS/CSS 指纹及文件校验值，并重新加载手机浏览器页面。聊天首屏应请求 `history_mode=conversation`，点击某轮过程后才请求 `history_mode=turn_details&turn_id=...`；仅验证本地手机接口不能证明公网页面已经使用新协议。

```text
python -m pip install -r deploy/peer-network/requirements.txt
python -m src.peer_network.signaling
```

环境变量：

| 变量 | 含义 |
| --- | --- |
| `AGENTPARK_SIGNALING_HOST` | 默认 `127.0.0.1` |
| `AGENTPARK_SIGNALING_PORT` | 默认 `8790` |
| `AGENTPARK_PORTAL_PASSWORD` | 至少 8 字符的独立管理员密码；未设置时登录入口返回未配置错误 |
| `AGENTPARK_PORTAL_WEB_ROOT` | 前端构建目录，默认 `webui/dist` |
| `AGENTPARK_SIGNALING_STATE` | 云端签名私钥目录，默认 `.auth/coordinator`；systemd 示例使用 `/var/lib/agentpark-signaling` |

云端管理员登录有效期固定为登录后的 3 天（72 小时），Cookie 与服务端会话使用相同到期时间，访问不会滑动续期；目前没有有效期配置项。同一浏览器保留 Cookie 即可在有效期内免登录。主动退出、清除 Cookie 或协调服务重启会使登录提前失效（会话保存在内存中）。单次 Board 连接及设备访问票据仍最长 1 小时，并且不能超过登录到期时间；连接到期后前端使用现有登录自动重连，无需重新输入密码。

示例 systemd 和 Caddy 配置位于 `deploy/peer-network/`。Caddy 把该域名全部路径交给协调服务，提供首页、`/board/...`、`/assets/...`、`/portal-sw.js`、登录/设备列表和两类信令 WebSocket。服务没有向设备转发普通 `/api/...` 的云端业务路由。部署环境文件包含管理员密码，应限制读取权限；签名私钥和设备批准记录目录应持久化。部署需要可信 HTTPS 证书和服务运行账户；无域名的私有部署使用 IP 证书，`nginx-ip.conf` 提供对应入口示例。

部署使用 coturn 的 `use-auth-secret` 模式。`deploy/peer-network/configure_turn.py` 在服务器生成共享密钥，同时配置协调服务和 TURN；密钥只保存在服务器的受限配置文件中。协调服务为已批准设备、已登录且通过身份挑战的浏览器签发一小时有效的临时凭证（浏览器不超过登录会话期限）。设备每约十分钟更新内存中的凭证，后续新建连接使用新凭证；临时凭证不写入本地配置、不放入设备列表、URL 或日志。中继凭证不代替现有签名信令、Board 票据和逐次业务权限校验。

`AGENTPARK_TURN_URLS` 为带显式端口和传输类型的 JSON 数组；`AGENTPARK_TURN_SECRET` 必须与 coturn 一致且至少 32 字符。必须同时配置两者；缺少一项时启动失败。两者都未设置时只收集 STUN/直连候选，供本机测试或明确无需中继的部署使用。

部署示例把 TCP 3478 放在 TURN URL 列表首位，并同时向浏览器提供 UDP 3478。当前 aiortc 只使用第一个 TURN URL，因此电脑端经 TCP 接入中继，仍可绕过客户端出站 UDP 限制；浏览器可以收集两种路径。无论客户端到 TURN 使用 TCP 还是 UDP，WebRTC 的中继分配都使用服务器 UDP 49160–49259。云端安全组需要开放 TCP/UDP 3478 和 UDP 49160–49259，并允许 TURN 向公网对端的 UDP 端口出站；`external-ip` 必须对应 ECS 公网地址与网卡私网地址。配置禁止向内网、回环、链路本地和组播目标转发，并限制分配数量。

首次安装需设置 `AGENTPARK_PUBLIC_IP` 和 `AGENTPARK_PRIVATE_IP` 再运行 `install-ecs.sh`。从旧部署升级时停用 `agentpark-stun`，启用 `agentpark-turn`，重启协调服务，并更新、重启各设备后端。旧后端不支持新的 ICE 凭证握手，必须与云端一起更新。当前部署没有启用 TURN TLS；只允许 HTTPS 443 出站的网络仍可能无法连接。[coturn 官方配置](https://github.com/coturn/coturn/blob/master/examples/etc/turnserver.conf)

云服务器需要开放 HTTPS、TURN TCP/UDP 3478 和 UDP 中继端口范围。直连数据不受云服务器带宽限制；TURN 中继数据占用 ECS 带宽，并与页面、鉴权、信令共享带宽。当前协调服务默认最多 100 台同时在线设备、100 个管理员会话，每个会话最多 8 个 Board；这些是程序保护上限，不是该 ECS 配置的压测容量承诺。设备目录与登录会话在进程内保存，部署一个协调进程，不能直接开启多个独立 worker。

## 验证与边界

```text
python -m pytest tests/test_peer_enrollment.py tests/test_peer_network_security.py tests/test_peer_operations.py tests/test_peer_network_direct.py tests/test_peer_backend_integration.py tests/test_peer_portal.py -q
```

真实协议测试启动独立协调服务与两个独立身份的 aiortc 实例，使用空 STUN 列表，验证双向直连、超过单帧的响应、协调服务连接关闭后继续通信，以及连接中修改权限和撤销授权。测试中的业务回调用于隔离传输验证，不调用真实模型。

业务测试验证远程查询投影、共享范围、三类权限、来源身份、入队调用和持久化接收凭证；现有移动端、工作机和权限测试验证回归。

云端测试覆盖登录与来源校验、在线列表、浏览器会话票据、设备与浏览器签名交换、关闭撤销、敏感接口拒绝、非本机身份、私有事件过滤和会话内删除撤销。浏览器人工验证使用隔离临时画板目录、关闭模型执行的后端，实际完成登录、点击设备、打开 Board、消息入队与保存画板。后端测试依赖 `tests/conftest.py` 的独立记忆目录；独立预览脚本也必须显式隔离 `src.memory_root`，只替换运行目录不足以隔离画板数据。

这些本机检查不能证明跨运营商 NAT 打洞成功、ECS HTTPS 入口可用、Windows 防火墙已放行、发布包已重新构建，或真实 Agent 已完成跨设备任务。上线验收需要两台不同网络下的真实设备完成一次人工消息和一次 Agent 回复，并确认实际使用的直连或中继路径。可用强制只保留 relay 候选的协议探针验证中继数据确实可传输；这不代替用户手机 5G 网络的实际验收。


## 当前 ECS：私有 CA（2026-09-12 已切换）

入口仍为 `https://203.0.113.10`，WSS 443、设备身份和批准记录保持不变。
本机 Windows 当前用户已导入根证书；Python 默认 TLS 校验已通过，并已让正在运行的
AgentPark 设备连接重新建立，确认 `coordinator_connected=true`、`enrollment_state=approved`。

- 根 CA 有效至 2036-09-09（UTC）。签发私钥只在 Windows `.auth/private-ca/root-key.dpapi`
  中，使用当前 Windows 用户 DPAPI 加密，不上传 ECS。该加密文件依赖原 Windows 用户环境，
  单独复制到另一台电脑不能视为可恢复的离线备份；保留本机账户及系统备份。
- ECS 下级 CA 有效至 2031-09-11（UTC），密钥在
  `/var/lib/agentpark-tls/private-ca/issuer-key.pem`（root 0600，父目录 0700）。
  证书包含关键 Name Constraints，仅允许 `203.0.113.10/32`，排除所有 DNS 名称；
  path length 为 0，不能再签发下级 CA。更换公网 IP 需要用离线根重新签发下级 CA。
- 服务器叶证书有效 90 天，SAN 仅包含服务器 IP，仅允许 TLS serverAuth。
  TLS 私钥仍留在 ECS `/var/lib/agentpark-tls/server-key.pem`。
- `agentpark-private-certificate.timer` 在 ECS 每天检查一次，随机延迟最多 30 分钟，
  剩余有效期不超过 30 天时签发、验证并重新加载 Nginx。错过时间会补跑。
  不依赖外部 CA、Workbench 或 Windows 电脑在线。
- 下级 CA 到期前 120 天，续期检查明确报错，需要用离线根更新下级 CA。
  日常状态见 `/var/lib/agentpark-tls/private-ca/renewal-status.json`；失败见 systemd journal，
  本任务未配置外部消息通知。
- 根证书和新设备安装说明位于 `deploy/peer-network/client-trust/`，目录不包含私钥。
  Windows 脚本安装到当前用户 Root 存储。其他系统或使用独立证书库的程序需单独安装信任。
  尚未配置的手机和其他电脑会拒绝新证书，必须先导入这份根证书。

部署职责：`private_ca.py` 定义签发约束；`create_private_root.py` 在 Windows 创建根并签署
ECS 生成的下级 CSR；`private_ca_server.py` 在 ECS 签发叶证书；`tls_server.py` 验证 IP、
有效期、密钥匹配和完整证书链，再原子替换证书并 reload Nginx。

### 原公网证书方案：已停用，仅用于短期恢复

Windows 任务 `AgentPark-ECS-Certificate-Renew` 已禁用。原 ACME 脚本在检测到本地私有
CA 状态后拒绝运行，以免误切回公网证书。原公开证书保留在 ECS
`/var/lib/agentpark-tls/public-fullchain-backup.pem`，有效期至 2026-09-19 05:38:23 UTC；
过期后不可作为恢复入口。原签发账户仍以 DPAPI 加密保存在 `.auth/acme/`。

需要短期恢复时，先确认备份证书仍有效，将其复制到 `incoming.pem` 并通过原公有根安装
验证，再停用私有续期 timer；恢复公有续期还需明确迁移本地私有 CA 状态并重新启用 Windows
任务。正常运行不应混用两套续期任务。

## TURN 实际路径验证

在装有 AgentPark 运行依赖的电脑上执行 `python deploy/peer-network/probe_turn.py --portal-url https://<服务器IP> --device-name <设备名称>`，按提示输入管理员密码。探针通过正常管理员登录、浏览器身份挑战和签名信令建立真实 Board 通道，依次验证自动选择、强制 TCP 中继、强制 UDP 中继。强制测试不创建本机直连套接字，并要求选中的两端候选都为 relay，然后通过加密通道只读请求系统状态、访问权限和画板列表。报告仅包含路径类型、响应字节数和权限结果，不输出凭证或画板内容。它会退出自己的登录会话，不改动设备上的画板或节点。
