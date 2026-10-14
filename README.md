# 安巡 · 实验室安全应急处置 Agent

> 基于 **Agnes Harness（AGH）** 的化学实验室可燃气体泄漏应急处置系统
> 2026 江苏省「AI + 科学与工程」创新实践黑客松参赛作品

- GitHub：https://github.com/zmjjkk6665/anxun-lab-safety-agent
- 参赛信息：本科生组 / 参赛编号 U126 / 队伍「大肥鱼脚香香」/ 队长 李家杰

Agent 在数字孪生实验室中完成 **感知 → 确认 → 切断 → 控制 → 复核 → 报告** 的完整闭环：
气体探测器报警后，交叉验证摄像机画面、调度巡检机器人现场复测、远程关阀失败时改派机械臂手动关阀、
启动排风与疏散、持续观测浓度直至达标，最后自动生成事故报告。

**全部设备均为 MHS 模拟设备，无需任何实体硬件即可完整演示。**

---

## 一、快速开始（3 分钟）

```bash
# 1. 启动可视化大屏（零第三方依赖，Python 标准库即可运行）
python run.py web
# 浏览器打开 http://127.0.0.1:8787/ ，点击「启动应急处置」

# 2. 命令行完整演练（打印每一步 Trace 并落盘）
python run.py cli --mode mock

# 3. 冒烟自测
python run.py selftest

# 4. 检测 AGH 可用性并生成 AGH 接入配置
python run.py agh
```

要求：**Python 3.8+**，无第三方依赖（`requirements.txt` 仅标注可选依赖）。
Windows 控制台如中文乱码，先执行 `chcp 65001` 或设置 `$env:PYTHONIOENCODING="utf-8"`。

## 二、运行模式

| 模式 | 说明 | 依赖 |
|---|---|---|
| `mock` | 内置规则规划器，完整跑通处置流程 | 无 |
| `builtin` | 内置 Agent Loop + 真实大模型决策 | `AGNES_API_KEY` |
| `agh` | 交由 Agnes Harness 组织任务与工具调用（经 MCP） | AGH 源码 / `agh` CLI |
| `auto` | 自动判定（默认）：有 AGH 走 AGH，有 Key 走模型，否则 mock | — |

接入组委会下发的模型 Key：

```bash
set AGNES_API_KEY=你的Key            # Windows PowerShell: $env:AGNES_API_KEY="..."
set AGNES_BASE_URL=https://apihub.agnes-ai.com/v1
set AGNES_MODEL=agnes-3.0-flash
python run.py cli --mode builtin
```

> 若 Key 的接入地址/协议与 OpenAI 兼容格式不同，只需修改 `src/llm/client.py` 中的
> `AgnesClient.chat()`，工具层与业务层无需改动。

接入自检与排障（脚本只读取环境变量中的 Key，不回显、不落盘）：

```bash
python scripts/probe_model.py     # 依次验证 /models、纯对话、function calling
```

- 赛事下发端点：`https://api.agnes-ai.cn/v1`；实测可用模型：`agnes-3.0-flash`、`agnes-2.5-flash`、
  `agnes-2.5-pro-alpha`、`agnes-2.5-pro-beta`
- 免费额度有速率限制，客户端已内置指数退避重试与请求最小间隔；仍可能触发 `429`，此时自动降级不影响闭环
- 常见问题与处置见 `docs/AGH接入说明.md`「接入自检与排障」一节
- **模型不可用不会中断演示**：`builtin` 模式遇到鉴权失败/网络不可达会自动降级为内置规则规划器，
  CLI 打印「降级提示」，处置闭环照常完成

## 三、项目结构

```
├── run.py                     统一入口（web / cli / mcp / agh / selftest）
├── config/default.json        实验室、阈值、模型、AGH 配置
├── src/
│   ├── world.py               实验室数字孪生：气体扩散模型 + 12 台设备
│   ├── tools/                 工具注册表与 14 个应急处置工具（JSON Schema）
│   ├── agent/                 Agent Loop、SOP 提示词、规则规划器、报警触发
│   ├── agh/adapter.py         Agnes Harness 适配层（探测 / 配置生成 / 任务下发）
│   ├── mcp/server.py          MCP 服务器（stdio + JSON-RPC，供 AGH 接入）
│   ├── server/app.py          可视化服务（stdlib HTTP，零依赖）
│   ├── web/                   前端大屏（原生 HTML/CSS/JS）
│   ├── llm/client.py          Agnes / OpenAI 兼容模型接入
│   ├── trace.py               执行轨迹（对齐 AGH Trace 视图）
│   └── report.py              事故报告生成（Markdown + JSON）
├── skills/chemical-leak-response/   AGH Skill：可复用的处置规程
├── deploy/agh/                AGH 接入配置（由 python run.py agh 生成）
├── tests/test_smoke.py        冒烟测试（CLI / MCP / HTTP 三通道）
├── outputs/                   运行产物：traces/ 轨迹，reports/ 报告
└── docs/                      作品详情、AGH 接入说明、提交检查清单
```

## 四、核心设计

1. **工具即能力**：所有设备操作都封装为带 JSON Schema 的工具（`src/tools/lab_tools.py`），
   同一份注册表同时服务于内置 Agent Loop、MCP 通道和前端，模型只通过工具感知与操控现场。
2. **失败可见、可恢复**：远程关阀失败不会被静默吞掉，工具返回 `ok=false` 与原因，
   由模型（或规则规划器）切换到「机械臂就地手动关阀」的替代路径——这正是剧本中的关键转折。
3. **闭环才结束**：SOP 强制要求浓度降至安全阈值以下才可提交报告，避免"动作做完即结束"的伪闭环。
4. **全过程可追溯**：每一步的思考、工具、入参、返回、耗时都进入 Trace，
   前端时间轴与 Markdown 报告同源，可直接用于复盘与审计。

## 五、验证记录

- `python run.py cli --mode mock`：12 步执行完成，状态 `completed`，轨迹与报告落盘 `outputs/`
- **真机联调（Agnes 模型驱动）**：端点 `https://api.agnes-ai.cn/v1`，模型 `agnes-3.0-flash`，
  14 步执行完成、状态 `completed`、耗时 137s、**全程无降级**；模型自主选择了与内置脚本不同的处置顺序
  （摄像头检出明火与 2 名在场人员后，先启动报警/广播/解锁出口疏散，再执行关阀），
  并在远程关阀失败后自行改派机械臂；最终三路探测器回落至 2.5 / 10.0 / 0.0 ppm，机器人现场复测 0 ppm，
  事故报告由模型自主撰写（含根因分析与 6 条整改建议）。
  证据：`outputs/traces/task-20261013-231655.json`、`outputs/reports/report-20261013-231912.md`
- **演示视频（自动生成）**：`media/demo-anxun-lab-safety.mp4（在线：https://github.com/zmjjkk6665/anxun-lab-safety-agent/blob/main/media/demo-anxun-lab-safety.mp4）`
  （2 分 09 秒，1600×900，H.264，1.6 MB）。由 `scripts/record_demo.js` 驱动系统 Edge 实录，
  全程 Agnes 模型决策、**无降级**，画面叠加中文字幕条与片头：

```bash
npm i playwright-core @ffmpeg-installer/ffmpeg     # 仅需一次
python run.py web                                  # 先起大屏
node scripts/record_demo.js --mode builtin         # 真机录制；--mode mock 为离线快版
```

- `python run.py mcp --selftest`：MCP 协议 `initialize` / `tools/list` / `tools/call` 自检通过
- 端到端断言：阀门关闭、排风 100%、人员疏散、源点浓度降至安全阈值以下、事故报告生成 —— 全部 PASS

### 真机接入的三个工程要点（均为实测踩坑后修复）

| 问题 | 现象 | 修复 |
|---|---|---|
| tool 消息缺 `tool_call_id` | 网关 `400 missing field tool_call_id` | 回放 `tool_calls` 时回填 `tool_call_id`（`src/agent/loop.py`） |
| 免费额度限流 | 连续调用触发 `429` | 指数退避重试 + 请求最小间隔（`src/llm/client.py`） |
| 浓度模型泄漏期零衰减 | 演练越长浓度越离谱（>7000 ppm） | 改为「源项 − 一阶通风稀释 − 自然沉降」，峰值有界、关阀后指数衰减（`src/world.py`） |

即便模型不可用（未配 Key / 鉴权失败 / 限流持续），`builtin` 模式也会自动降级到内置规则规划器，
处置闭环照常完成并在 CLI 打印「降级提示」，演示不会中断。

## 六、安全提示：模型 Key 的处理

赛事要求：**Key 不得出现在公开代码库、截图或演示材料中**。本项目在流程上做了强制约束：

- Key **只通过环境变量** `AGNES_API_KEY` 注入，代码中不出现任何明文 Key
  （`config/default.json` 的 `api_key` 默认为空字符串）。
- 打包脚本内置**密钥泄露扫描**（`scripts/package.py`）：打包前扫描每个待入包文件，
  命中 `sk-` 令牌、硬编码 `AGNES_API_KEY` 等特征即**中止打包、不生成 ZIP**，
  且只打印「文件:行号 + 规则名」，不回显密钥内容：

```bash
python scripts/package.py --scan-only   # 只扫描不打包，退出码 0 表示通过
```

- 推 GitHub 前请再跑一次扫描；`.gitignore` 已排除 `.env`、`outputs/`、`dist/`。
- 录制演示视频时，用环境变量设置 Key，**不要在终端回显或写入屏幕可见文件**。

## 七、评审复现说明（无 Key 也能完整演示）

组委会 Key 可能有有效期或每日额度限制。作品提供零依赖复现路径：

```bash
python run.py cli --mode mock     # 13 步处置闭环 + 轨迹 + 事故报告
python run.py web                 # 可视化大屏，点击「启动应急处置」
```

`mock` 模式的内置规则规划器严格实现与 SOP 提示词一致的决策链（含"远程关阀失败 → 机械臂手动关阀"），
处置逻辑与接入模型时一致，仅决策主体不同。

## 八、已知限制

- AGH 真机联调需在可访问 GitHub 的环境拉取 `AgnesAI-Labs/agnes-harness` 源码后执行
  `python run.py agh` 并按 `docs/AGH接入说明.md` 配置；当前环境已完成适配层与 MCP 桥接代码，
  但未经 AGH 实机运行验证（工具层与 AGH 解耦，替换后无需改动业务代码）。
- 气体扩散为工程简化模型（指数衰减 + 通风衰减），用于演示处置逻辑，不作定量安全评估依据。
- 离线 `mock` 模式使用规则规划器，用于基线对照与回归；真实决策能力需接入模型后体现。
