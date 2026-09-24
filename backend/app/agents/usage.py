"""Token and search usage for one agent run, and its estimated cost."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import get_settings


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    searches: int = 0
    model: str = ""  # the model that answered last; differs from the requested one after a fallback

    def add(self, response: Any) -> None:
        """Add one API response's usage."""
        usage = response.usage
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        self.cache_write_tokens += usage.cache_creation_input_tokens or 0
        self.cache_read_tokens += usage.cache_read_input_tokens or 0
        stu = getattr(usage, "server_tool_use", None)
        self.searches += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
        self.model = getattr(response, "model", "") or self.model

    def cost_usd(self) -> float:
        s = get_settings()
        return round(
            self.input_tokens / 1e6 * s.price_input_per_mtok
            + self.output_tokens / 1e6 * s.price_output_per_mtok
            + self.cache_write_tokens / 1e6 * s.price_cache_write_per_mtok
            + self.cache_read_tokens / 1e6 * s.price_cache_read_per_mtok
            + self.searches * s.price_per_search,
            4,
        )
