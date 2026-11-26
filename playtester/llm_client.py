import base64
import time
from typing import Protocol

from openai import APIConnectionError, APIStatusError, OpenAI
from pydantic import ValidationError

from .budget import input_bound
from .models import Decision
from .security import RULES, StopRun, dump


class ModelRouter(Protocol):
    def select_model(self, stage, stuck_count, is_reflection) -> str: ...


class SingleModelRouter:
    def __init__(self, model):
        self.model = model

    def select_model(self, stage, stuck_count, is_reflection):
        return self.model


class Player:
    def __init__(self, settings, persona, ledger, privacy, log, client=None, router=None):
        self.settings = settings
        self.client = client or OpenAI(base_url="https://api.openai.com/v1", timeout=60, max_retries=0)
        self.router = router or SingleModelRouter(settings.default_model)
        self.ledger = ledger
        self.privacy = privacy
        self.log = log
        self.instructions = RULES + "\n" + dump(dict(name=persona.name, profile=persona.profile,
                                                     dimensions=persona.dimensions))
        self.format = {"format": {"type": "json_schema", "name": "player_decision", "strict": True,
                                  "schema": Decision.model_json_schema()}}

    def decide(self, state, image, size):
        model = self.router.select_model(state.phase, state.missed_clicks, False)
        dynamic = self.privacy.clean(dump(state.model_memory()))
        content = [{"type": "input_text", "text": dynamic},
                   {"type": "input_image", "detail": "high", "image_url":
                    "data:image/png;base64," + base64.b64encode(image).decode("ascii")}]
        common = dict(model=model, instructions=self.instructions, text=self.format,
                      reasoning={"effort": self.settings.reasoning_effort},
                      input=[{"role": "user", "content": content}])
        bound = input_bound(len((self.instructions + dump(self.format) + dynamic).encode()), *size)
        for attempt in range(1, 4):
            # No Responses generation is sent until its full ceiling has been reserved on disk.
            row = None
            try:
                count = self.client.responses.input_tokens.count(**common).input_tokens
                row = self.ledger.reserve(state.step_index + 1, model, max(bound, count))
                result = self.client.responses.create(**common, store=False,
                                                      max_output_tokens=self.settings.max_output_tokens)
                if result.usage is None:
                    raise StopRun("USAGE_UNKNOWN", "API 未返回用量，保留预留金额")
                self.ledger.settle(row, result.usage.model_dump())
                data = Decision.model_validate_json(result.output_text)
                return model, Decision.model_validate(self.privacy.tree(data.model_dump()))
            except (APIConnectionError, APIStatusError, ValidationError) as exc:
                code = getattr(exc, "status_code", None)
                label = type(exc).__name__ + (f" HTTP {code}" if code else "")
                if row is not None:
                    if row["status"] == "reserved":
                        self.ledger.uncertain(row, label)
                    else:
                        row["status"] = "invalid_decision"
                        self.ledger.persist()
                self.log(f"API 尝试 {attempt}/3：{label}")
                if code and code < 500 and code not in {408, 429}:
                    raise StopRun("API_FAILED", label) from None
                if attempt == 3:
                    raise StopRun("API_FAILED", label) from None
                time.sleep(2 ** (attempt - 1))

