import argparse
import os
import re
import sys
from pathlib import Path

from .agent import play
from .browser import Browser
from .budget import Ledger
from .config import load
from .llm_client import Player
from .providers import make_player
from .memory import Memory, save, verify
from .offline import FixtureBrowser, fixture_client
from .reporter import Reporter
from .security import Privacy, StopRun, now


def main(argv=None):
    parser = argparse.ArgumentParser(description="云端 AI 游戏试玩")
    parser.add_argument("command", choices=["dry-run", "run", "resume"])
    parser.add_argument("--game", default="demo")
    parser.add_argument("--persona", default="explorer")
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID") or now().replace(":", "-"))
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--pause-at", type=int)
    parser.add_argument("--return-visit", action="store_true", help="重新登录并单独记录已自然退出玩家的后续回访")
    for flag in ("model", "reasoning-effort", "max-output-tokens", "max-budget-usd"):
        parser.add_argument("--"+flag, default=os.getenv("PLAYTEST_"+flag.replace("-", "_").upper()))
    args = parser.parse_args(argv)
    if not 1 <= args.steps <= 50 or not re.fullmatch(r"[A-Za-z0-9_.+-]{1,100}", args.run_id) or args.run_id in {".",".."}:
        parser.error("无效运行标识或步数")
    game, persona, settings = load(args.game, args.persona, dict(default_model=args.model,
        reasoning_effort=args.reasoning_effort, max_output_tokens=args.max_output_tokens, max_budget_usd=args.max_budget_usd))
    if args.command == "resume" and not args.resume:
        parser.error("resume 需要 --resume 指定检查点")
    offline = args.command == "dry-run"
    if args.resume:
        state = Memory.model_validate_json(args.resume.read_bytes())
        if (state.game_id, state.persona_id, state.account_alias) != (game.id, persona.id, persona.account_alias):
            parser.error("检查点与游戏、角色或账号不符")
        if offline and not state.offline:
            parser.error("正式检查点不能用于离线试玩")
        offline = state.offline
        folder = args.resume.parent
    else:
        state = Memory(run_id=args.run_id, game_id=game.id, persona_id=persona.id,
                       account_alias=persona.account_alias, patience=persona.initial_patience, offline=offline)
        folder = args.output / args.run_id
        folder.mkdir(parents=True, exist_ok=False)
    if not offline and (os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("RUNNER_OS") != "Linux"):
        parser.error("正式试玩仅在 GitHub Actions Linux Runner 运行")
    username, password, key = (os.getenv(name, "") for name in ("PLAYTEST_USERNAME","PLAYTEST_PASSWORD", {"openai":"OPENAI_API_KEY","glm":"GLM_API_KEY","gemini":"GEMINI_API_KEY"}[settings.models[settings.default_model].provider]))
    privacy = Privacy(username, password, key)
    reporter = Reporter(folder, state, persona, privacy)
    checkpoint = folder / "memory_checkpoint.json"

    def persist():
        save(checkpoint, state, privacy)

    reporter.log(f"{args.command} {game.id}/{persona.id} 步数={state.step_index} 已计费={state.spent_usd} 预留={state.reserved_usd}")
    try:
        if state.status in {"SAVE_ROLLBACK","SAVE_CONFLICT","SAVE_TAMPERED","ACCOUNT_MISMATCH","ACCOUNT_CHANGED","PRICE_BOUND_ERROR"}:
            raise StopRun(state.status, "账号已暂停，需要人工核对存档或费用")
        if state.pending_action is not None:
            raise StopRun("ACTION_UNCERTAIN", f"第 {state.pending_action} 步输入可能已送达，需核实现场")
        if not offline and not all((key, username, password)):
            raise StopRun("SECRETS_MISSING", "缺少正式试玩凭据")
        if args.return_visit:
            if not args.resume or state.status != "NATURAL_QUIT" or state.step_index >= args.steps:
                raise StopRun("INVALID_RETURN_VISIT")
            state.phase = "return_after_quit"
            state.grid_evidence = ""
            state.missed_clicks = 0
            reporter.log("独立回访，保留此前退出节点和累计费用")
        elif args.resume and state.status in {"COMPLETED","NATURAL_QUIT"} and not state.pending_return:
            return 0
        state.status, state.detail = "RUNNING", ""
        ledger = Ledger(state, settings, persist)
        player = (Player(settings, persona, ledger, privacy, reporter.log, fixture_client(state)) if offline
                  else make_player(settings, persona, ledger, privacy, reporter.log, key))
        instance = FixtureBrowser(game, state) if offline else Browser(game, persona, state, username, password, reporter.log)
        with instance as browser:
            try:
                browser.adapter.login(browser)
                verify(state, browser.adapter.fingerprint, browser.adapter.revision)
                state.version_fingerprint = browser.adapter.fingerprint
                state.last_confirmed_server_revision = browser.adapter.revision
                persist()
                state.status = play(browser, player, reporter, persist, args.steps, args.pause_at)
            except Exception:
                try:
                    path = f"screenshots/raw/fault_{state.step_index:03}.png"
                    (folder/path).write_bytes(browser.screenshot())
                    state.fault_screenshot = path
                except Exception:
                    pass  # login forms are never captured
                browser.check()
                raise
    except StopRun as exc:
        state.status, state.detail = exc.status, privacy.clean(str(exc))
    except KeyboardInterrupt:
        state.status, state.detail = "PAUSED", "进程中断"
    except Exception as exc:
        state.status, state.detail = "RUN_FAILED", type(exc).__name__
    finally:
        if state.sessions and state.sessions[-1]["end_status"] == "RUNNING":
            state.sessions[-1].update(end_status=state.status, pause_reason=state.detail, end_time=now())
        reporter.log(f"{state.status} {state.detail}")
        persist()
        reporter.finish()
        print(f"{state.status} steps={state.step_index} confirmed_usd={state.spent_usd} reserved_usd={state.reserved_usd}")
    return 0 if state.status in {"PAUSED","COMPLETED","BUDGET_EXHAUSTED","NATURAL_QUIT"} else 1


if __name__ == "__main__":
    sys.exit(main())
