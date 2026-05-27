"""OpenRouter API client used by model and judge integrations."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib import request
from urllib.error import HTTPError

from scopebench.config import ScopebenchConfig, load_config


PLACEHOLDER_API_KEY = "YOUR_OPENROUTER_API_KEY"


class OpenRouterError(RuntimeError):
    """Raised when OpenRouter cannot be called or returns an error."""


@dataclass(frozen=True)
class OpenRouterClient:
    """Minimal OpenAI-compatible chat client for OpenRouter."""

    config: ScopebenchConfig

    @classmethod
    def from_config(cls, config: ScopebenchConfig | None = None) -> "OpenRouterClient":
        return cls(config=config or load_config())

    def chat_completion(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """Call OpenRouter's chat completions endpoint."""

        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self._url("/chat/completions"),
            data=body,
            method="POST",
            headers=self._headers(),
        )
        try:
            with request.urlopen(req, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise OpenRouterError(f"OpenRouter HTTP {exc.code}: {error_body}") from exc
        except OSError as exc:
            raise OpenRouterError(f"OpenRouter request failed: {exc}") from exc

    def list_models(self) -> set[str]:
        """Return the model IDs currently listed by OpenRouter."""

        req = request.Request(self._url("/models"), method="GET")
        try:
            with request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise OpenRouterError(f"OpenRouter HTTP {exc.code}: {error_body}") from exc
        except OSError as exc:
            raise OpenRouterError(f"OpenRouter model listing failed: {exc}") from exc
        models = payload.get("data", [])
        if not isinstance(models, list):
            raise OpenRouterError("OpenRouter model listing returned unexpected payload")
        return {str(item["id"]) for item in models if isinstance(item, dict) and "id" in item}

    def validate_configured_models(self) -> dict[str, bool]:
        """Check configured model and judge IDs against OpenRouter's model list."""

        available = self.list_models()
        ids = {*self.config.model_names, *self.config.judge_names}
        return {str(model_id): str(model_id) in available for model_id in sorted(ids)}

    def _headers(self) -> dict[str, str]:
        openrouter = self.config.openrouter
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }
        if openrouter.get("site_url"):
            headers["HTTP-Referer"] = openrouter["site_url"]
        if openrouter.get("app_name"):
            headers["X-Title"] = openrouter["app_name"]
        return headers

    def _api_key(self) -> str:
        openrouter = self.config.openrouter
        env_name = openrouter.get("api_key_env", "OPENROUTER_API_KEY")
        env_key = os.environ.get(env_name, "")
        if env_key:
            return env_key
        configured_key = openrouter.get("api_key", "")
        if configured_key and configured_key != PLACEHOLDER_API_KEY:
            return configured_key
        raise OpenRouterError(
            f"set {env_name} or replace openrouter.api_key in {self.config.path}"
        )

    def _url(self, path: str) -> str:
        base_url = self.config.openrouter.get("base_url", "").rstrip("/")
        return f"{base_url}{path}"
