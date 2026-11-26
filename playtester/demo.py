"""Hosted Chromium integration benchmark. Only aggregate synthetic metrics go to stdout."""
import argparse
import json
import os
import secrets
import statistics
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from io import BytesIO
from pathlib import Path

from PIL import Image

from games.demo.server import serve
from .agent import play
from .browser import Browser
from .config import load
from .security import StopRun
from .memory import Memory, save, verify
from .models import Decision
from .budget import Ledger
from .reporter import Reporter
from .security import Privacy, now
from .providers import make_player


class DemoVision:
    """Find a visible amber signal using pixels. This is a deterministic integration fixture."""
    def __init__(self,settings):
        self.settings=settings

    def decide(self,state,image,size):
        with Image.open(BytesIO(image)) as im:
            rgb=im.convert("RGB")
            mask=Image.new("1",rgb.size)
            mask.putdata([r>230 and 160<g<220 and b<145 for r,g,b in rgb.getdata()])
            bounds=mask.getbbox()
        if not bounds:
            raise RuntimeError("Fixture did not see either signal")
        x,y,_,_=bounds
        return "offline-pixel-fixture",Decision.model_validate(dict(observation="看见亮色信号块",
            expectation_before_action="下一个海湾的灯号会变化", emotion=dict(mood="好奇",patience_delta=0,
            quit_urge_score=0,quit_reason=""),goal_update="前往下一座灯塔",action=dict(type="click",
            target_description="左侧亮色信号",x_norm=(x+12)/size[0],y_norm=(y+12)/size[1],end_x_norm=None,
            end_y_norm=None,text=None,key=None,wait_ms=0,reason="继续辨认下一个海湾"),
            experience_reflection=dict(notable_good="",friction_or_issue="",issue_category="无")))


def worker(params):
    index,steps,paid,output=params
    started=time.time()
    game,persona,settings=load("demo","explorer",{"default_model":os.getenv("PLAYTEST_MODEL"),
        "max_budget_usd":os.getenv("PLAYTEST_MAX_BUDGET_USD"),"reasoning_effort":os.getenv("PLAYTEST_REASONING_EFFORT"),
        "max_output_tokens":os.getenv("PLAYTEST_MAX_OUTPUT_TOKENS")})
    password=secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory() as temp, serve(persona.test_account,password) as origin:
        from urllib.parse import urlsplit
        game.url=origin
        game.allowed_hosts=[urlsplit(origin).netloc]
        folder=Path(output or temp)/f"worker-{index}"
        folder.mkdir(parents=True,exist_ok=False)
        state=Memory(run_id=f"demo-{index}",game_id=game.id,persona_id=persona.id,
                     account_alias=persona.account_alias,offline=not paid)
        key=os.getenv({"openai":"OPENAI_API_KEY","glm":"GLM_API_KEY","gemini":"GEMINI_API_KEY"}[settings.models[settings.default_model].provider],"")
        privacy=Privacy(key,password,persona.test_account)
        checkpoint=folder/"memory_checkpoint.json"
        for part in (1,2):
            if part==2:
                state=Memory.model_validate_json(checkpoint.read_bytes())
                if state.status!="PAUSED":
                    break
            reporter=Reporter(folder,state,persona,privacy)
            persist=lambda:save(checkpoint,state,privacy)
            ledger=Ledger(state,settings,persist)
            player=make_player(settings,persona,ledger,privacy,reporter.log,key) if paid else DemoVision(settings)
            reporter.log("run demo" if part==1 else "resume demo")
            try:
                with Browser(game,persona,state,persona.test_account,password,reporter.log) as browser:
                    browser.adapter.login(browser)
                    verify(state,browser.adapter.fingerprint,browser.adapter.revision)
                    state.version_fingerprint=browser.adapter.fingerprint
                    state.last_confirmed_server_revision=browser.adapter.revision
                    state.status=play(browser,player,reporter,persist,steps,max(1,steps//2) if part==1 else None)
            except StopRun as exc:
                state.status, state.detail = exc.status, str(exc)
                if not paid:
                    raise
            finally:
                if state.sessions:
                    state.sessions[-1]["end_status"]=state.status
                persist()
                reporter.finish()
        if not paid and (state.step_index!=steps or state.last_confirmed_server_revision!=steps or len(state.sessions)!=2):
            raise RuntimeError("Demo state did not survive reopening Chromium")
        return dict(worker=index,steps=state.step_index,start=started,end=time.time(),status=state.status,
                    calls=len(state.usage),cost_usd=str(state.spent_usd),revision=state.last_confirmed_server_revision,
                    browsers_opened=len(state.sessions),action_seconds=[r.elapsed_seconds for r in state.steps])


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--workers",type=int,choices=[1,2,5],default=1)
    p.add_argument("--steps",type=int,choices=range(2,51),default=4)
    p.add_argument("--metrics",type=Path,required=True)
    p.add_argument("--paid",action="store_true")
    p.add_argument("--output",type=Path)
    args=p.parse_args()
    if args.paid and (args.workers!=1 or os.getenv("GITHUB_ACTIONS")!="true" or os.getenv("RUNNER_OS")!="Linux"):
        p.error("Paid demo requires one hosted Linux job")
    start=time.monotonic()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows=list(pool.map(worker,[(i,args.steps,args.paid,args.output) for i in range(args.workers)]))
    seconds=time.monotonic()-start
    times=sorted(t for row in rows for t in row.pop("action_seconds"))
    report=dict(workers=len(rows),wall_seconds=round(seconds,3),steps=sum(r["steps"] for r in rows),
        overlap_seconds=max(0,min(r["end"] for r in rows)-max(r["start"] for r in rows)),
        p50_step_seconds=round(statistics.median(times),3) if times else None,
        p95_step_seconds=round(times[max(0,(95*len(times)+99)//100-1)],3) if times else None,results=rows)
    args.metrics.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="results"}))
    if args.paid and not all(r["steps"]>=1 and r["status"] in {"COMPLETED","NATURAL_QUIT"} for r in rows):
        raise SystemExit(1)


if __name__=="__main__":
    main()
