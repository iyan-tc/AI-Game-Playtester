from decimal import Decimal

import httpx
import pytest

from playtester.budget import Ledger
from playtester.config import load
from playtester.memory import Memory
from playtester.parallel import allocate
from playtester.providers import VendorPlayer
from playtester.security import Privacy


@pytest.mark.parametrize(("model","provider"),[("glm-4.6v","glm"),("gemini-2.5-flash","gemini")])
def test_provider_payload_usage_and_invalid_decision(model,provider):
    _,persona,settings=load("demo","explorer",{"default_model":model})
    state=Memory(run_id="case",game_id="demo",persona_id="explorer",account_alias="test")
    requests=[]
    def server(req):
        requests.append(req)
        if req.url.path.endswith("countTokens"):
            return httpx.Response(200,json={"totalTokens":2000})
        return httpx.Response(200,json={})
    player=VendorPlayer(settings,persona,Ledger(state,settings,lambda:None),Privacy(),lambda *_:None,"synthetic",
                        httpx.Client(transport=httpx.MockTransport(server)))
    url,headers,body,bound=player.request(state,b"pixels",(390,640))
    if provider=="glm":
        assert "api.z.ai" in url and "image_url" in str(body) and bound==131072
        usage,get=player.decode({"usage":{"prompt_tokens":80,"completion_tokens":30,
            "prompt_tokens_details":{"cached_tokens":20}},"choices":[{"message":{"content":"{}"}}]})
    else:
        assert url.endswith("generateContent") and "inlineData" in str(body) and len(requests)==1
        usage,get=player.decode({"usageMetadata":{"promptTokenCount":80,"cachedContentTokenCount":20,
            "candidatesTokenCount":20,"thoughtsTokenCount":10},"candidates":[{"content":{"parts":[{"text":"{}"}]}}]})
    assert get()=="{}" and usage["output_tokens"]==30
    ledger=player.ledger
    row=ledger.reserve(1,model,bound)
    ledger.settle(row,usage)
    assert row["cache_read_tokens"]==20 and row["uncached_input_tokens"]==60 and state.reserved_usd==0


def test_batch_ceiling():
    assert Decimal(allocate(Decimal(1),3))*3<=1
    with pytest.raises(ValueError):
        allocate(Decimal(2),2)

