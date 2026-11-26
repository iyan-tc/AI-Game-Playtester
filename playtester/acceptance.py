import argparse
import json
from pathlib import Path

from .memory import Memory


def inspect(folder, live):
    s = Memory.model_validate_json((folder/"memory_checkpoint.json").read_bytes())
    expected = ["试玩结论.md","问题与证据.md","玩家体验日记.md","实玩时段与角色记录.csv","action_trace.jsonl",
                "usage_and_cost.csv","memory_checkpoint.json","screenshots/raw","screenshots/assist","logs/run.log"]
    aimed = [r for r in s.steps if r.executed in {"click","double_click","scroll","drag","swipe","type_text"}
             and r.decision.action.target_description.strip()]
    hits = sum(r.detector_status in {"major_transition","modal_or_panel_change","subtle_feedback"} for r in aimed)
    log = (folder/"logs/run.log").read_text(encoding="utf-8")
    checks = dict(mode=s.offline != live, artifacts=all((folder/i).exists() for i in expected),
                  steps=s.step_index >= 50 and len(s.steps)==s.step_index,
                  evidence=all((folder/r.before).is_file() and (folder/r.after).is_file() for r in s.steps),
                  grid=all(not r.grid or any(p.attempt_evidence and p.step < r.step for p in s.steps) for r in s.steps),
                  accuracy=bool(aimed) and hits/len(aimed)>=.95,
                  resume="resume " in log and len(s.sessions)>=2,
                  budget=0 < s.spent_usd <= 1 and s.reserved_usd==0,
                  version=bool(s.version_fingerprint) and (not live or s.version_fingerprint["release_path"]!="offline-fixture"),
                  initial_revision=bool(s.sessions) and s.sessions[0]["start_revision"]==0)
    return checks


def main():
    p = argparse.ArgumentParser()
    p.add_argument("path", type=Path)
    p.add_argument("--mode", choices=["live","offline"], required=True)
    args = p.parse_args()
    matched = list(args.path.rglob("memory_checkpoint.json"))
    if len(matched) != 1:
        raise SystemExit("需要一份运行检查点")
    checks = inspect(matched[0].parent, args.mode == "live")
    print(json.dumps(checks))
    return int(not all(checks.values()))


if __name__ == "__main__":
    raise SystemExit(main())

