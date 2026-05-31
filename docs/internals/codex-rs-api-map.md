# Codex.app internal architecture & API map

> **Status:** reference notes, in Chinese, kept verbatim from the
> original reverse-engineering session. Companion to
> [`codex-app-internals.md`](./codex-app-internals.md), which
> documents the methodology in English and is the doc most readers
> want to start from.
>
> **Disclaimer:** None of the endpoints / module names below are part
> of any public OpenAI API. They were extracted by inspecting
> `/Applications/Codex.app/Contents/Resources/app.asar` (Electron) and
> `/Applications/Codex.app/Contents/Resources/codex` (Rust binary) on
> a specific Codex desktop release, and may have changed since.

---

通过逆向 `/Applications/Codex.app/Contents/Resources/app.asar`（Electron UI 层）
和 `/Applications/Codex.app/Contents/Resources/codex`（Rust 核心层）整理。

---

## 整体架构

```
┌──────────────────────────────────────────────────────────┐
│  Electron 进程（app.asar / JS）                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  webview（React UI）  ──IPC──→  main process        │ │
│  │  codex-api.js                                       │ │
│  │  /wham/* 任务管理接口                                │ │
│  └───────────────────────┬─────────────────────────────┘ │
└──────────────────────────┼───────────────────────────────┘
                           │ WebSocket (ws://127.0.0.1)
                           ↓
┌──────────────────────────────────────────────────────────┐
│  codex 二进制（Rust，183MB）                              │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  app-server（WebSocket RPC 层）                      │ │
│  │    ├─ exec-server（WebSocket，Shell 命令执行）        │ │
│  │    └─ responses-api-proxy（HTTP，转发 LLM 请求）      │ │
│  │         ↓ SSE / WebSocket                            │ │
│  │  ┌──────────────────────────────────────────────┐   │ │
│  │  │  LLM Provider（可配置）                       │   │ │
│  │  │  · OpenAI         api.openai.com/v1           │   │ │
│  │  │  · ChatGPT-auth   chatgpt.com/backend-api/codex│  │ │
│  │  │  · Bedrock        bedrock-mantle.*.api.aws/v1 │   │ │
│  │  │  · Ollama         http://127.0.0.1 (本地)     │   │ │
│  │  │  · LM Studio      ~/.lmstudio/bin/lms         │   │ │
│  │  └──────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

**其他随附二进制：**
- `codex_chronicle`（4.3MB）— 日志 / 可观测性收集器
- `node`（113MB）— Node.js 运行时，供技能脚本使用
- `rg` — ripgrep，供文件搜索工具调用

**Rust 源码树**（从 binary symbols 还原）：`codex-rs/` 下的主要模块：
- `codex-api/` — 所有 LLM 端点封装
- `app-server/` — WebSocket RPC 服务器
- `core/` — 会话状态机、compact、MCP
- `model-provider/` — 多提供商抽象
- `analytics/` — 遥测
- `ollama/`、`lmstudio/`、`feedback/` — 本地模型 & 反馈

---

## LLM 调用接口

### 主端点：OpenAI Responses API

```
POST https://api.openai.com/v1/responses
Authorization: Bearer <access_token>
Content-Type: application/json

（SSE 流式返回，也有 WebSocket 变体）
```

> Codex 使用的是 **Responses API**（新版），**不是** `chat/completions`。
> Rust 实现：`codex-api/src/endpoint/responses.rs`（SSE）、`responses_websocket.rs`（WebSocket）

### ChatGPT-auth 用户的 base URL

```
https://chatgpt.com/backend-api/codex
```

当 `auth.json` 的 `auth_mode = "chatgpt"` 时（即普通 Plus/Pro 用户），
请求会发往 `chatgpt.com/backend-api/codex/responses`（加了 `/codex` 前缀）。

### 支持的模型（slug）

| slug | 展示名 |
|---|---|
| `gpt-5.2` | GPT-5.2 |
| `gpt-5.3-codex` | GPT-5.3 Codex（默认编码模型） |
| `gpt-5.4` | GPT-5.4 |
| `gpt-5.4-mini` | GPT-5.4 mini |
| `gpt-5.5` | GPT-5.5（配置默认替换目标） |

### 必填字段（实测）

直接打 `chatgpt.com/backend-api/codex/responses` 时，以下字段**缺一不可**，否则立即 400：

| 字段 | 必填值 | 错误信息（缺失时） |
|---|---|---|
| `instructions` | 任意字符串（系统提示） | `"Instructions are required"` |
| `store` | `false` | `"Store must be set to false"` |
| `stream` | `true` | `"Stream must be set to true"` |

### SSE 流式响应注意事项

此 backend **只支持 SSE 流式**，且有一个关键陷阱：

> **`response.completed` 事件里的 `output: []` 永远是空数组。**
> 实际输出内容通过 `response.output_item.done` 事件逐条推送，需要客户端自己从流里拼装。

解析流程：

```python
output_items = []
for sse_line in stream:
    event = parse_sse(sse_line)
    if event["type"] == "response.output_item.done":
        output_items.append(event["item"])   # 文本 / 图片结果都在这里
    elif event["type"] == "response.completed":
        final_meta = event["response"]       # 元信息（用量、id等），output 字段为空
# 最终：output_items 就是完整输出
```

---

### 多模态输入（图片理解 / Vision）

Responses API 原生支持多模态，**不需要任何 `tools`**，直接在 `input` 内容里混入 `input_image` 即可。Codex.app 本身的"拖图进对话框"功能走的就是这条路径。

```bash
# ChatGPT-auth 用户（Plus/Pro，用 ~/.codex/auth.json 里的 access_token）
POST https://chatgpt.com/backend-api/codex/responses
Authorization: Bearer <access_token>
chatgpt-account-id: <account_id>
```

```json
{
  "model": "gpt-5.4",
  "input": [{
    "role": "user",
    "content": [
      {"type": "input_text",  "text": "这张图里有什么？"},
      {"type": "input_image", "image_url": "data:image/jpeg;base64,<...>", "detail": "high"}
    ]
  }],
  "stream": false
}
```

| 字段 | 说明 |
|---|---|
| `image_url` | `data:image/<mime>;base64,...` 或 https URL。无 `/v1/files`，**不能用 file_id** |
| `detail` | `auto`（默认）/ `low` / `high` |

**三种能力速查（同一端点）：**

| 任务 | 请求方式 |
|---|---|
| 纯文本对话 | `input_text` only，无 tools |
| 图片理解（vision） | `input_text` + `input_image`，无 tools |
| 图片生成 | `input_text`，`tools:[{type:"image_generation",...}]` |
| 图片局部重绘 | `input_text` + `input_image`（参考图），`tools:[{type:"image_generation",action:"edit"}]` |

---

### Realtime WebSocket（语音 / 音频输入）

```
WSS wss://api.openai.com/v1/realtime
```

实现了 protocol_v1 和 protocol_v2 两个版本。
有独立的 sideband WebSocket 用于传输实时文件预览等附加数据。

---

## 会话压缩（Compact）

压缩**不是**一个独立的外部 API 端点。本质是用 `compact_prompt` 通过 `/v1/responses` 向 LLM 发一次特殊请求，LLM 返回会话摘要后替换历史。

### 触发方式

1. **自动触发**：`auto_compact_token_limit`（`config.toml` 可配置，默认 null = 由客户端自动判断）
2. **手动触发**：用户或技能显式调用

### Hooks（可被技能拦截）

- `PreCompact` — 压缩前回调，可修改输入或阻止压缩
- `PostCompact` — 压缩后回调，可处理新摘要

### 版本

| 文件 | 说明 |
|---|---|
| `core/src/compact_remote.rs` | v1：发 LLM 请求 + 直接替换 |
| `core/src/compact_remote_v2.rs` | v2：期望 LLM 返回 `context_compaction` 类型输出项 |
| `core/src/tasks/compact.rs` | 云任务版压缩 |

压缩完成后发出 IPC 通知：`{ "method": "thread/compacted", "params": ... }`

---

## 文件上传

```
POST /v1/files          （OpenAI auth）
POST /codex/files       （ChatGPT auth，base 前缀后）
GET  /files/            （列出已上传文件）
GET  /uploaded          （上传状态查询）
```

---

## Wham 任务管理 API（全表）

base URL：`https://chatgpt.com/backend-api`（或 `http://localhost:8000/api`，开发模式）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/wham/usage` | 实时额度（5h/周）✅ 已实现 |
| GET | `/wham/accounts/check` | 账号有效性验证 |
| GET | `/wham/environments` | 云运行环境列表 |
| GET | `/wham/environments/by-repo/{provider}/{owner}/{name}` | 指定仓库的环境 |
| GET | `/wham/github/branches/{repo_id}/search` | 分支搜索 |
| POST | `/wham/tasks` | 创建远程 Agent 任务 |
| GET | `/wham/tasks/list` | 列出任务 |
| GET | `/wham/tasks/{task_id}` | 任务详情 |
| GET | `/wham/tasks/{task_id}/turns` | 任务对话轮次 |
| GET | `/wham/tasks/{task_id}/turns/{turn_id}` | 单轮详情 |
| GET | `/wham/tasks/{task_id}/turns/{turn_id}/logs` | 单轮执行日志 |
| POST | `/wham/tasks/{task_id}/turns/{turn_id}/pr` | 从任务创建 PR |
| POST | `/wham/tasks/{task_id}/mark_read` | 标记任务为已读 |
| POST | `/wham/worktree_snapshots/upload_url` | 获取代码快照上传 URL |
| POST | `/wham/worktree_snapshots/finish_upload` | 完成代码快照上传 |
| POST | `/wham/referrals/invite` | 发送推荐邀请 |
| GET | `/wham/agent-identities/jwks` | Agent JWT 签名公钥 |
| GET | `/wham/config/requirements` | 配置要求检查 |

---

## 其他后端接口

### 遥测 & 安全

| 方法 | URL | 说明 |
|---|---|---|
| POST | `https://chatgpt.com/backend-api/codex/analytics-events/events` | 客户端遥测事件 |
| POST | `https://chatgpt.com/backend-api/codex/safety/arc` | 命令安全检查（shell 命令执行前） |
| POST | `https://chatgpt.com/backend-api/codex/device` | 设备注册 |
| GET/POST | `https://chatgpt.com/backend-api/log` | 客户端日志上报 |
| POST | `https://ab.chatgpt.com/otlp/v1/metrics` | OpenTelemetry 指标 |

### 插件市场

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/plugins/featured` | 精选插件 |
| GET | `/plugins/list` | 全部插件 |
| GET | `/ps/plugins/installed` | 已安装插件 |
| GET | `/ps/plugins/list` | 插件列表（带分页） |
| GET | `/ps/plugins/workspace/shared` | 工作区共享插件 |
| POST | `/public/plugins/workspace/upload-url` | 上传插件（获取 URL） |
| POST | `/public/plugins/workspace` | 发布插件 |
| GET | `/public/plugins/workspace/{id}` | 插件详情 |

### OAuth / 设备认证

```
POST https://auth.openai.com/oauth/token      # 获取 token
POST https://auth.openai.com/oauth/revoke     # 撤销 token
GET  https://auth.openai.com/api/accounts     # 账号列表

# 设备授权流
POST /deviceauth/callback
GET  /deviceauth/token
GET  /deviceauth/usercode
```

---

## Amazon Bedrock 集成

```
base URL: https://bedrock-mantle.{region}.api.aws/openai/v1
接口格式: 与 OpenAI Responses API 完全兼容（同一套 SDK）
Auth: AWS SigV4（IAM 凭证）
```

AWS 相关：有完整的 `aws-auth`、`aws-config` Rust crate（`aws-config-1.8.12`），支持 IAM Role、SSO、环境变量等标准 AWS 认证链。

---

## 本地模型提供商

### Ollama

```
base URL: http://127.0.0.1:11434（默认）
接口路径: /api/generate 或 /api/chat（Ollama 标准格式）
管理命令: GET /api/tags（列出可用模型）, GET /api/version
```

Codex 会验证 Ollama 版本是否满足最低要求（太旧会报错）。

### LM Studio

```
可执行文件: ~/.lmstudio/bin/lms
协议: 与 OpenAI 兼容（OpenAI-format API）
```

---

## 图像生成

**Codex backend 完全支持图像生成**，通过 `image_generation` hosted tool 挂在 `/responses` 请求里，由后端自动调用 `gpt-image-2` 生图，客户端收到 base64 结果。

> 详细参数参考与实验记录见：`ip-maker-pipeline/docs/others/gpt-image-api.md`

### 端点

```
POST https://chatgpt.com/backend-api/codex/responses
Authorization: Bearer <access_token>
chatgpt-account-id: <account_id>
```

### 请求格式（Responses API + image_generation tool）

```json
{
  "model": "gpt-5.4",
  "input": [
    {"role": "user", "content": [{"type": "input_text", "text": "画一只橘色小猫"}]}
  ],
  "tools": [
    {
      "type":             "image_generation",
      "quality":          "high",
      "size":             "1024x1024",
      "output_format":    "png",
      "output_compression": 100,
      "background":       "opaque",
      "moderation":       "auto",
      "action":           "generate"
    }
  ],
  "stream": false
}
```

### 关键参数说明

| 参数 | 有效值 | 说明 |
|---|---|---|
| `quality` | `low/medium/high/auto` | 实际档位以响应的 `image_generation_call.quality` 为准，模型可能擅自调整 |
| `size` | 任意字符串（如 `2160x3840`） | SDK 枚举只是子集，后端实测支持最大 3840px 长边，16 倍数 |
| `output_format` | `png/webp/jpeg` | PNG 无损 |
| `action` | `generate/edit/auto` | `edit` 时配合 `input_image_mask` 做局部重绘 |
| `input_image_mask` | `{"image_url": "data:image/png;base64,..."}` | 仅认内联 data URI，不支持 file_id |
| ❌ `n` | — | **传了直接 400**，虽然响应回显里有 `n:1` |
| ❌ `input_fidelity` | — | gpt-image-2 不支持 |
| ❌ `background: "transparent"` | — | gpt-image-2 不支持 |

### 参考图传递

```json
{
  "type": "input_image",
  "image_url": "data:image/jpeg;base64,<base64>"
}
```

只能内联 data URI，无法用 `file_id`（Codex backend 没有 `/v1/files` 端点）。

### 响应体（成功）

```json
{
  "status": "completed",
  "output": [
    {
      "type": "image_generation_call",
      "quality": "high",
      "size": "1024x1024",
      "revised_prompt": "...",
      "result": "<base64 PNG>"
    }
  ],
  "tools": [{"type": "image_generation", "model": "gpt-image-2"}]
}
```

### 与公开 API 的差异

| 维度 | Codex Backend | api.openai.com/v1 |
|---|---|---|
| 认证 | ChatGPT OAuth token（订阅额度） | OpenAI API key（现金计费） |
| 文件上传 | ❌ 无 `/v1/files`，只能 data URI | ✅ 有，可用 file_id |
| 图像模型 | 默认 gpt-image-2，不建议显式 pin | 同 |
| schema | 高度重合 | — |

---

## 没有找到的功能

| 功能 | 结论 |
|---|---|
| ~~文生图接口~~ | ✅ 存在，见上方「图像生成」章节。Codex 客户端 UI 未暴露，但 backend 完全支持 |
| 独立的压缩接口 | ❌ 压缩 = 特殊 LLM 请求（`/v1/responses`），非独立端点。 |
| 公开账单/用量 API | ❌ 仅有 `/wham/usage`（rate limit），无详细账单。 |

---

## 如何追踪新版本的变化

### 快速检查 LLM 端点是否变化

```bash
# 重新提取 asar（Electron UI 层）
npx asar extract /Applications/Codex.app/Contents/Resources/app.asar /tmp/codex-asar

# 搜索 wham/usage
grep -rl "wham" /tmp/codex-asar/webview/assets/

# 搜索 LLM 调用函数
grep -o "safeGet('[^']*')" /tmp/codex-asar/webview/assets/codex-api-*.js
```

### 检查 Rust 二进制变化

```bash
CODEX_BIN=/Applications/Codex.app/Contents/Resources/codex

# 所有端点路径
strings "$CODEX_BIN" | grep -E '^/(wham|v1|responses|files|plugins)' | sort -u

# 所有 HTTPS URL
strings "$CODEX_BIN" | grep -oE 'https://[a-zA-Z0-9._/-]+' | sort -u

# 源码模块列表（Rust panic message 中有路径）
strings "$CODEX_BIN" | grep -oE 'codex-[a-z]+/src/[a-z_/]+\.rs' | sort -u
```

### 验证端点可用性

```bash
TOKEN=$(python3 -c "import json; print(json.load(open('$HOME/.codex/auth.json'))['tokens']['access_token'])")
curl -s -H "Authorization: Bearer $TOKEN" \
  https://chatgpt.com/backend-api/wham/usage | python3 -m json.tool
```
