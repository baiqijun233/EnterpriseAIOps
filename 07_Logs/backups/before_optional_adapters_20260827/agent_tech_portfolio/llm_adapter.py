"""可替换的 LLM 接口：默认离线客户端和 OpenAI 兼容 HTTP 客户端。"""

from __future__ import annotations

import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMClient(Protocol):
    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        """根据提示和结构化上下文生成文本。"""


class DeterministicLLMClient:
    """离线演示客户端，保证没有 API Key 时仍可测试。"""

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt 不能为空")
        service = (context or {}).get("service", "目标服务")
        confidence = (context or {}).get("confidence", 0)
        return f"根据已验证证据，{service} 的异常根因候选置信度为 {confidence}。建议先执行受审批保护的低风险操作。"


class OpenAICompatibleLLMClient:
    """调用 OpenAI 兼容 chat/completions 接口，不依赖第三方 SDK。"""

    def __init__(self, endpoint: str, api_key: str, model: str, timeout: float = 15.0) -> None:
        if not isinstance(endpoint, str) or not endpoint.startswith(("http://", "https://")):
            raise ValueError("endpoint 必须是 http(s) 地址")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key 不能为空")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model 不能为空")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout 必须是正数")
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.timeout = float(timeout)

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt 不能为空")
        user_content = prompt
        if context:
            try:
                user_content += "\n结构化上下文:\n" + json.dumps(context, ensure_ascii=False)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"context 不可 JSON 序列化: {exc}") from exc
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": user_content}],
            "temperature": 0,
        }
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"LLM 请求失败: {exc}") from exc
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("LLM 响应缺少 choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM 返回内容为空")
        return content.strip()
