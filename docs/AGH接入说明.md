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
    "base_url": "https://api.agnes.ai/v1",
    "model": "agnes-3.0-pro",
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

## Skills 复用

`skills/chemical-leak-response/SKILL.md` 已按 AGH Skills 机制组织，
把本次验证过的处置规程沉淀为可跨实验室复用的技能，也可直接作为模型 system prompt 使用
（内容与 `src/agent/prompts.py` 的 SOP 同源）。

## 模型接入

AGH 与内置通道共用同一份模型配置（OpenAI 兼容协议）：

| 环境变量 | 说明 | 默认值 |
|---|---|---|
| `AGNES_API_KEY` | 组委会下发的模型 Key | 空 |
| `AGNES_BASE_URL` | 模型服务地址 | `https://api.agnes.ai/v1` |
| `AGNES_MODEL` | 模型名 | `agnes-3.0-pro` |
| `LABGUARD_MODE` | 运行模式 | `auto` |
| `LABGUARD_SPEED` | 仿真倍速（演示/测试用） | `2.0` |

若组委会提供的 Key 采用私有协议，仅需改写 `src/llm/client.py::AgnesClient.chat()`。
