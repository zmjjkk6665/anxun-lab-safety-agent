"""事故报告落盘：Markdown 正文 + JSON 结构化数据。"""

import json
import os
import time


def save_report(trace, world, directory):
    os.makedirs(directory, exist_ok=True)
    rep = trace.final_report or {}
    stamp = time.strftime("%Y%m%d-%H%M%S")

    md = ["# 实验室安全事故处置报告", ""]
    md.append("- 任务编号：%s" % trace.task_id)
    md.append("- 实验室：%s（介质：%s）" % (world.name, world.chemical))
    md.append("- 生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    md.append("- 处置耗时：%.1f 秒，任务步数：%d" % (trace.to_dict()["elapsed_sec"], len(trace.steps)))
    md.append("")
    md.append("## 一、处置结论")
    md.append(rep.get("summary", ""))
    md.append("")
    md.append("## 二、根因分析")
    md.append(rep.get("root_cause", ""))
    md.append("")
    md.append("## 三、处置动作时序")
    md.append("| 步序 | 阶段 | 工具 | 耗时(ms) | 结果摘要 |")
    md.append("|---|---|---|---|---|")
    for s in trace.steps:
        md.append("| %d | %s | %s | %d | %s |" % (
            s["index"], s["phase"], s["tool"], s["duration_ms"],
            json.dumps(s["result"], ensure_ascii=False)[:80],
        ))
    md.append("")
    md.append("## 四、整改建议")
    for item in rep.get("recommendations", []):
        md.append("- %s" % item)
    md.append("")
    md.append("> 本报告由 Agnes Harness 驱动的应急处置 Agent 自动生成，全过程可复现、可追溯。")

    md_path = os.path.join(directory, "report-%s.md" % stamp)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    json_path = os.path.join(directory, "report-%s.json" % stamp)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"task_id": trace.task_id, "report": rep, "trace": trace.to_dict()}, f, ensure_ascii=False, indent=2)

    return md_path
