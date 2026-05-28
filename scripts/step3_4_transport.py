#!/usr/bin/env python3
"""
STEP3+STEP4 统一 Transport 模块 v1.0.0

所有引擎调用必须经过此模块，保证：
1. baseUrl 规范化（/v1 恰好一次）
2. 全部走 OpenAI-compatible chat completions
3. 统一 Bearer auth
4. 统一 rate limiting
5. 统一错误分类与重试

安全规则：
- 不打印完整 key
- 不从 stdin 读取 key
"""

import os
import json
import time
import base64
import traceback
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

from dotenv import dotenv_values
from openai import OpenAI

# ─── Constants ───

PROJECT_ROOT = Path("/Volumes/小满/yongle_palace_dataset")
ENV_FILE = PROJECT_ROOT / ".env.step4.local"

ENGINE_DEFAULTS = {
    "openai": {
        "key_var": "OPENAI_API_KEY",
        "url_var": "OPENAI_BASE_URL",
        "model": "gpt-4o",
        "temperature": 0.10,
        "source": "gptsapi.net proxy",
    },
    "gemini": {
        "key_var": "GEMINI_API_KEY",
        "url_var": "GEMINI_BASE_URL",
        "model": "gemini-2.5-flash",
        "temperature": 0.05,
        "source": "gptsapi.net proxy",
    },
    "claude": {
        "key_var": "ANTHROPIC_API_KEY",
        "url_var": "ANTHROPIC_BASE_URL",
        "model": "claude-sonnet-4-6",
        "temperature": 0.15,
        "source": "gptsapi.net proxy",
    },
    "qwen": {
        "key_var": "DASHSCOPE_API_KEY",
        "url_var": "QWEN_BASE_URL",
        "fallback_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-max-latest",
        "temperature": 0.08,
        "source": "DashScope official",
    },
}


# ─── URL Normalization ───

def normalize_base_url(url: str) -> str:
    """确保 URL 以 /v1 结尾恰好一次，适用于 OpenAI-compatible SDK。"""
    if not url:
        return url
    url = url.rstrip("/")
    if url.endswith("/v1"):
        return url
    return url + "/v1"


def mask_key(key: str) -> str:
    if not key or len(key) < 10:
        return "(empty)"
    return f"{key[:6]}...{key[-4:]}"


# ─── Engine Client ───

@dataclass
class EngineClient:
    name: str
    api_key: str
    base_url: str
    model: str
    temperature: float
    source: str
    client: Optional[OpenAI] = field(default=None, repr=False)
    ready: bool = False

    def __post_init__(self):
        if self.api_key and self.base_url:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            self.ready = True

    def info(self) -> dict:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "source": self.source,
            "key_preview": mask_key(self.api_key),
            "endpoint": f"{self.base_url}/chat/completions",
            "auth_mode": "Bearer (OpenAI-compatible)",
            "ready": self.ready,
        }

    def call(self, messages: list, max_tokens: int = 1024, timeout: int = 60) -> dict:
        """
        统一调用入口。返回标准化结果 dict。
        """
        t0 = time.time()
        result = {
            "engine": self.name,
            "model_requested": self.model,
            "model_returned": None,
            "success": False,
            "content": None,
            "latency_s": 0,
            "error_type": None,
            "error_message": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            result["latency_s"] = round(time.time() - t0, 2)
            result["success"] = True
            result["content"] = resp.choices[0].message.content if resp.choices else ""
            result["model_returned"] = resp.model or self.model
        except Exception as e:
            result["latency_s"] = round(time.time() - t0, 2)
            result["error_type"] = type(e).__name__
            result["error_message"] = str(e)[:500]
        return result


# ─── Rate Limiter ───

class RateLimiter:
    """Global serial rate limiter — enforces min interval across ALL engines."""

    def __init__(self, min_interval_s: float = 1.5, max_rpm: int = 20):
        self.min_interval = min_interval_s
        self.max_rpm = max_rpm
        self._last_call_global: float = 0
        self._call_timestamps: list[float] = []

    def wait(self, engine_name: str):
        now = time.time()
        # 1. Global min interval (across all engines)
        gap = now - self._last_call_global
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        # 2. RPM cap (sliding 60s window)
        now = time.time()
        cutoff = now - 60
        self._call_timestamps = [t for t in self._call_timestamps if t > cutoff]
        if len(self._call_timestamps) >= self.max_rpm:
            wait_until = self._call_timestamps[0] + 60
            if wait_until > now:
                time.sleep(wait_until - now)
        now = time.time()
        self._last_call_global = now
        self._call_timestamps.append(now)


# ─── Retry Logic ───

def call_with_retry(engine: EngineClient, messages: list, limiter: RateLimiter,
                    max_tokens: int = 1024, timeout: int = 60,
                    retry_429: int = 3, retry_5xx: int = 2, retry_socket: int = 1,
                    retry_parse: int = 2,
                    json_validator: Optional[callable] = None) -> dict:
    """带重试的调用。429 指数退避，5xx 固定重试，socket 重试一次，JSON 解析失败重试。

    json_validator: 可选回调 f(content_str) -> dict|None。
      返回 dict 表示解析成功（存入 result["parsed_json"]）。
      返回 None 表示解析失败，触发 parse retry。
    """
    attempts = 0
    parse_attempts = 0

    while True:
        limiter.wait(engine.name)
        result = engine.call(messages, max_tokens=max_tokens, timeout=timeout)
        attempts += 1
        result["attempt"] = attempts
        result["parsed_json"] = None
        result["parse_error"] = None

        if result["success"]:
            # JSON validation inside retry loop
            if json_validator and result["content"]:
                parsed = json_validator(result["content"])
                if parsed is not None:
                    result["parsed_json"] = parsed
                    return result
                else:
                    parse_attempts += 1
                    result["parse_error"] = f"json_validate_fail (attempt {parse_attempts})"
                    if parse_attempts <= retry_parse:
                        time.sleep(1)
                        continue
                    # Exhausted parse retries — return with parse_error set
                    return result
            return result

        err = result["error_message"] or ""
        etype = result["error_type"] or ""

        # 429: rate limit
        if "429" in err or "rate" in err.lower():
            if attempts <= retry_429:
                wait = 2 ** attempts
                time.sleep(wait)
                continue

        # 5xx server error
        if any(f"{c}" in err for c in [500, 502, 503, 504]):
            if attempts <= retry_5xx:
                time.sleep(2)
                continue

        # Socket / connection error
        if "socket" in err.lower() or "connect" in err.lower() or "UND_ERR" in err:
            if attempts <= retry_socket:
                time.sleep(3)
                continue

        # No more retries
        return result


# ─── Factory ───

def _load_transport_lock() -> dict:
    """Load transport lock config for URL validation."""
    lock_path = PROJECT_ROOT / "configs" / "step3_4_transport_lock.yaml"
    if lock_path.exists():
        import yaml
        return yaml.safe_load(open(lock_path))
    return {}


def _validate_base_url(engine_name: str, url: str, lock: dict) -> str:
    """Validate base URL against transport lock. Raises ValueError on violation."""
    if not url:
        raise ValueError(f"{engine_name}: empty base_url")

    # Check forbidden domains/paths
    for fp in lock.get("forbidden_paths", []):
        pattern = fp["path"]
        if pattern in url:
            raise ValueError(f"{engine_name}: forbidden path '{pattern}' in URL '{url}' — {fp['reason']}")

    # Reject double /v1
    guards = lock.get("runtime_guards", {})
    if guards.get("reject_double_v1") and url.count("/v1") > 1:
        raise ValueError(f"{engine_name}: double /v1 in URL '{url}'")

    # Reject missing /v1
    if guards.get("reject_missing_v1") and "/v1" not in url:
        raise ValueError(f"{engine_name}: missing /v1 in URL '{url}'")

    # Cross-check with lockfile allowed URLs
    lock_engines = lock.get("engines", {})
    if engine_name in lock_engines:
        expected = lock_engines[engine_name].get("base_url", "")
        if expected and url != expected:
            raise ValueError(f"{engine_name}: URL '{url}' does not match lockfile '{expected}'")

    return url


def load_engines(env_path: str = None) -> dict[str, EngineClient]:
    """加载所有引擎，统一经过 normalize_base_url + transport lock 校验。"""
    if env_path is None:
        env_path = str(ENV_FILE)
    env = dotenv_values(env_path)
    lock = _load_transport_lock()

    engines = {}
    for name, defaults in ENGINE_DEFAULTS.items():
        key = env.get(defaults["key_var"], "")
        raw_url = env.get(defaults.get("url_var", ""), "") or defaults.get("fallback_url", "")
        normed_url = normalize_base_url(raw_url)

        # Validate against transport lock
        try:
            _validate_base_url(name, normed_url, lock)
        except ValueError as e:
            print(f"[TRANSPORT] BLOCKED: {e}")
            engines[name] = EngineClient(
                name=name, api_key="", base_url="", model=defaults["model"],
                temperature=defaults["temperature"], source=f"BLOCKED: {e}",
            )
            continue

        engines[name] = EngineClient(
            name=name,
            api_key=key,
            base_url=normed_url,
            model=defaults["model"],
            temperature=defaults["temperature"],
            source=defaults["source"],
        )
    return engines


# ─── Message Builders ───

def build_text_message(text: str) -> list:
    return [{"role": "user", "content": text}]


def build_image_message(text: str, image_b64: str, mime: str = "image/png") -> list:
    return [{"role": "user", "content": [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
    ]}]


def build_step3_4_message(system_prompt: str, user_prompt: str, image_b64: str) -> list:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]},
    ]


def image_to_b64(path: str | Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def image_to_b64_thumbnail(path: str | Path, max_size: int = 256) -> str:
    from PIL import Image
    import io
    img = Image.open(path)
    img.thumbnail((max_size, max_size))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()
