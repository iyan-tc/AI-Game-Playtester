from decimal import Decimal
from typing import Literal

from pydantic import Field

from .models import Issue, StepRecord, Strict
from .security import StopRun, atomic, dump


class Memory(Strict):
    run_id: str
    game_id: str
    persona_id: str
    account_alias: str
    version_fingerprint: dict = Field(default_factory=dict)
    step_index: int = 0
    phase: Literal["initial_play", "return_after_quit"] = "initial_play"
    active_play_seconds: float = 0
    spent_usd: Decimal = Field(default=Decimal(0), ge=0)
    reserved_usd: Decimal = Field(default=Decimal(0), ge=0)
    last_confirmed_server_revision: int | None = None
    rolling_summary: str = Field(default="", max_length=600)
    recent_steps: list[dict] = Field(default_factory=list, max_length=8)
    current_goal: str = ""
    patience: int = 10
    emotion_history: list[dict] = Field(default_factory=list)
    natural_quit_events: list[dict] = Field(default_factory=list)
    discovered_issues: list[Issue] = Field(default_factory=list)
    steps: list[StepRecord] = Field(default_factory=list)
    usage: list[dict] = Field(default_factory=list)
    sessions: list[dict] = Field(default_factory=list)
    status: str = "READY"
    detail: str = ""
    grid_evidence: str = ""
    missed_clicks: int = 0
    pending_return: bool = False
    pending_action: int | None = None
    fault_screenshot: str = ""
    offline: bool = False

    def remember(self, step):
        self.steps.append(step)
        self.step_index = step.step
        self.active_play_seconds += step.elapsed_seconds
        self.patience = step.patience
        decision = step.decision
        self.current_goal = decision.goal_update
        note = dict(step=step.step, goal=self.current_goal, action=step.executed,
                    feeling=decision.emotion.mood, screen=decision.observation[:120], result=step.detector_status)
        self.recent_steps = (self.recent_steps + [note])[-8:]
        self.rolling_summary = (self.rolling_summary + f"\n{step.step}. {note['screen']}；{self.current_goal}；"
                                f"{note['feeling']}，{note['result']}")[-600:]
        self.emotion_history.append(dict(step=step.step, **decision.emotion.model_dump()))
        self.last_confirmed_server_revision = step.revision

    def model_memory(self):
        return dict(phase=self.phase, goal=self.current_goal, patience=self.patience,
                    summary=self.rolling_summary, recent=self.recent_steps,
                    last_quit=self.natural_quit_events[-1]["reason"] if self.natural_quit_events else "")


def save(path, state, privacy):
    atomic(path, dump(privacy.tree(state.model_dump(mode="json"))))


def verify(state, fingerprint, revision):
    if state.version_fingerprint and state.version_fingerprint != fingerprint:
        raise StopRun("VERSION_MISMATCH", "检查点指纹与实际加载版本不同")
    if type(revision) is not int or revision < 0:
        raise StopRun("REVISION_UNKNOWN", "未确认服务器 revision")
    previous = state.last_confirmed_server_revision
    if previous is None and revision != 0:
        raise StopRun("ACCOUNT_NOT_EMPTY", "首轮需要零历史云档")
    if previous is not None and revision < previous:
        raise StopRun("SAVE_ROLLBACK", f"云档 revision 从 {previous} 回退至 {revision}")

