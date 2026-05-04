# 更新日志

## v0.1.1 — 默认 external_cli (2026-05-05)

### 变更

- **默认 LLM Provider 改为 external_cli**：不再要求用户单独配置 API Key
- 默认通过本机已登录的 Agent CLI 进行知识总结（`claude -p`）
- external_cli 不可用时自动 fallback 到 prompt_only，不中断流程
- openai_compatible / anthropic 模式需用户显式启用，不再是默认行为
- 新增 `llm-doctor` / `llm-test` CLI 诊断命令
- 新增 `export-prompts` 命令，导出 prompt 文件供手动处理
- 新增 `--provider` 参数，支持 CLI 级别覆盖 LLM provider
- ExternalCLIProvider 支持 Windows `.cmd`/`.exe` 后缀自动检测
- 支持 Claude Code、Codex、OpenCode、OpenClaw、Hermes、cg 等多种 Agent CLI 自动发现

### 安全

- 明确禁止读取任何外部工具的私有配置文件
- 不扫描 `~/.claude/`、`~/.codex/`、`~/.config/` 等目录
- 不读取系统密钥链
- 日志中 Token 自动脱敏（前4后4）
- prompt 内容不在日志中完整打印（仅记录长度）

## v0.1.0 - 初始版本 (2026-05-05)

### 新增

- 支持 B站直播间地址输入，自动识别平台
- 支持抖音直播间地址输入，自动识别平台
- 支持通用直播流地址（m3u8 / flv / rtmp / http stream）
- 使用 ffmpeg 录制直播音频，按时间分片保存为 WAV（16 kHz 单声道）
- 使用 faster-whisper 在本地进行语音转写，保留时间戳
- 转写文本自动清洗（去口头禅、去重复、合并碎片）
- 按语义将转写文本分块，每块 800–1500 字
- 调用 LLM（OpenAI 兼容 API）对每个分块提取摘要、核心观点、知识点、可执行建议、关键词和标签
- 生成结构化的 Markdown 知识库笔记（final_note.md）
- 生成结构化的 JSON 知识库文件（final_note.json），适合向量数据库或 RAG
- 支持导入 getnote，方便后续语义搜索
- 完整的任务状态管理系统（task_state.json），支持状态机流转和流程检查点
- 支持断点续跑（resume）：工具中断后可从上次完成位置继续
- 支持手动停止录制（live2note stop）
- 支持直播结束自动停止（LiveMonitor 后台检测）
- 支持 Windows、macOS、Linux 三平台
- YAML 配置文件，支持环境变量覆盖敏感信息
- 完善的中文 README 和使用文档
- GitHub Actions CI（Ubuntu + Windows，Python 3.10–3.13）

### 已知限制

- 本版本为初始版本，平台直播流解析能力可能受平台规则和链接状态影响
- 抖音直播如自动解析失败，可使用通用直播流模式作为替代方案
- 直播监控目前依赖 yt-dlp 解析，对非标准平台支持有限
- 无图形界面，仅支持命令行操作

### 注意

- 本工具仅用于个人学习和知识整理
- 不支持绕过 DRM、付费墙或平台访问控制
- 请遵守当地法律法规和平台服务条款
