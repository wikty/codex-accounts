<!-- markdownlint-disable MD041 -->
<h1 align="center">codex-accounts</h1>

<p align="center">
  <em>OpenAI Codex 桌面客户端的多账号本地管理工具。</em>
</p>

<p align="center">
  <a href="./README.md">English</a> · <a href="./docs/installation.md">安装</a> · <a href="./docs/add-account.md">添加账号</a> · <a href="./docs/faq.md">FAQ</a>
</p>

---

OpenAI Codex 桌面客户端把所有会话、日志、UI 状态都存在 `~/.codex/` 里，
而底层 SQLite **没有"账号"这个字段**。一旦切换到另一个 ChatGPT 账号，
之前所有的会话都会从侧边栏消失。

**codex-accounts** 通过在 `~/.codex/` 中切换关键文件，让多账号干净隔离：

```console
$ codex-accounts use work
✓ switched to: work  (auth mode)

$ codex-accounts list
Accounts (/Users/you/.codex-accounts):

  ▶ work       work@example.com    Plus       5d left      2h ago    ← current
    personal   personal@me.io      Plus       9d left      yesterday
    research   lab@university.edu  Pro        1d left ⚠    3d ago
```

## 功能特性

- **一行切换**：`codex-accounts use <name>` 会自动保存当前账号再激活目标账号。
- **两种隔离模式**：默认所有账号共享会话历史；加 `--no-share-sessions` 后
  会话、日志、Shell 快照完全独立。
- **实时额度**：`quota` 和 `list -a` 调用与 Codex 客户端右上角进度条相同的
  私有接口，显示 5 小时 / 周窗口的真实用量。
- **本地用量统计**：`stats` 直接读取本地 SQLite，离线展示 token 消耗。
- **自动激活窗口**：`refresh` 一次性为所有账号打开当日的 5 小时窗口，
  避免滑动窗口浪费（详见 [docs/auto-refresh.md](./docs/auto-refresh.md)）。
- **零依赖**：纯标准库 Python，单文件 console script。

## 环境要求

| 项 | 支持范围 |
|---|---|
| **操作系统** | macOS 12+（主要支持），Linux（尽力支持，欢迎 PR） |
| **Python** | 3.9+ |
| **Codex 桌面客户端** | 已安装并至少登录过一次 |

> 目前未支持 Windows，欢迎贡献。

## 安装

```bash
# 推荐：使用 pipx 隔离安装
pipx install codex-accounts

# 或使用 pip
pip install --user codex-accounts
```

无包管理器安装方式见 [`docs/installation.md`](./docs/installation.md)。

## 快速上手

```bash
# 1. 把当前已登录的账号保存为快照
codex-accounts save work

# 2. 添加第二个账号
codex-accounts init personal      # 占位目录
codex-accounts use   personal     # 清除 auth.json，让 Codex 提示重新登录
open -a Codex                   # 在浏览器完成 OAuth
codex-accounts save  personal     # 抓取新账号的数据

# 3. 日常使用
codex-accounts list               # 一眼概览
codex-accounts use work           # 切回主账号
codex-accounts quota              # 查看 5h / 每周额度
codex-accounts stats              # 本地 token 用量
```

完整流程参见 [docs/add-account.md](./docs/add-account.md)。

## 命令一览

| 命令 | 说明 |
|---|---|
| `list [-a]` | 列出账号（`-a` 附带实时额度） |
| `current` | 当前激活账号 |
| `info [name]` | 邮箱、套餐、token 有效期、备注 |
| `save <name> [--auth-only]` | 把当前 Codex 状态保存到 `<name>` |
| `use <name> [--no-share-sessions]` | 切换到 `<name>`，自动先保存当前 |
| `init <name>` | 仅创建占位目录，不拷贝任何文件 |
| `note <name> <text>` | 设置账号备注 |
| `rename <old> <new>` | 重命名账号 |
| `delete <name>` | 删除快照目录 |
| `stats [name]` | 读取本地 SQLite 的 token 用量 |
| `quota [name]` | 通过私有 API 查询实时额度（需联网） |
| `refresh` | 批量为每个账号打开 5h 窗口（适合定时任务） |
| `app status [--since HOURS] [--json]` | 快速查看本机 Codex Desktop 基础健康状态 |
| `app doctor [--since HOURS] [--live] [--json]` | 诊断 Codex Desktop 重连、WebSocket、TLS 超时类问题 |
| `app kill [list\|stale]` | 查看 Codex Desktop 后台进程，或在退出后清理残留（仅 macOS 桌面端） |
| `app gc [--dry-run] [--json]` | 把 Codex home 大文件分类为可移除、可重建、可归档、受保护 |
| `app gc clean --category <name> --yes` | 显式确认后删除选中的 `remove` 候选 |
| `status [--since HOURS] [--json]` | `app status` 的快捷入口 |
| `doctor` | 输出运行环境诊断信息 |

## 工作原理

```
~/.codex/                           ~/.codex-accounts/work/
├── auth.json          ←互换→       ├── auth.json
├── state_*.sqlite     ←互换→       ├── state_*.sqlite       (仅 FULL 模式)
├── sessions/          ←互换→       ├── dirs/sessions/       (仅 FULL 模式)
├── config.toml                     └── meta.json            (备注、时间戳)
├── skills/ rules/ memories/        (所有账号共享，永不互换)
└── installation_id
```

- **AUTH 模式**（`use` 默认）：仅互换 `auth.json`。会话历史所有账号共享，
  这是绝大多数用户想要的。此模式不再提示关闭 Codex 或要求继续确认；
  如果已运行的客户端仍使用旧账号，重启客户端后再使用。
- **FULL 模式**（`use --no-share-sessions`）：会话 DB、日志 DB、JSONL 索引、
  `sessions/`/`archived_sessions/`/`shell_snapshots/` 目录、全局 UI 状态
  文件全部互换。当你真的想让每个账号有独立会话栏时使用。
  此模式会替换 SQLite 文件，因此检测到 Codex 运行时仍要求继续确认。

`app gc` 默认只读。它只报告临时残留、可重建缓存、适合压缩归档的历史产物，
以及必须保护的运行状态。`app gc clean` 只会删除当前 `remove` bucket 里的
候选项，并且必须显式指定 `--category` 或 `--path`，再加 `--yes` 确认；
不会删除 rollout 历史、认证/配置文件、SQLite 索引或生成图片。

具体文件列表见
[`src/codex_switch/config.py`](./src/codex_switch/config.py)；
使用 glob 模式（`state_*.sqlite` / `logs_*.sqlite`），Codex 的 schema 升级
不会让脚本漏文件。

## 安全与隐私

- `~/.codex-accounts/` 及其下每个快照目录都会以 `0700` 权限创建。
- 账号名校验：`^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`，杜绝路径穿越。
- `auth.json` 与 Codex 客户端自身保存的内容一致，**是明文 OAuth bundle**。
  请像对待 `~/.codex/` 一样小心处理快照目录：可以备份，**但不要提交到 git
  或同步到任何未加密的位置**。
- `quota` / `list -a` / `refresh` 会发起到 `chatgpt.com/backend-api` 的
  HTTPS 请求，其它命令完全离线。
- 漏洞报告流程见 [`SECURITY.md`](./SECURITY.md)。

## 免责声明

- 本项目**与 OpenAI 没有任何隶属关系**。
- `quota` / `list -a` / `refresh` 依赖私有接口
  （`/backend-api/wham/usage`、`/backend-api/codex/responses`），
  这些接口是通过逆向 Codex 客户端获得的，可能随时变化。
  当 Codex 更新破坏集成时，
  [`docs/internals/codex-app-internals.md`](./docs/internals/codex-app-internals.md)
  记录了重新定位接口的方法。
- `refresh` 会代你向 OpenAI 发起轻量级 API 请求。开启定时任务前请阅读
  [`docs/auto-refresh.md`](./docs/auto-refresh.md) 中的风控与延迟说明。

## 贡献

欢迎 PR、Issue 以及"在 Linux 上 XX 跑不起来"反馈。开发流程见
[`CONTRIBUTING.md`](./CONTRIBUTING.md)，社区准则见
[`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)。

## 许可证

[MIT](./LICENSE) © codex-accounts contributors.
