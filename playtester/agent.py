from time import monotonic

from .models import Issue, StepRecord
from .security import StopRun, now
from .vision_assist import evidence, grid


def add_issue(state, step, severity, category, observed, impact, suggestion):
    state.discovered_issues.append(Issue(number=len(state.discovered_issues)+1, severity=severity,
        category=category, step=step.step, before=step.before, after=step.after,
        target=step.decision.action.target_description, expected=step.decision.expectation_before_action,
        observed=observed, impact=impact, suggestion=suggestion))


def play(browser, player, reporter, persist, target, pause_at=None):
    state, folder = reporter.state, reporter.folder
    persona = reporter.persona
    session = None
    try:
        while state.step_index < target:
            if state.pending_return:
                # Check remaining funds before causing a real logout. The next generation
                # still goes through the full image-specific preflight.
                if state.spent_usd + state.reserved_usd >= player.settings.max_budget_usd:
                    raise StopRun("BUDGET_EXHAUSTED")
                browser.adapter.reenter(browser)
                state.phase = "return_after_quit"
                state.pending_return = False
                state.grid_evidence = ""
                state.missed_clicks = 0
                persist()
                session = None
            if session is None:
                session = dict(run_id=state.run_id, phase=state.phase, persona=persona.name,
                               account=persona.account_alias, start_time=now(), end_time=now(), active_seconds=0,
                               steps=0, start_revision=browser.adapter.revision, end_revision=browser.adapter.revision,
                               pause_reason="", end_status="RUNNING")
                state.sessions.append(session)
            browser.check()
            number = state.step_index + 1
            stem = f"screenshots/raw/step_{number:03}"
            before_path, after_path = stem + "_before.png", stem + "_after.png"
            started, timestamp = monotonic(), now()
            before = browser.screenshot()
            (folder / before_path).write_bytes(before)
            assisted = bool(state.grid_evidence)
            frame = before
            if assisted:
                frame = grid(before)
                (folder / f"screenshots/assist/step_{number:03}_grid.png").write_bytes(frame)
            model, decision = player.decide(state, frame, browser.size)
            browser.check()
            action, emotion = decision.action, decision.emotion
            quitting = action.type == "natural_quit" or emotion.quit_urge_score >= persona.quit_threshold
            executed = "natural_quit" if quitting else action.type
            state.pending_action = number
            persist()
            if executed in {"natural_quit", "request_grid"}:
                after, status = before, "not_applicable"
            else:
                after, status = browser.execute(action, before)
            (folder / after_path).write_bytes(after)
            record = StepRecord(step=number, timestamp=timestamp, phase=state.phase, model=model, grid=assisted,
                decision=decision, executed=executed, detector_status=status, before=before_path, after=after_path,
                elapsed_seconds=monotonic()-started, revision=browser.adapter.revision,
                patience=max(0, min(10, state.patience+emotion.patience_delta)))
            missed = executed in {"click", "double_click"} and status == "no_visible_change"
            state.missed_clicks = state.missed_clicks + 1 if missed else 0
            if status in {"subtle_feedback", "major_transition", "modal_or_panel_change"}:
                state.grid_evidence = ""
            if action.target_description.strip() and (state.missed_clicks >= 2 or executed == "request_grid"):
                previous = record if missed else next((r for r in reversed(state.steps) if
                            r.executed in {"click", "double_click"} and r.detector_status == "no_visible_change"), None)
                point = browser.pixel(previous.decision.action.x_norm, previous.decision.action.y_norm) if previous else None
                source = previous.before if previous else before_path
                state.grid_evidence = evidence(folder, number, (folder / source).read_bytes(), point, action.reason, source)
                record.attempt_evidence = state.grid_evidence
                add_issue(state, record, "P2", "交互定位", action.reason, "需要坐标辅助定位目标",
                          "核对目标热区与画面可见边界。证据 " + state.grid_evidence + "_point.png")
            reflection = decision.experience_reflection
            if reflection.friction_or_issue:
                add_issue(state, record, "P2", reflection.issue_category, reflection.friction_or_issue,
                          emotion.quit_reason or decision.goal_update, f"复核「{action.target_description}」的提示与可见反馈")
            state.remember(record)
            state.pending_action = None
            reporter.log(f"步骤 {number} {executed} {status} revision={record.revision}")
            session.update(end_time=now(), active_seconds=session["active_seconds"]+record.elapsed_seconds,
                           steps=session["steps"]+1, end_revision=record.revision)
            if quitting:
                state.natural_quit_events.append(dict(step=number, phase=state.phase, screen=before_path,
                    seconds=state.active_play_seconds, reason=emotion.quit_reason or action.reason, mood=emotion.mood))
                state.pending_return = number < target and state.phase == "initial_play"
                session.update(end_status="NATURAL_QUIT", pause_reason=emotion.quit_reason or action.reason)
            persist()
            browser.check()
            if quitting and not state.pending_return:
                return "NATURAL_QUIT"
            if pause_at == number and number < target:
                return "PAUSED"
        return "COMPLETED"
    finally:
        if session:
            session["end_time"] = now()

