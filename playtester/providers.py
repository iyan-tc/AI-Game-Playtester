"""Vision transports use fixed vendor origins. Provider errors never log request bodies."""
import base64
import time
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from .budget import input_bound
from .llm_client import Player
from .models import Decision
from .security import RULES, StopRun, dump


def make_player(settings, persona, ledger, privacy, log, key):
    provider = settings.models[settings.default_model].provider
    if provider == "openai":
        return Player(settings, persona, ledger, privacy, log)
    return VendorPlayer(settings, persona, ledger, privacy, log, key)


class VendorPlayer:
    def __init__(self, settings, persona, ledger, privacy, log, key, http=None):
        self.settings, self.ledger, self.privacy, self.log = settings, ledger, privacy, log
        self.key = key
        self.http = http or httpx.Client(timeout=60, follow_redirects=False)
        self.rules = RULES + "\n" + dump(dict(profile=persona.profile, dimensions=persona.dimensions)) + "\n" + dump(Decision.model_json_schema())

    def post(self, url, headers, data):
        r = self.http.post(url, headers=headers, json=data)
        r.raise_for_status()
        return r.json()

    def request(self, state, image, size):
        model = self.settings.default_model
        rates = self.settings.models[model]
        effort = self.settings.reasoning_effort
        text = self.privacy.clean(dump(state.model_memory()))
        encoded = base64.b64encode(image).decode("ascii")
        maximum = self.settings.max_output_tokens
        if rates.provider == "glm":
            url = "https://api.z.ai/api/paas/v4/chat/completions"
            headers = {"Authorization":"Bearer "+self.key}
            body = dict(model=model,max_tokens=maximum,thinking={"type":"disabled" if effort=="low" else "enabled"},
                        response_format={"type":"json_object"},messages=[{"role":"system","content":self.rules},
                        {"role":"user","content":[{"type":"text","text":text},{"type":"image_url",
                        "image_url":{"url":"data:image/png;base64,"+encoded}}]}])
            # No exact image counter is assumed. The configured model context window
            # bounds any accepted request. An overlength request fails at the provider.
            return url,headers,body,rates.context_limit
        prefix = "https://generativelanguage.googleapis.com/v1beta/models/"+quote(model,safe="")
        headers = {"x-goog-api-key":self.key}
        content = [{"role":"user","parts":[{"text":text},{"inlineData":{"mimeType":"image/png","data":encoded}}]}]
        system = {"parts":[{"text":self.rules}]}
        thinking = min(maximum//2, {"low":128, "medium":768, "high":4096}[effort])
        body = dict(contents=content,systemInstruction=system,generationConfig=dict(maxOutputTokens=maximum,
                    responseMimeType="application/json",thinkingConfig={"thinkingBudget":thinking}))
        local_bound = input_bound(len((self.rules+text).encode()), *size)
        self.ledger.check(model, local_bound)
        count = self.post(prefix+":countTokens",headers,{"generateContentRequest":{"model":"models/"+model,**body}})
        bound = max(count["totalTokens"], local_bound)
        return prefix+":generateContent",headers,body,bound

    def decode(self, response):
        if "usageMetadata" in response:
            u=response["usageMetadata"]
            reasoning=u.get("thoughtsTokenCount",0)
            usage=dict(input_tokens=u["promptTokenCount"], output_tokens=u.get("candidatesTokenCount",0)+reasoning,
                       input_tokens_details=dict(cached_tokens=u.get("cachedContentTokenCount",0)),
                       output_tokens_details=dict(reasoning_tokens=reasoning))
            return usage, lambda:"".join(p.get("text","") for p in response["candidates"][0]["content"]["parts"] if not p.get("thought"))
        u=response["usage"]
        return dict(input_tokens=u["prompt_tokens"],output_tokens=u["completion_tokens"],
                    input_tokens_details=u.get("prompt_tokens_details") or {},
                    output_tokens_details=u.get("completion_tokens_details") or {}), lambda:response["choices"][0]["message"]["content"]

    def decide(self,state,image,size):
        model=self.settings.default_model
        for attempt in range(1,4):
            row=None
            try:
                url,headers,body,count=self.request(state,image,size)
                row=self.ledger.reserve(state.step_index+1,model,count)
                usage,content=self.decode(self.post(url,headers,body))
                self.ledger.settle(row,usage)
                decision=Decision.model_validate_json(content())
                return model, Decision.model_validate(self.privacy.tree(decision.model_dump()))
            except (httpx.HTTPError,ValueError,KeyError,IndexError,TypeError) as exc:
                status=exc.response.status_code if isinstance(exc,httpx.HTTPStatusError) else None
                if row is not None:
                    self.ledger.uncertain(row,"invalid_decision" if row["actual_usd"] is not None else "unknown_usage")
                self.log(f"模型传输尝试 {attempt}/3 {type(exc).__name__} {status or ''}")
                if attempt==3 or (status and status<500 and status not in {408,429}):
                    raise StopRun("API_FAILED",f"{type(exc).__name__} {status or ''}") from None
                time.sleep(2**(attempt-1))
