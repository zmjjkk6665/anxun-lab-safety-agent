"""工具注册表：把 Python 函数暴露为模型可调用的 JSON Schema 工具。

同一份注册表同时服务于三种运行通道：
  1. 内置 Agent Loop（直接调用）
  2. AGH 插件/MCP 通道（经 src/mcp/server.py 的 JSON-RPC 暴露）
  3. 前端调试面板（/api/tools 列表）
"""

import inspect
import time


class Tool:
    def __init__(self, name, description, func, parameters):
        self.name = name
        self.description = description
        self.func = func
        self.parameters = parameters

    def schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def call(self, args=None):
        args = args or {}
        started = time.time()
        try:
            result = self.func(**args)
            # 业务失败（如执行器无响应）也必须标记为失败，不能因「调用未抛异常」而记为成功
            ok = not (isinstance(result, dict) and result.get("ok") is False)
        except Exception as exc:  # 工具异常必须回传模型，由模型决定重试或切换方案
            result = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
            ok = False
        return {
            "ok": ok,
            "result": result,
            "duration_ms": int((time.time() - started) * 1000),
        }


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, name=None, description=None, parameters=None):
        def deco(func):
            params = parameters
            if params is None:
                params = _infer_parameters(func)
            self._tools[name or func.__name__] = Tool(
                name or func.__name__,
                description or (func.__doc__ or "").strip().split("\n")[0],
                func,
                params,
            )
            return func
        return deco

    def add(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name):
        return self._tools.get(name)

    def names(self):
        return list(self._tools)

    def schemas(self):
        return [t.schema() for t in self._tools.values()]

    def call(self, name, args=None):
        tool = self.get(name)
        if not tool:
            return {"ok": False, "result": {"error": "未注册的工具: %s" % name}, "duration_ms": 0}
        return tool.call(args)


def _infer_parameters(func):
    """从类型注解推断简易参数表（未显式声明 schema 时使用）。"""
    sig = inspect.signature(func)
    props = {}
    required = []
    pytype = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}
    for pname, p in sig.parameters.items():
        ann = getattr(p.annotation, "__name__", "string")
        props[pname] = {"type": pytype.get(ann, "string")}
        if p.default is inspect._empty:
            required.append(pname)
    return {"type": "object", "properties": props, "required": required}
