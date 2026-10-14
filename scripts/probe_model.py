"""模型接入真机探针：验证 Base URL、鉴权、工具调用（function calling）能力。

安全约定：
- 只从环境变量 AGNES_API_KEY 读取密钥，**绝不打印、绝不落盘**
- 输出仅包含状态码、模型名、能力判定与耗时

用法：
    set AGNES_API_KEY=...                (Windows cmd)
    $env:AGNES_API_KEY="..."             (PowerShell)
    python scripts/probe_model.py
    python scripts/probe_model.py --base https://apihub.agnes-ai.com/v1 --model agnes-3.0-flash
"""

import argparse
import json
import os
import time
import urllib.error
import urllib.request


def request(url, payload=None, key=None, timeout=30, method=None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer %s" % key
    req = urllib.request.Request(url, data=data, headers=headers, method=method or ("POST" if data else "GET"))
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8")), round(time.time() - t0, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("AGNES_BASE_URL", "https://api.agnes-ai.cn/v1"))
    ap.add_argument("--model", default=os.environ.get("AGNES_MODEL", "agnes-3.0-flash"))
    a = ap.parse_args()

    key = os.environ.get("AGNES_API_KEY", "").strip()
    base = a.base.rstrip("/")
    print("Base URL : %s" % base)
    print("Model    : %s" % a.model)
    print("Key      : %s（长度 %d，不显示内容）" % ("已设置" if key else "未设置", len(key)))
    if not key:
        print("\n未设置 AGNES_API_KEY，无法做鉴权探测。请在终端设置后重跑。")
        return 2

    ok = True

    # 1) 模型清单
    try:
        data, dt = request(base + "/models", key=key)
        ids = [m.get("id") for m in data.get("data", [])]
        print("\n[1] GET /models -> OK（%.2fs，%d 个模型）" % (dt, len(ids)))
    except urllib.error.HTTPError as e:
        print("\n[1] GET /models -> HTTP %s %s" % (e.code, e.read(120).decode("utf-8", "ignore")))
    except Exception as e:
        print("\n[1] GET /models -> 失败 %s: %s" % (type(e).__name__, e))
        ok = False

    # 2) 纯对话
    try:
        data, dt = request(base + "/chat/completions", {
            "model": a.model, "temperature": 0.2,
            "messages": [{"role": "user", "content": "用一句话说明你是谁"}],
        }, key=key)
        content = data["choices"][0]["message"].get("content", "")
        print("[2] 纯对话 -> OK（%.2fs）回复前 60 字: %s" % (dt, content[:60].replace("\n", " ")))
    except urllib.error.HTTPError as e:
        print("[2] 纯对话 -> HTTP %s %s" % (e.code, e.read(200).decode("utf-8", "ignore")))
        ok = False
    except Exception as e:
        print("[2] 纯对话 -> 失败 %s: %s" % (type(e).__name__, e))
        ok = False

    # 3) 工具调用（是否支持 function calling，是本项目的关键能力）
    tools = [{
        "type": "function",
        "function": {
            "name": "get_sensor_readings",
            "description": "读取全部气体探测器读数与报警等级",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }]
    try:
        data, dt = request(base + "/chat/completions", {
            "model": a.model, "temperature": 0.2, "tools": tools, "tool_choice": "auto",
            "messages": [{"role": "user", "content": "实验室疑似气体泄漏，请先读取探测器读数。"}],
        }, key=key)
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if calls:
            fn = calls[0]["function"]
            print("[3] 工具调用 -> 支持（%.2fs）模型选择: %s(%s)" % (dt, fn.get("name"), fn.get("arguments")))
        else:
            print("[3] 工具调用 -> 未返回 tool_calls，回复: %s" % (msg.get("content", "")[:80]))
            print("    提示：该模型可能不支持 function calling，建议换用 agnes-3.0-flash / agnes-2.5-flash")
            ok = False
    except urllib.error.HTTPError as e:
        print("[3] 工具调用 -> HTTP %s %s" % (e.code, e.read(200).decode("utf-8", "ignore")))
        ok = False
    except Exception as e:
        print("[3] 工具调用 -> 失败 %s: %s" % (type(e).__name__, e))
        ok = False

    print("\n结论: %s" % ("模型接入可用，可执行 --mode builtin 真机演练" if ok else "存在问题，请根据上方报错调整 base_url / model"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
