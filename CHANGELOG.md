# 更新日志

## v0.1.5 — 并发安全与可靠性改进 (2026-05-22)

### 修复

- **LiveMonitor 线程竞态**：增加 `threading.Lock` 保护 LiveMonitor 与主线程并发写 TaskState
- **SIGINT 死锁风险**：移除自定义 SIGINT 信号处理器，改用 `KeyboardInterrupt` 捕获避免 ffmpeg `communicate()` 死锁
- **StreamlinkResolver 硬编码 python**：使用 `sys.executable` 替代硬编码 `"python"`，修复仅有 `python3` 的系统
- **task_state.json 原子写入**：使用 `.tmp + rename` 模式防止崩溃时文件损坏
- **配置未知键静默忽略**：统一使用 `_filter_known()` 对未知配置键产生 warning
- **DouyinPageResolver session 泄漏**：增加 `close()` 方法并在 `DouyinResolver` 中使用 try/finally 确保关闭
- **Douyin resolver 配置未注入**：`platforms.douyin.resolver` 配置现在正确传入 `DouyinResolver`
- **Chunker 超大 segment**：修正 flush 条件，对超过 `max_chars` 的 segment 产生警告
- **yt-dlp 代码重复**：提取共享 `run_ytdlp()` 函数和 `YtdlpError`，适配器委托调用

### 新增

- **LLM 调用重试**：OpenAI/Anthropic provider 增加指数退避重试（429/500/502/503）
- **hatch 动态版本**：`pyproject.toml` 使用 `__init__.py` 作为唯一版本来源

### 变更

- 版本号统一为 v0.1.5，修复 `pyproject.toml` 与 `__init__.py` 不一致问题

## v0.1.4 — 抖音工作流、直播误判修复、getnote 安全加固 (2026-05-10)

### 修复

- **直播结束误判彻底修复**：解决因网络波动、HLS 地址过期、check_live 失败等导致直播被误判为"已结束"的问题
- **单次 ffmpeg 退出不再判定为直播结束**：ffmpeg 退出后自动触发重连流程
- **单次 check_live 失败不再判定为直播结束**：区分 ERROR/UNKNOWN 与 NOT_LIVE
- **仅连续多次 NOT_LIVE 才确认直播结束**（默认 3 次），避免偶发超时触发停止
- **getnote 导入仅限当前任务**：新增路径校验，禁止导入其他任务、transcripts、chunks、summaries
- **抖音 metadata 标题修复**：标题不再回退到 task_id，使用 display_title 格式
- **source_url 不再被 stream_url 覆盖**：原始直播间地址始终保留

### 新增

- **抖音多级解析工作流**：`--stream-url` → yt-dlp → streamlink → page_public_data → Playwright → 手动兜底
- **DouyinPageResolver**：支持 `v.douyin.com` 短链重定向、`webcast.amemv.com` 页面 FLV 提取
- **Playwright headed 降级**：遇到强反爬房间时自动启动 Chromium 拦截流地址
- **ResolveResult 数据模型**：独立于 CheckResult，描述流地址解析结果
- **`live2note resolve` 命令**：只解析直播流，不录制，默认脱敏显示
- **`live2note metadata` 命令**：查看当前任务完整 metadata
- **`live2note rebuild-note` 命令**：从已有数据重建 final_note.md
- **`import-getnote --dry-run`**：预览导入目标，不真正调用 API
- **safe_url 日志工具**：全链路脱敏 stream URL
- **LiveCheckStatus 枚举**：LIVE / NOT_LIVE / UNKNOWN / ERROR
- **LiveMonitor 三态区分**：LIVE 重置、NOT_LIVE 确认、ERROR 计数
- **FfmpegRecorder 重连循环**：失败后自动重解析 + 重试（最多 20 次）
- **`--no-auto-stop` / `--max-reconnect-attempts` / `--cookie-file` / `--debug-resolve` / `--show-stream-url` 参数**
- **display_title / author 字段**：TaskMetadata 统一，getnote 标题从 markdown H1 提取
- **`final_note.md` 增加录制时长、录制状态、平台中文化**

### 变更

- `no_data_timeout_seconds` 默认 180→600（10 分钟）
- `max_live_check_failures` 默认 3→5（仅对 ERROR/UNKNOWN 生效）
- adapter `check_live` 返回 `live_status` 替代二元 `is_live`
- `getnote.command` 字段移除（统一使用 HTTP API）
- getnote 导入前强制路径校验（名称、父目录、task 内、非空）
- 录制中断重连使用 `safe_url()` 记录
- 测试从 224 增加到 322

## v0.1.3 — 增强转写与说话人识别 (2026-05-05)

### 新增

- **增强转写配置**：新增 `initial_prompt`、`glossary`（热词）、`word_timestamps` 配置项
- **说话人识别（可选）**：集成 pyannote.audio 声纹识别，识别"谁在何时说话"
  - 需额外安装：`pip install live2note[diarization]`
  - 需设置环境变量：`HUGGING_FACE_HUB_TOKEN=hf_...`
  - 自动将说话人标签映射到转写文本
- **说话人标签写入转写文件**：JSON 转写增加 `speaker` 字段，Markdown 转写增加 `**SPEAKER_00**` 前缀
- **新增 CLI 命令**：
  - `live2note speakers <task_id>` — 查看所有说话人列表
  - `live2note rename-speaker <task_id> <原标签> <新名字>` — 重命名说话人
- **转写 CLI 参数**：`live2note run` 和 `live2note transcribe` 新增 `--initial-prompt`、`--lang`、`--model` 参数
- **最终笔记增加说话人信息**：final_note.md 增加「说话人」章节，展示每个说话人的发言次数
- **新增配置示例**：`config.example.yaml` 新增 `diarization` 配置段

### 变更

- TranscriptionConfig 新增 `initial_prompt`、`glossary`、`word_timestamps` 字段
- WhisperEngine 支持 `hotwords`、`initial_prompt`、`word_timestamps` 参数传递给 faster-whisper
- TaskState 新增 `speakers` 字典字段用于说话人重命名映射

### 依赖

- `pyannote.audio>=3.1` 作为可选依赖（`[diarization]` extra）

## v0.1.2 — 修复 CI lint (2026-05-05)

### 修复

- 修复 ruff lint 错误（未使用的 import、import 块排序问题）
- tests 文件 import 块按 stdlib → third-party → first-party 规范排序

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
