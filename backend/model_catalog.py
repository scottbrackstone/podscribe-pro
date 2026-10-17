import os
import threading
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import requests

from .ai_generation import DEFAULT_CONTENT_MODEL

DEFAULT_MODEL_IDS = (
    DEFAULT_CONTENT_MODEL,
    "deepseek/deepseek-v4-flash-0731",
    "~z-ai/glm-latest",
    "openai/gpt-5.6-luna",
    "google/gemini-3.8-flash",
    "anthropic/claude-haiku-4.5",
    "x-ai/grok-4.6",
)

def configured_default_model() -> str:
    return os.getenv("CONTENT_DEFAULT_MODEL", DEFAULT_CONTENT_MODEL).strip() or DEFAULT_CONTENT_MODEL

def configured_model_ids() -> tuple[str, ...]:
    values = [v.strip() for v in os.getenv("CONTENT_MODEL_IDS", ",".join(DEFAULT_MODEL_IDS)).split(",") if v.strip()]
    default = configured_default_model()
    if default not in values: values.insert(0, default)
    return tuple(dict.fromkeys(values))

def _decimal_env(name: str, fallback: str) -> Decimal:
    try: return Decimal(os.getenv(name, fallback))
    except InvalidOperation: return Decimal(fallback)

def _per_million(value: Any) -> Decimal | None:
    try: return Decimal(str(value)) * Decimal("1000000")
    except (InvalidOperation, TypeError): return None

def _supports_schema(model: dict[str, Any]) -> bool:
    params = model.get("supported_parameters") or []
    return "structured_outputs" in params or "response_format" in params

@dataclass
class ModelCatalog:
    api_key: str | None = None
    endpoint: str = "https://openrouter.ai/api/v1/models"
    ttl_seconds: int = 900
    timeout_seconds: int = 15

    def __post_init__(self) -> None:
        self._lock = threading.Lock(); self._cached_at = 0.0; self._cached_models: list[dict[str, Any]] | None = None

    def get_models(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            if self._cached_models is not None and now - self._cached_at < self.ttl_seconds:
                return self._build(self._cached_models, "live-cache")
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            response = requests.get(self.endpoint, headers=headers, timeout=self.timeout_seconds)
            response.raise_for_status(); models = response.json().get("data")
            if not isinstance(models, list): raise ValueError
            with self._lock: self._cached_models, self._cached_at = models, now
            return self._build(models, "live")
        except (requests.RequestException, ValueError, TypeError):
            with self._lock: cached = self._cached_models
            if cached is not None:
                result = self._build(cached, "stale-cache")
                result["warning"] = "Live model metadata is unavailable; showing the last known catalog."
                return result
            return self._fallback()

    def allowed_model_ids(self) -> set[str]:
        return {m["id"] for m in self.get_models()["models"] if m["enabled"]}

    def _build(self, catalog: list[dict[str, Any]], source: str) -> dict[str, Any]:
        found = {str(m.get("id")): m for m in catalog}
        max_in, max_out = _decimal_env("CONTENT_MAX_INPUT_PRICE", "2"), _decimal_env("CONTENT_MAX_OUTPUT_PRICE", "6")
        items = []
        for model_id in configured_model_ids():
            raw = found.get(model_id)
            if raw is None:
                items.append(self._disabled(model_id, "Not present in the current OpenRouter catalog")); continue
            in_price = _per_million((raw.get("pricing") or {}).get("prompt"))
            out_price = _per_million((raw.get("pricing") or {}).get("completion"))
            reason = None
            if not _supports_schema(raw): reason = "Structured JSON output is not currently advertised"
            elif in_price is None or out_price is None: reason = "Pricing metadata is unavailable"
            elif in_price > max_in or out_price > max_out: reason = "Current pricing exceeds the configured ceiling"
            items.append({"id": model_id, "name": str(raw.get("name") or model_id), "enabled": reason is None,
                "reason": reason, "input_price_per_million": float(in_price) if in_price is not None else None,
                "output_price_per_million": float(out_price) if out_price is not None else None})
        return {"models": items, "default_model": configured_default_model(), "metadata_source": source,
            "price_ceiling": {"input_per_million": float(max_in), "output_per_million": float(max_out)}}

    def _fallback(self) -> dict[str, Any]:
        default = configured_default_model()
        items = [{"id": mid, "name": mid, "enabled": mid == default,
            "reason": None if mid == default else "Live metadata is required before this model can be selected",
            "input_price_per_million": None, "output_price_per_million": None} for mid in configured_model_ids()]
        return {"models": items, "default_model": default, "metadata_source": "safe-fallback",
            "warning": "Live model metadata is unavailable. Only the configured default is enabled.",
            "price_ceiling": {"input_per_million": float(_decimal_env("CONTENT_MAX_INPUT_PRICE", "2")),
                              "output_per_million": float(_decimal_env("CONTENT_MAX_OUTPUT_PRICE", "6"))}}

    @staticmethod
    def _disabled(model_id: str, reason: str) -> dict[str, Any]:
        return {"id": model_id, "name": model_id, "enabled": False, "reason": reason,
                "input_price_per_million": None, "output_price_per_million": None}
