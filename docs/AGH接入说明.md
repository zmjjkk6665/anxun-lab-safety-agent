# Agnes Harness 接入说明

本项目的核心任务组织、执行与工具调用均由 Harness 承担。接入 AGH 分三条通道，可逐级落地。

## 通道一：MCP 接入（推荐，解耦最彻底）

AGH 支持通过 MCP 连接已有服务。本项目已实现完整 MCP 服务器：

```bash
python run.py mcp --selftest    # 自检协议：initialize / tools/list / tools/call
```

配置（`python run.py agh` 会自动生成 `deploy/agh/agh.labguard.json`）：

```json
{
  "model": {
    "provider": "agnes",
    "base_url": "https://api.agnes-ai.cn/v1",
    "model": "agnes-3.0-flash",
    "api_key_env": "AGNES_API_KEY"
  },
  "mcpServers": [
    {
      "name": "labguard-devices",
      "command": "python",
      "args": ["<项目根目录>/run.py", "mcp"],
      "transport": "stdio"
    }
  ],
  "skills": ["<项目根目录>/skills/chemical-leak-response"]
}
```

AGH 拉起该 MCP 服务器后，即可在其 Agent Loop 中调用全部 14 个设备工具，
由 AGH 负责规划、工具调用编排与结果回灌，本项目只负责设备侧的真实执行。

## 通道二：AGH CLI / App Server 任务下发

```bash
set AGH_HOME=D:\path\to\agnes-harness      # 或把 agh 加入 PATH
python run.py agh                           # 探测可用性并生成配置
```

探测逻辑见 `src/agh/adapter.py::AGHBridge.detect()`，依次检查：
`AGH_HOME` 目录是否存在 → `agh` 是否在 PATH → 是否配置了 `AGH_SERVER_URL`。
命中任一即切换为 `agh` 模式，通过 `AGHBridge.run_task()` 下发任务指令。

## 通道三：内置 Agent Loop（与 AGH 同构，兜底）

在无 AGH 源码的环境（如离线评审、CI）中，`src/agent/loop.py` 提供与 AGH 一致的
「模型决策 → 工具执行 → 反馈回灌」循环，复用同一份工具注册表与 Trace 模型。
拿到 AGH 后只需切换模式，业务代码零改动。

### 真机接入实测记录（2026-10-14）

环境：Windows 11 / Node v24.19.0 / pnpm 10.34.5，AGH 源码 `AgnesAI-Labs/agnes-harness`（pre-alpha）。

```bash
# 1) 拉取并构建（--output-dir 必须是绝对路径）
git clone --depth 1 https://github.com/AgnesAI-Labs/agnes-harness.git
cd agnes-harness && pnpm install --frozen-lockfile
pnpm --filter @agnes/cli build:local --output-dir "<绝对路径>\packages\cli\dist\local-dev-lab"

# 2) 启动 Web 与守护进程（会自动拉起 daemon）
node packages/cli/dist/local-dev-lab/agnes.mjs serve --port 4180 --profile local-dev \
     --cwd "<AGH 源码目录>" --data-dir "<AGH_HOME>\data"

# 3) 配置模型账号（Web：Settings → Models & accounts → Add account）
#    Provider=Agnes AI，Base URL=https://api.agnes-ai.cn/v1，测试连接返回
#    agnes-3.0-flash / agnes-2.5-pro / agnes-2.5-pro-alpha / agnes-2.5-pro-beta / agnes-2.5-flash
```

自动化注意点（踩过的坑，均已在本仓库脚本中规避）：

| 现象 | 原因与处理 |
|---|---|
| `build:local` 报 `Expected --output-dir with an absolute directory` | 参数必须是绝对路径 |
| `local daemon did not become ready` | 资源类命令依赖守护进程，先 `serve` 拉起 |
| `operation cancelled; rerun and confirm…` | `mcp add/trust/enable` 强制要求真实 TTY（`stdin.isTTY && stdout.isTTY`），管道输入无效；需在真实终端确认（本仓库 `scripts/_pty_run.py` 提供 PTY 自动确认） |
| `stdio executable is not allowed by profile policy` | pre-alpha 版本对 MCP stdio 的可执行文件有**部署策略白名单**，实测 `python` 与 `node` 均被拒。已提供 `scripts/mcp_stdio_bridge.js` 作为备用桥接，待官方开放白名单后一行登记即可挂载 |
| `MCP_RECONCILE_FAILED` | 更新定义会使 trust 失效，需按新 revision 重新 `trust` 再 `enable` |

一键复现脚本（含账号配置、会话下发、执行记录导出）：

```bash
set AGNES_API_KEY=...
node scripts/agh_setup.js --step account    # 配置模型账号并测试连接
node scripts/agh_setup.js --step session    # 下发应急处置任务并导出 AGH 执行记录
```

产物落在 `outputs/agh/`（会话文本、截图、AGH 执行记录 JSON）。

## Skills 复用

`skills/chemical-leak-response/SKILL.md` 已按 AGH Skills 机制组织，
把本次验证过的处置规程沉淀为可跨实验室复用的技能，也可直接作为模型 system prompt 使用
（内容与 `src/agent/prompts.py` 的 SOP 同源）。

## 模型接入

AGH 与内置通道共用同一份模型配置（OpenAI 兼容协议）：

| 环境变量 | 说明 | 默认值 |
|---|---|---|
| `AGNES_API_KEY` | 组委会下发的模型 Key | 空 |
| `AGNES_BASE_URL` | 模型服务地址 | `https://api.agnes-ai.cn/v1` |
| `AGNES_MODEL` | 模型名 | `agnes-3.0-flash` |
| `LABGUARD_MODE` | 运行模式 | `auto` |
| `LABGUARD_SPEED` | 仿真倍速（演示/测试用） | `2.0` |

### 官方端点与模型清单（实测）

- **赛事 Key 对应端点（2026-10 实测通过）**：`https://api.agnes-ai.cn/v1` —— 对话与 function calling 均 OK
- 公开 OpenAI 兼容端点：`https://apihub.agnes-ai.com/v1`（`/models` 可匿名读，`/chat/completions` 对赛事 Key 返回 401）
- 官方模型清单实测（2026-10）：`agnes-3.0-flash`、`agnes-2.5-flash`、`agnes-2.5-pro-alpha`、`agnes-2.5-pro-beta`
- ⚠️ `api.agnes.ai`、`apihub.agnes.ai` 在公共 DNS 上**不存在**，不可用作 base_url
- ⚠️ 赛事 Key **每日更新**：隔日 Key 会返回 `401 Invalid token`，需换用当日邮件中的 Key

### 接入自检与排障

```bash
set AGNES_API_KEY=...
python scripts/probe_model.py          # 依次验证 /models、纯对话、function calling
```

脚本只从环境变量读取密钥，**不回显、不落盘**；输出仅含状态码与结论。常见问题：

| 现象 | 原因与处理 |
|---|---|
| `401 Invalid token` | Key 与当前 base_url 不匹配（赛事 Key 可能走专用网关）。向赛事技术客服索取正确的**接口地址**，或换用自有第三方模型 |
| `404 Resource not found` | base_url 写错（如 `api.agnes-ai.com`），应为 `apihub.agnes-ai.com/v1` |
| 模型未返回 `tool_calls` | 该模型不支持 function calling，改用 `agnes-3.0-flash` |
| 无任何 Key | 自动降级为内置规则规划器，处置闭环照常完成（CLI 会打印「降级提示」） |

若组委会提供的 Key 采用私有协议，仅需改写 `src/llm/client.py::AgnesClient.chat()`。
