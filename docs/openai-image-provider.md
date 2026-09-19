# Agent 节点图片生成

Agent 节点选择 Provider `GPT_Image_2_5`，使用模型 `gpt-image-2.5`。
Provider 只声明 `image_generation`，节点会自动选择图片模式，无需启用图片 Skill。

- 使用 AgentPark 已保存的 OpenAI / Codex 登录账号。
- 发送文字提示词生成图片；附带图片或设置 `image_references` 时执行编辑。
- 尺寸、质量和背景均使用 `auto`，与 Codex 内置图片工具的请求保持一致。
- 图片写入节点目录的 `generated_images`，通过图片资源消息展示和传递。
- 超时为 180 秒，普通请求及过载重试次数均为 0；认证恢复沿用 OpenAI transport。
- 图片模式不调用对话历史压缩或长期记忆模型。

安装代码更新后重启后台服务。配置加载和模拟接口测试不代表账号具有该模型的服务端访问权限；接口错误会直接报告。
