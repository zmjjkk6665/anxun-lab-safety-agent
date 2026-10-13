"""模型接入层：Agnes 自研模型 / OpenAI 兼容模型 / 离线规则规划器。

默认走 OpenAI 兼容的 chat.completions + tool_calls 协议（Agnes API 同样兼容），
未配置 Key 时自动降级为 rule-based planner，保证无网也能完整演示。
"""

import json
import time
import urllib.error
import urllib.request

# 免费/低配额网关常见：429 限流、5xx 抖动，均按退避重试处理
RETRY_STATUS = (429, 500, 502, 503, 504)


class LLMError(RuntimeError):
    pass


class AgnesClient:
    """OpenAI 兼容协议客户端（Agnes / DeepSeek / 通义等仅换 base_url 与 model）。"""

    def __init__(self, cfg):
        llm = cfg["llm"]
        self.api_key = llm.get("api_key") or ""
        self.base_url = (llm.get("base_url") or "https://api.agnes-ai.cn/v1").rstrip("/")
        self.model = llm.get("model") or "agnes-3.0-flash"
        self.temperature = llm.get("temperature", 0.2)
        self.timeout = llm.get("timeout_sec", 60)
        self.max_retries = int(llm.get("max_retries", 4))
        self.retry_base_sec = float(llm.get("retry_base_sec", 3.0))
        self.min_interval_sec = float(llm.get("min_interval_sec", 1.5))
        self._last_call_at = 0.0

    def available(self):
        return bool(self.api_key)

    def chat(self, messages, tools):
        if not self.api_key:
            raise LLMError("未配置 AGNES_API_KEY")

        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": self.temperature,
        }
        req = urllib.request.Request(
            "%s/chat/completions" % self.base_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer %s" % self.api_key,
            },
            method="POST",
        )
        last_error = None
        for attempt in range(self.max_retries + 1):
            self._pace()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "ignore")
                last_error = "模型服务返回 %s: %s" % (exc.code, body[:200])
                if exc.code in RETRY_STATUS and attempt < self.max_retries:
                    time.sleep(self._backoff(exc, attempt))
                    continue
                raise LLMError(last_error)
            except Exception as exc:
                last_error = "模型服务调用失败: %s" % exc
                if attempt < self.max_retries:
                    time.sleep(self._backoff(None, attempt))
                    continue
                raise LLMError(last_error)
        raise LLMError(last_error or "模型服务调用失败")

    def _pace(self):
        """两次请求之间留最小间隔，降低触发免费额度限流的概率。"""
        gap = time.time() - self._last_call_at
        if gap < self.min_interval_sec:
            time.sleep(self.min_interval_sec - gap)
        self._last_call_at = time.time()

    def _backoff(self, exc, attempt):
        retry_after = 0.0
        if exc is not None:
            try:
                retry_after = float(exc.headers.get("Retry-After") or 0)
            except (ValueError, TypeError, AttributeError):
                retry_after = 0.0
        return max(retry_after, self.retry_base_sec * (2 ** attempt))


def extract_tool_call(response):
    """从模型响应中解析工具调用，兼容 tool_calls 与纯 JSON 两种输出。"""
    try:
        msg = response["choices"][0]["message"]
    except (KeyError, IndexError):
        raise LLMError("模型响应格式异常: %s" % json.dumps(response, ensure_ascii=False)[:300])

    calls = msg.get("tool_calls")
    if calls:
        fn = calls[0]["function"]
        args = fn.get("arguments") or "{}"
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        return {"name": fn.get("name"), "args": args, "thought": msg.get("content") or ""}

    content = msg.get("content") or ""
    parsed = _parse_json_block(content)
    if parsed and "tool" in parsed:
        return {
            "name": parsed["tool"],
            "args": parsed.get("args", {}),
            "thought": parsed.get("thought", ""),
        }
    return {"name": None, "args": {}, "thought": content}


def _parse_json_block(text):
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
