from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


Coord = Annotated[float, Field(ge=0, le=1)]
Short = Annotated[str, Field(max_length=600)]
Status = Literal["major_transition", "modal_or_panel_change", "subtle_feedback",
                 "loading_or_animation", "no_visible_change", "runtime_error", "not_applicable"]


class Action(Strict):
    type: Literal["click", "double_click", "drag", "swipe", "scroll", "type_text", "wait",
                  "press_key", "back", "logout_reenter", "natural_quit", "request_grid"]
    target_description: Short
    x_norm: Coord | None
    y_norm: Coord | None
    end_x_norm: Coord | None
    end_y_norm: Coord | None
    text: Annotated[str, Field(max_length=80)] | None
    key: Literal["Enter", "Escape", "Backspace", "Space", "Tab", "ArrowUp", "ArrowDown",
                 "ArrowLeft", "ArrowRight"] | None
    wait_ms: Annotated[int, Field(ge=0, le=5000)]
    reason: Short

    @model_validator(mode="after")
    def check_input(self):
        if self.type in {"click", "double_click", "drag", "swipe", "scroll", "type_text"}:
            if self.x_norm is None or self.y_norm is None:
                raise ValueError("起点坐标缺失")
        if self.type in {"swipe", "drag", "scroll"} and None in (self.end_x_norm, self.end_y_norm):
            raise ValueError("终点坐标缺失，滚动方向由起点指向终点")
        if self.type == "press_key" and self.key is None:
            raise ValueError("按键缺失")
        if self.type == "type_text" and not self.text:
            raise ValueError("输入文字缺失")
        if self.type == "request_grid" and not self.target_description.strip():
            raise ValueError("申请网格需要已识别的画面目标")
        return self


class EmotionState(Strict):
    mood: Literal["好奇", "投入", "满足", "困惑", "烦躁", "疲惫", "挫败", "想退出"]
    patience_delta: Annotated[int, Field(ge=-10, le=10)]
    quit_urge_score: Annotated[int, Field(ge=0, le=10)]
    quit_reason: Short

    @model_validator(mode="after")
    def check_reason(self):
        if self.quit_urge_score >= 7 and not self.quit_reason.strip():
            raise ValueError("缺少退出意愿的理由")
        return self


class Reflection(Strict):
    notable_good: Short
    friction_or_issue: Short
    issue_category: Literal["新手引导", "序幕节奏", "阅读疲劳", "人物表现", "美术氛围", "经营深度", "交互定位", "异常", "无"]


class Decision(Strict):
    observation: Short
    expectation_before_action: Short
    emotion: EmotionState
    goal_update: Short
    action: Action
    experience_reflection: Reflection


class StepRecord(Strict):
    step: int
    timestamp: str
    phase: Literal["initial_play", "return_after_quit"]
    model: str
    grid: bool
    decision: Decision
    executed: str
    detector_status: Status
    before: str
    after: str
    elapsed_seconds: float
    revision: int | None
    patience: int
    attempt_evidence: str = ""
    animation_samples: list[str] = Field(default_factory=list)
    held_change_fraction: Coord | None = None


class Issue(Strict):
    number: int
    severity: str
    category: str
    step: int
    before: str
    after: str
    target: str
    expected: str
    observed: str
    impact: str
    suggestion: str
