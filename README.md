# live2note

> 将 B站、抖音等直播平台的直播内容录制、转写、整理为知识库笔记，并导入 getnote 的开源 CLI 工具。

[![CI](https://github.com/MemoryKD/live2note/actions/workflows/ci.yml/badge.svg)](https://github.com/MemoryKD/live2note/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

## 项目简介

live2note 是一个命令行工具，用于将 B站、抖音等直播平台上分享干货的主播直播内容，自动录制音频、本地转写为文字、调用 LLM 整理为结构化知识库，并导入 getnote 方便后续搜索。

你可以把它理解为「直播知识采集 Agent」——输入一个直播间地址，它自动完成从录音到知识笔记的全流程。

## 核心功能

- 输入直播间地址，自动识别平台（B站、抖音、通用流）
- 使用 ffmpeg 录制直播音频，按时间分片保存
- 使用 faster-whisper 在本地转写音频为文字
- 调用 LLM（OpenAI 兼容 API）自动提取摘要、核心观点、可执行建议和关键词
- 生成结构化的 Markdown 和 JSON 知识库文件
- 支持导入 getnote，方便后续语义搜索
- 完整的任务状态管理，支持断点续跑
- 支持手动停止（`live2note stop`）和直播结束自动停止
- **智能直播结束检测**：区分网络波动与真正下播，仅连续确认才停止
- **自动重连**：ffmpeg 因 HLS 地址过期或网络中断退出后，自动重试并解析新地址

## 使用场景

- 个人学习：录制知识类直播，整理为可搜索的笔记
- 内容复盘：回顾直播中的关键观点和知识要点
- 知识管理：将直播内容转化为结构化知识库

**本工具仅用于个人学习和知识整理，不用于未授权传播。**

## 安装前准备

### 系统要求

- Python 3.10 及以上
- [ffmpeg](https://ffmpeg.org/download.html)（音频录制）
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)（直播流地址解析）
- [getnote](https://github.com/nicepkg/getnote)（可选，知识库导入）

### 安装 ffmpeg

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Windows (winget)
winget install FFmpeg

# 或者从官网下载：https://ffmpeg.org/download.html
```

### 安装 yt-dlp

```bash
pip install yt-dlp
```

### 安装 getnote（可选）

参考 [getnote 安装文档](https://github.com/nicepkg/getnote)。

## 安装方法

```bash
# 从 GitHub 克隆
git clone https://github.com/MemoryKD/live2note.git
cd live2note

# 安装（开发模式）
pip install -e ".[dev]"

# 生成默认配置
live2note config-init

# 验证安装
live2note --help
```

## 快速开始

```bash
# 生成配置文件
live2note config-init

# 录制 B站直播间（30 分钟，并导入 getnote）
live2note run "https://live.bilibili.com/xxxx" --duration 30 --getnote

# 录制抖音直播间
live2note run "https://live.douyin.com/xxxx" --getnote

# 录制通用直播流
live2note run "https://example.com/live.m3u8" --platform generic --getnote

# 查看任务状态
live2note status

# 列出所有任务
live2note list

# 手动停止录制
live2note stop <task_id>

# 断点续跑
live2note resume <task_id>

# 单独导入 getnote
live2note import-getnote <task_id>
```

## 命令行参考

| 命令 | 说明 |
|------|------|
| `live2note run URL` | 录制直播、转写、整理、导出（全流程） |
| `live2note watch URL` | 等待直播开始，开播后自动录制 |
| `live2note transcribe TASK_ID` | 转写任务的音频片段 |
| `live2note process TASK_ID` | 清洗、分块、LLM 总结转写内容 |
| `live2note save TASK_ID` | 生成 final_note.md 和 final_note.json |
| `live2note import-getnote TASK_ID` | 将最终笔记导入 getnote |
| `live2note stop TASK_ID` | 停止正在进行的录制任务 |
| `live2note resume TASK_ID` | 从中断点继续执行任务 |
| `live2note status [TASK_ID]` | 查看任务状态和流程进度 |
| `live2note list` | 列出所有任务 |
| `live2note llm-doctor` | 检查 LLM 配置和可用性 |
| `live2note llm-test` | 发送测试 prompt 给配置的 LLM |
| `live2note export-prompts TASK_ID` | 导出总结 prompt 文件 |
| `live2note config-init` | 生成默认配置文件 |

### run 命令常用选项

```
live2note run URL [OPTIONS]

  --platform TEXT       平台：auto | bilibili | douyin | generic（默认 auto）
  -d, --duration INT    录制时长（分钟），0 为手动停止（默认 0）
  -s, --segment INT     每段音频时长（分钟，默认 5）
  --stream-url TEXT     直接指定直播流地址
  -g, --getnote         处理完成后导入 getnote
  --getnote-tag TEXT    getnote 标签（可重复）
  --no-check            跳过直播状态检测
  --no-record           跳过录制（仅创建任务）
  --no-auto-stop        禁用自动停止（直到手动 Ctrl+C 或时长限制）
  --max-reconnect-attempts INT  覆盖最大重连次数（-1 使用配置）
  -c, --config PATH     指定配置文件路径
```

## 配置文件说明

运行 `live2note config-init` 生成 `~/.live2note/config.yaml`。

关键配置项：

```yaml
recording:
  segment_duration: 5             # 每段音频时长（分钟）
  ffmpeg_path: "ffmpeg"           # ffmpeg 可执行文件路径
  stop_grace_seconds: 10          # 停止录制时的优雅等待时间
  no_data_timeout_seconds: 600    # 无数据超时自动停止（10 分钟）
  live_check_interval_seconds: 60 # 直播状态检测间隔
  max_live_check_failures: 5      # 连续检测失败上限（仅对 ERROR/UNKNOWN 生效）
  live_end_confirmations: 3       # 连续 NOT_LIVE 确认次数后判定直播结束
  reconnect_enabled: true         # 是否启用自动重连
  reconnect_delay_seconds: 10     # 重连尝试间隔
  max_reconnect_attempts: 20      # 最大重连尝试次数

transcription:
  model_size: "large-v3"          # whisper 模型大小
  language: "zh"                  # 语言代码
  device: "auto"                  # auto | cpu | cuda

llm:
  provider: auto                  # auto | openai_compatible | anthropic | external_cli | prompt_only | none
  model: "gpt-4o"
  api_base: "https://api.openai.com/v1"
  api_key: ""                     # 或通过环境变量设置
  external_cli:
    enabled: false
    command: ""                   # e.g. "claude -p" or "codex exec"

getnote:
  enabled: false                  # 是否默认导入 getnote
  default_tags: ["live2note"]
  timeout: 120                    # 秒

output:
  base_dir: ""                    # 数据保存目录（空 = ~/.live2note/data/tasks）
  keep_audio: true                # 是否保留音频文件
  keep_intermediate: true         # 是否保留中间文件
```

**注意：不要在配置文件中写入真实 API Key。建议使用环境变量 `LLM_API_KEY`。**

完整配置选项见 [`config.example.yaml`](config.example.yaml)。

## 默认 LLM 模式：external_cli

live2note **默认使用 external_cli 模式**，不要求用户单独配置 API Key。

### 默认工作方式

```
live2note 构建总结 Prompt
  → 调用本机已登录的外部 Agent CLI
  → 例如 claude -p
  → 读取 stdout 作为总结结果
  → 保存为知识库笔记
```

### 为什么默认使用 external_cli？

1. 用户通常已经在 Claude Code、Codex、OpenCode、OpenClaw、Hermes 等工具中登录
2. live2note 不需要直接保存 API Key，更安全
3. 更适合本地 Agent 工作流
4. 更适合开源项目
5. 不读取任何内部 Token，完全透明

### 默认配置

```yaml
llm:
  provider: external_cli
  external_cli:
    enabled: true
    command: "claude"
    args: ["-p"]
    timeout_seconds: 600
    fallback_to_prompt_only: true
```

### 如果 external_cli 不可用

live2note 会自动降级到 **prompt_only 模式**：

1. 正常完成转写和分块
2. 每个 chunk 的 prompt 写入 `prompts/chunk_NNN_prompt.md`
3. 提示用户手动复制 prompt 到任意 LLM 处理
4. **不会导致录音、转写、分块失败**

```powershell
# 查看导出的 prompt 文件
ls ~/.live2note/data/tasks/<task_id>/prompts/
```

### 如果我不用 Claude Code

修改 `external_cli.command` 和 `args` 即可：

**Codex：**
```yaml
llm:
  provider: external_cli
  external_cli:
    enabled: true
    command: "codex"
    args: ["exec"]
```

**OpenCode：**
```yaml
llm:
  provider: external_cli
  external_cli:
    enabled: true
    command: "opencode"
    args: []
```

**其他工具同理**，只要支持从 stdin 接收 prompt、从 stdout 输出结果。

### 如果我想用 API Key

显式配置 `provider: openai_compatible` 或 `provider: anthropic`：

```yaml
llm:
  provider: openai_compatible
  api_key: "sk-your-key"
  model: "gpt-4o"
```

**这不是默认模式，需要用户显式启用。**

### LLM 诊断命令

```powershell
live2note llm-doctor                      # 检查 LLM 配置
live2note llm-test                        # 测试默认 external_cli
live2note llm-test --provider prompt_only # 测试降级模式
live2note export-prompts <task_id>        # 导出 prompt 文件
```

### 安全声明

1. live2note 不读取 Claude Code、Codex 等工具的内部 Token
2. live2note 不扫描用户本地认证文件（`~/.claude/`、`~/.codex/` 等）
3. live2note 不读取系统密钥链
4. live2note 不在日志中输出 API Key（自动脱敏）
5. external_cli 的认证由外部 Agent 自己处理
6. prompt 内容不在日志中完整打印（仅记录长度）
7. 不要求普通用户单独配置 API Key

## 输出目录说明

```
~/.live2note/data/tasks/<task_id>/
  task_state.json          # 任务状态与流程检查点
  metadata.json            # 直播元信息（标题、主播等）
  control/
    stop.flag              # 停止信号文件
  audio_segments/
    segment_001.wav        # 16 kHz 单声道 WAV
    segment_002.wav
  transcripts/
    segment_001.json       # 带时间戳的转写结果
    segment_001.md         # 人类可读的转写文本
  chunks/
    chunks.json            # 清洗分块后的文本
  summaries/
    chunk_summaries.json   # LLM 逐块总结
  notes/
    final_note.md          # 结构化知识笔记
    final_note.json        # JSON 格式（用于向量数据库 / RAG）
  logs/
    task.log               # 任务日志
```

## 抖音直播录音说明

抖音直播间地址通常不是最终可录制的流地址。live2note 会尝试自动解析真实直播流，使用以下多级策略：

1. **`--stream-url` 手动提供**（最高优先级）
2. **yt-dlp** 解析（通过配置启用）
3. **streamlink** 解析（推荐，对抖音兼容性最好）
4. **手动兜底**（如果所有自动策略失败）

### 安装 streamlink（推荐）

```bash
pip install streamlink
```

### 解析命令

```bash
# 只解析直播流地址，不录制
live2note resolve "https://live.douyin.com/xxxx" --platform douyin

# 显示完整 stream URL
live2note resolve "https://live.douyin.com/xxxx" --platform douyin --show-stream-url

# 显示解析诊断信息
live2note resolve "https://live.douyin.com/xxxx" --platform douyin --debug-resolve

# 使用 cookie 文件
live2note resolve "https://live.douyin.com/xxxx" --platform douyin --cookie-file ./cookies.txt
```

### 录制命令

```bash
# 全自动（需要 streamlink 已安装）
live2note run "https://live.douyin.com/xxxx" --platform douyin --getnote

# 禁用自动停止（推荐，避免因 check_live 失败而中断）
live2note run "https://live.douyin.com/xxxx" --platform douyin --no-auto-stop --getnote

# 手动传入 stream URL（自动解析失败时）
live2note run "https://live.douyin.com/xxxx" --platform douyin --stream-url "https://xxx.m3u8" --getnote
```

### 录制中断与重连

抖音流地址会定期过期。当 ffmpeg 因网络波动或地址过期退出时：
- 系统自动触发重连流程（默认最多 20 次，每次间隔 10 秒）
- 重新调用解析器获取新的流地址
- 不会将单次中断判定为直播结束
- 仅连续多次 NOT_LIVE 确认才停止录制

### 注意事项

- 自动解析可能受平台页面变化、登录状态、直播状态影响
- 使用 `--no-auto-stop` 可以避免因检测失败导致录制中断
- 本工具不绕过平台权限，不破解加密，不处理无权限内容
- 日志中不会记录完整 stream URL（使用 `--show-stream-url` 可显示）

## 支持平台

| 平台 | URL 格式 | 解析方式 |
|------|---------|---------|
| B站 (Bilibili) | `live.bilibili.com/<房间号>` | yt-dlp |
| 抖音 (Douyin) | `live.douyin.com/<房间号>` | yt-dlp |
| 通用流 | `.m3u8` / `.flv` / `rtmp://` | ffmpeg 直连 |

## getnote 导入说明

live2note **只导入当前任务的 `notes/final_note.md`**，不会导入以下内容：

- 不会导入 transcripts（转写文件）
- 不会导入 chunks（分块文件）
- 不会导入 summaries（总结文件）
- 不会导入 prompts（LLM prompt 文件）
- 不会导入其他 task 的笔记
- 不会导入项目文档（README、CHANGELOG 等）

```bash
# 预览即将导入的文件（不实际导入）
live2note import-getnote <task_id> --dry-run

# 导入当前任务的 final_note
live2note import-getnote <task_id>
```

- 当 `--getnote` 标志或配置中 `getnote.enabled: true` 时，录制完成后自动导入
- 如果 `final_note.md` 不存在或为空，会明确报错提示
- 导入失败不影响本地文件保存，可稍后重试
- 如果 getnote 中出现无关笔记，说明版本较旧或配置错误，需要更新

## 停止录制说明

live2note 支持三种停止方式：

**方式一：直播结束自动检测停止**

系统通过 LiveMonitor 定时检查直播状态，智能检测直播结束：

- **LIVE**：正常直播，重置所有计数器
- **NOT_LIVE**：平台确认直播已结束，递增确认计数（默认连续 3 次才判定结束）
- **ERROR/UNKNOWN**：网络波动或检测失败，递增错误计数（默认连续 5 次才停止）

检测到直播结束后：
1. 自动停止 ffmpeg 录制
2. 保存已录制的音频片段
3. 继续完成转写、总结、生成笔记
4. 任务状态标记为 `COMPLETED`

**自动重连**

当 ffmpeg 因网络波动或 HLS 地址过期退出时，系统会自动：

1. 记录 ffmpeg 退出码和错误信息
2. 等待重连间隔（默认 10 秒）
3. 调用 `adapter.resolve_stream_url()` 获取新的流地址
4. 使用新地址重新启动 ffmpeg
5. 最多重试 20 次（可配置）

**方式二：手动停止**

```bash
live2note stop <task_id>        # 优雅停止
live2note stop <task_id> --force # 强制停止
```

**方式三：--no-auto-stop 模式**

对于抖音等 check_live 可能频繁失败的平台，可以使用 `--no-auto-stop`：

```bash
live2note run "https://live.douyin.com/xxxx" --no-auto-stop
```

此模式下：
- LiveMonitor 不启动
- 录制只会在 Ctrl+C、时长限制、或 `live2note stop` 时停止
- 不会因 check_live 失败而自动停止

## 注意事项与合规声明

**本工具仅用于个人学习和知识整理。**

- 用户需要确保自己有权限观看和处理相关直播内容
- 本工具不支持绕过 DRM、付费墙、登录限制或平台访问控制
- 不鼓励也不支持未经授权的内容传播
- 用户需要自行遵守平台规则和当地法律法规
- 录制内容默认仅供个人学习和知识整理使用

## 常见问题

### ffmpeg 找不到怎么办？

请确保已安装 ffmpeg 并加入 PATH。安装方法见[安装前准备](#安装前准备)。

```bash
# 验证安装
ffmpeg -version
```

### yt-dlp 解析失败怎么办？

部分平台可能需要浏览器环境。可以尝试：
1. 在浏览器中打开直播间
2. 使用开发者工具（F12 → 网络）找到 `.m3u8` 或 `.flv` 地址
3. 使用通用流模式：`live2note run <流地址> --platform generic`

### 抖音直播解析失败怎么办？

抖音的反爬机制可能导致 yt-dlp 无法直接获取流地址。建议：
1. 在浏览器中打开直播间
2. 使用开发者工具获取 `.flv` 流地址
3. 使用 `live2note run <流地址> --platform generic`

### faster-whisper 转写太慢怎么办？

- 使用更小的模型：`--model tiny` 或 `--model small`
- 如果有 NVIDIA GPU，安装 CUDA 并在配置中设置 `device: "cuda"`
- 使用 CPU 时可以选择 `medium` 模型在速度和精度之间取得平衡

### getnote 导入失败怎么办？

- 检查 getnote 是否已安装：`getnote --help`
- 检查 getnote 登录状态：`getnote auth`
- 导入失败不会影响本地文件，可以稍后使用 `live2note import-getnote <task_id>` 重试

### 如何手动停止录制？

在另一个终端执行：

```bash
live2note stop <task_id>
```

已录制的音频和已完成的处理不会丢失。

### 如何断点续跑？

任务中断后（Ctrl+C、手动停止、错误），使用：

```bash
live2note resume <task_id>
```

工具会自动跳过已完成的步骤，从中断处继续。

### 数据保存在哪里？

默认保存路径：`~/.live2note/data/tasks/<task_id>/`

可在配置文件中通过 `output.base_dir` 修改。

## 开发说明

### 项目结构

```
src/live2note/
  cli.py              # Typer CLI 入口（所有命令）
  pipeline.py          # 流水线执行器
  config.py            # YAML 配置加载
  task_manager.py      # 任务管理
  models/task.py       # 任务状态数据模型
  adapters/            # 平台适配器（bilibili / douyin / generic）
  recorder/            # ffmpeg 录制 + 停止控制 + 直播监控
  transcriber/         # faster-whisper 转写
  processor/           # 清洗 / 分块 / LLM 总结 / 笔记生成
  storage/             # Markdown / JSON 写入 + getnote 导入
```

### 安装开发依赖

```bash
pip install -e ".[dev]"
```

### 运行测试

```bash
# 运行所有测试
pytest

# 带覆盖率
pytest --cov=live2note --cov-report=term-missing

# 单个测试文件
pytest tests/test_cli.py -v
```

### 代码质量检查

```bash
ruff check src/ tests/
```

### 提交贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 版本说明

当前版本：**v0.1.4**

这是 live2note 的第一个版本，核心能力包括：
- 直播音频录制与分片
- 本地语音转写（faster-whisper）
- LLM 知识整理与总结
- Markdown / JSON 知识库输出
- getnote 导入
- 任务状态管理与断点续跑
- 手动停止与自动停止

更多版本信息见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

[MIT](LICENSE)
