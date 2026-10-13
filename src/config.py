"""全局配置：默认 JSON 配置 + 环境变量覆盖。

优先级：环境变量 > config/default.json
关键环境变量：
  AGNES_API_KEY   组委会下发的 Agnes 模型 Key
  AGNES_BASE_URL  Agnes 模型服务地址（OpenAI 兼容）
  AGNES_MODEL     模型名，默认 agnes-3.0-pro
  LABGUARD_MODE   auto | agh | builtin | mock
  AGH_HOME        Agnes Harness 源码目录（可选，存在则优先走 AGH）
  AGH_SERVER_URL  AGH App Server 地址（可选）
"""

import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(_ROOT, "config", "default.json")


def _load_default() -> dict:
    with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_config(path: str = None) -> dict:
    cfg = _load_default()
    if path:
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        cfg.update(user_cfg)

    env_map = {
        "AGNES_API_KEY": ("llm", "api_key"),
        "AGNES_BASE_URL": ("llm", "base_url"),
        "AGNES_MODEL": ("llm", "model"),
        "AGH_HOME": ("agh", "home"),
        "AGH_SERVER_URL": ("agh", "server_url"),
        "LABGUARD_MODE": ("agent", "mode"),
        "LABGUARD_SPEED": ("lab", "sim_speed"),
    }
    for env_key, (section, field) in env_map.items():
        val = os.environ.get(env_key)
        if val:
            cfg.setdefault(section, {})[field] = val

    cfg["root"] = _ROOT
    return cfg


def resolve_mode(cfg: dict) -> str:
    """判定运行模式：显式指定优先，否则按 AGH 是否可用自动切换。"""
    mode = (cfg.get("agent", {}).get("mode") or "auto").lower()
    if mode != "auto":
        return mode

    agh_home = cfg.get("agh", {}).get("home")
    if agh_home and os.path.isdir(agh_home):
        return "agh"
    if cfg.get("agh", {}).get("server_url"):
        return "agh"
    if cfg.get("llm", {}).get("api_key"):
        return "builtin"
    return "mock"
