import csv
import json
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image, ImageDraw

from playtester.acceptance import inspect
from playtester.budget import Ledger
from playtester.cli import main
from playtester.config import load
from playtester.detector import classify
from playtester.llm_client import Player
from playtester.memory import Memory, verify
from playtester.offline import fixture_client
from playtester.security import Privacy, StopRun, allowed
from playtester.vision_assist import NullHotspotProvider
from games.demo.adapter import Adapter


@pytest.fixture
def config():
    return load("demo", "explorer", {})


@pytest.fixture
def state():
    return Memory(run_id="example", game_id="demo", persona_id="explorer", account_alias="fixture")


def test_reserve_and_settle(config, state):
    settings = config[2]
    ledger = Ledger(state, settings, lambda: None)
    row = ledger.reserve(1, settings.default_model, 2000)
    ledger.settle(row, dict(input_tokens=2000, output_tokens=1000, input_tokens_details=dict(
        cached_tokens=500, cache_write_tokens=400), output_tokens_details=dict(reasoning_tokens=250)))
    assert state.spent_usd == Decimal(".006625") and state.reserved_usd == 0
    state.spent_usd = Decimal(".999")
    with pytest.raises(StopRun, match="调用前拦截"):
        ledger.reserve(2, settings.default_model, 2000)
    assert len(state.usage) == 1


def test_uncertain_retries_and_real_sdk(config, state, monkeypatch):
    import openai
    monkeypatch.setattr("playtester.llm_client.time.sleep", lambda *_: None)
    settings = config[2]
    client = fixture_client(state)
    def fail(**kwargs):
        raise openai.APITimeoutError(request=httpx.Request("POST","https://offline.invalid"))
    monkeypatch.setattr(client.responses, "create", fail)
    ledger = Ledger(state, settings, lambda: None)
    p = Player(settings, config[1], ledger, Privacy(), lambda *_: None, client)
    with pytest.raises(StopRun):
        p.decide(state,b"sample",(390,844))
    assert len(state.usage)==3 and state.spent_usd==0
    assert state.reserved_usd == sum(Decimal(row["est_max_usd"]) for row in state.usage)
    assert all(row["actual_usd"] is None for row in state.usage)


def frame(rect=None):
    im = Image.new("RGB",(100,100))
    if rect:
        ImageDraw.Draw(im).rectangle(rect, fill="white")
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize(("rect","status"), [(None,"no_visible_change"), ((50,50,52,53),"subtle_feedback"),
    ((20,20,60,60),"modal_or_panel_change"), ((0,0,95,95),"major_transition")])
def test_detection(rect,status):
    base, after = frame(), frame(rect)
    assert classify(base,[after,after],(50,50))==status
    assert classify(base,[base,after], pending=True)=="loading_or_animation"
    assert classify(base,[base,base], writes=True)=="subtle_feedback"
    assert classify(base,[base,base], error=True)=="runtime_error"


def test_revision_and_identity(config, state):
    game, persona, _ = config
    with pytest.raises(StopRun):
        Adapter(game, persona, "unrelated-user", "fake")
    adapter = Adapter(game, persona, persona.test_account, "synthetic")
    assert not adapter.permits_write("/api/save","PUT")
    state.last_confirmed_server_revision = 7
    with pytest.raises(StopRun, match="回退"):
        verify(state,{},6)
    verify(state,{},7)
    verify(state,{},8)
    for other in ("http://game.invalid:8086/", "https://game.invalid:8086.evil.local/",
                  "https://game.invalid:8086@other.invalid/", "https://game.invalid:8087/"):
        assert not allowed(other, ["game.invalid:8086"])
    assert allowed("https://game.invalid:8086/",["game.invalid:8086"])
    privacy = Privacy("ai_fixture","example-password")
    output = privacy.clean("ai_fixture example-password demo_session=Abcd123; sk-fake123456789")
    assert all(token not in output for token in ("fixture","password","Abcd","fake"))
    assert NullHotspotProvider().get_hotspots(None)==[]


def test_offline_pause_resume_artifacts(tmp_path):
    folder = tmp_path/"case"
    args = ["--output",str(tmp_path),"--run-id","case"]
    assert main(["dry-run",*args,"--pause-at","10"])==0
    checkpoint=folder/"memory_checkpoint.json"
    before=json.loads(checkpoint.read_bytes())
    assert before["status"]=="PAUSED" and before["step_index"]==10
    first=(folder/"screenshots/raw/step_001_before.png").read_bytes()
    assert main(["resume","--resume",str(checkpoint)])==0
    state=json.loads(checkpoint.read_bytes())
    assert all(inspect(folder,False).values())
    assert state["sessions"][-1]["start_revision"]==before["last_confirmed_server_revision"]
    assert Decimal(state["spent_usd"]) > Decimal(before["spent_usd"])
    assert state["natural_quit_events"][0]["step"]==4 and state["phase"]=="return_after_quit"
    assert state["steps"][2]["grid"] and not state["steps"][3]["grid"]
    assert state["steps"][1]["attempt_evidence"]
    assert len(state["rolling_summary"])<=600 and len(state["recent_steps"])==8
    assert not list(folder.rglob("*.tmp"))
    assert first==(folder/"screenshots/raw/step_001_before.png").read_bytes()
    rows=list(csv.DictReader((folder/"usage_and_cost.csv").open(encoding="utf-8")))
    assert len(rows)==50 and rows[0]["cache_write_source"]=="not_returned:0"


def test_budget_exit_produces_all_reports(tmp_path):
    assert main(["dry-run","--output",str(tmp_path),"--run-id","budget","--max-budget-usd",".001"])==0
    folder=tmp_path/"budget"
    data=json.loads((folder/"memory_checkpoint.json").read_bytes())
    assert data["status"]=="BUDGET_EXHAUSTED" and data["usage"]==[]
    assert inspect(folder,False)["artifacts"]

