from decimal import Decimal
from math import ceil

from .security import StopRun, now

MILLION = Decimal(1_000_000)


def input_bound(text_bytes, width, height):
    # UTF-8 byte upper bound for text, plus an envelope for message/schema framing.
    # Cover both tiled and 32px patch image encodings. The remote count also guards
    # against changes to the provider's image encoding for the configured model.
    tiles = ceil(width / 512) * ceil(height / 512)
    patches = ceil(width / 32) * ceil(height / 32)
    return text_bytes + 1024 + max(1024 * (tiles + 1), 4 * patches)


class Ledger:
    def __init__(self, state, settings, persist):
        self.state = state
        self.settings = settings
        self.persist = persist

    def check(self, model, tokens):
        rates = self.settings.models[model]
        estimate = (tokens * max(rates.input, rates.cache_write, rates.cache_read) +
                    self.settings.max_output_tokens * rates.output) / MILLION
        if self.state.spent_usd + self.state.reserved_usd + estimate > self.settings.max_budget_usd:
            raise StopRun("BUDGET_EXHAUSTED", f"调用前拦截，本次最高费用 {estimate}")
        return estimate

    def reserve(self, step, model, tokens):
        estimate = self.check(model, tokens)
        row = dict(step=step, timestamp=now(), model=model, reasoning_effort=self.settings.reasoning_effort,
                   status="reserved", uncached_input_tokens=None, cache_write_tokens=None,
                   cache_read_tokens=None, output_tokens=None, reasoning_tokens=None, cache_hit_rate=None,
                   est_max_usd=str(estimate), actual_usd=None, cache_write_source="unknown",
                   cumulative_usd=str(self.state.spent_usd))
        self.state.usage.append(row)
        self.state.reserved_usd += estimate
        self.persist()
        return row

    def uncertain(self, row, status):
        row["status"] = status
        self.persist()  # unknown billing retains the full reservation across retries/resume

    def settle(self, row, usage):
        total = usage["input_tokens"]
        output = usage["output_tokens"]
        details = usage.get("input_tokens_details") or {}
        read = details.get("cached_tokens", 0)
        field = next((k for k in ("cache_write_tokens", "cache_creation_tokens", "cache_write_input_tokens")
                      if details.get(k) is not None), None)
        write = details[field] if field else 0
        ordinary = total - read - write
        reasoning = (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0)
        if min(ordinary, output, read, write, reasoning) < 0 or reasoning > output:
            raise StopRun("INVALID_USAGE", "API 返回的 token 分项不一致")
        rates = self.settings.models[row["model"]]
        cost = (ordinary*rates.input + read*rates.cache_read + write*rates.cache_write +
                output*rates.output) / MILLION
        estimate = Decimal(row["est_max_usd"])
        self.state.spent_usd += cost
        self.state.reserved_usd -= estimate
        row.update(status="ok", uncached_input_tokens=ordinary, cache_write_tokens=write,
                   cache_read_tokens=read, output_tokens=output, reasoning_tokens=reasoning,
                   cache_hit_rate=read / total if total else 0, actual_usd=str(cost),
                   cumulative_usd=str(self.state.spent_usd), cache_write_source=field or "not_returned:0")
        self.persist()
        if cost > estimate:
            raise StopRun("PRICE_BOUND_ERROR", "实际用量超过预留，暂停后续调用")
