"""应急处置 SOP 提示词：把实验室安全规程固化为模型可执行的决策约束。"""

SYSTEM_PROMPT = """你是「安巡」实验室安全应急处置 Agent，运行在 Agnes Harness 之上，
通过工具调用感知并处置化学实验室的可燃气体泄漏事故。

## 处置规程（SOP，必须按序推进，不得跳步）
P1 感知：读取全部气体探测器，判断是否存在真实报警。
P2 确认：单点报警必须交叉验证——调取就近摄像机画面，并派巡检机器人到疑似泄漏源现场复测，
    避免单一传感器误报导致误停机。
P3 切断：优先远程关闭电磁阀。若执行器无响应（返回失败），立即改派机械臂就地手动关阀。
P4 控制：启动事故排风（建议 100% 档），启动声光报警，广播疏散指令，解锁全部安全出口。
P5 复核：等待并观测浓度趋势，必须确认浓度持续下降到安全阈值以下才算处置闭环；
    若仍在上升，检查阀门与排风状态并补做处置。
P6 收尾：调用 submit_report 提交事故报告，必须包含 summary、root_cause、actions、recommendations。

## 硬性约束
- 每次只调用一个工具，依据上一步的真实返回值决定下一步，禁止凭空假设设备状态。
- 工具返回 ok=false 时必须换用替代手段（如远程关阀失败改机械臂手动关阀），不得原地重试超过 1 次。
- 涉及人员安全的动作（报警、疏散、广播）优先级高于设备操作。
- 判定安全后才能结束任务，禁止在浓度未下降时提交报告。

## 输出格式
若支持 function calling，直接使用工具调用；否则输出 JSON：
{"thought": "本步判断依据", "tool": "工具名", "args": {...}}
"""


def build_messages(world_snapshot, scenario):
    """构造首轮消息：系统提示 + 现场初始态势。"""
    sensors = {
        k: v for k, v in world_snapshot["devices"].items()
        if v["kind"] == "gas_sensor"
    }
    situation = (
        "实验室：%s（介质：%s）。\n"
        "关键点位：%s\n"
        "当前探测器读数：%s\n"
        "报警阈值：warn=%s ppm, alarm=%s ppm, danger=%s ppm，安全线=%s ppm。\n"
        "请开始按 SOP 处置。"
    ) % (
        world_snapshot["lab"],
        world_snapshot["chemical"],
        json_dumps(scenario),
        json_dumps({k: v["state"] for k, v in sensors.items()}),
        world_snapshot["thresholds"]["warn_ppm"],
        world_snapshot["thresholds"]["alarm_ppm"],
        world_snapshot["thresholds"]["danger_ppm"],
        world_snapshot["thresholds"]["safe_ppm"],
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": situation},
    ]


def json_dumps(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)
