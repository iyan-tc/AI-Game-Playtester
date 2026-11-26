"""Deterministic fixture for dry-run. Never opens a browser, socket or API key."""
import json
from io import BytesIO
from types import SimpleNamespace

import httpx
from openai import OpenAI
from PIL import Image, ImageDraw


class FixtureBrowser:
    size = (390, 844)
    fault = None

    def __init__(self, game, state):
        self.game, self.state = game, state
        self.adapter = self
        self.fingerprint = {"release_path": "offline-fixture", "sha256": "synthetic"}
        self.revision = state.last_confirmed_server_revision or 0
        self.reentries = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def login(self, browser):
        pass

    def reenter(self, browser):
        self.reentries += 1

    def check(self):
        pass

    def screenshot(self):
        image = Image.new("RGB", self.size, "#efe0b2")
        ImageDraw.Draw(image).text((40, 60), f"OFFLINE FIXTURE {self.revision}", fill="black")
        buf = BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    def pixel(self, x, y):
        return round(x*(self.size[0]-1)), round(y*(self.size[1]-1))

    def execute(self, action, before):
        if self.state.step_index < 2:
            return before, "no_visible_change"
        self.revision += 1
        return self.screenshot(), "subtle_feedback"


def fixture_client(state):
    def reply(req):
        if req.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object":"response.input_tokens", "input_tokens":1200})
        quit_now = state.step_index == 3
        data = dict(observation="看见合成测试画面", expectation_before_action="看到提示变化",
            emotion=dict(mood="想退出" if quit_now else "好奇", patience_delta=-1,
                         quit_urge_score=8 if quit_now else 1, quit_reason="合成场景重复" if quit_now else ""),
            goal_update="看看下一屏", action=dict(type="click", target_description="测试入口", x_norm=.2, y_norm=.2,
                end_x_norm=None, end_y_norm=None, text=None, key=None, wait_ms=0, reason="想看到下一页"),
            experience_reflection=dict(notable_good="", friction_or_issue="", issue_category="无"))
        return httpx.Response(200, json=dict(id="resp_fixture", object="response", created_at=0,
            status="completed", model="fixture", output=[dict(type="message", role="assistant", id="msg_fixture",
            status="completed", content=[dict(type="output_text", text=json.dumps(data, ensure_ascii=False), annotations=[])])],
            usage=dict(input_tokens=1200, input_tokens_details=dict(cached_tokens=100), output_tokens=300,
                       output_tokens_details=dict(reasoning_tokens=100), total_tokens=1500)))
    return OpenAI(api_key="offline-fixture", base_url="https://offline.invalid/v1", max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(reply)))

