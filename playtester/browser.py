from importlib import import_module
from time import monotonic
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import sync_playwright

from .detector import sample
from .security import StopRun, allowed
from .vision_assist import NullHotspotProvider


class Browser:
    def __init__(self, game, persona, state, username, password, log, hotspots=None):
        self.game, self.state, self.log = game, state, log
        self.adapter = import_module(game.adapter).Adapter(game, persona, username, password)
        self.hotspots = hotspots or NullHotspotProvider()
        self.size = game.viewport.width, game.viewport.height
        self.pending = set()
        self.writes = 0
        self.fault = None

    def __enter__(self):
        self.pw = sync_playwright().start()
        try:
            self.engine = self.pw.chromium.launch()
            self.context = self.engine.new_context(viewport=self.game.viewport.model_dump(),
                                                   service_workers="block", accept_downloads=False)
            self.context.route("**/*", self.route)
            self.context.route_web_socket("**/*", lambda ws: ws.close())
            self.page = self.context.new_page()
            self.page.set_default_timeout(15000)
            self.context.on("page", lambda popup: popup.close() if popup != self.page else None)
            self.page.on("pageerror", lambda error: self.fail("RUNTIME_ERROR", str(error)))
            self.page.on("console", lambda msg: self.fail("CONSOLE_ERROR", msg.text) if msg.type == "error" else None)
            return self
        except BaseException:
            self.pw.stop()
            raise

    def __exit__(self, *_):
        try:
            self.context.close()
        finally:
            self.pw.stop()

    def fail(self, status, detail):
        if self.fault is None:
            self.fault = StopRun(status, detail)
            self.log(f"{status} {detail}")

    def check(self):
        if self.fault:
            raise self.fault

    def route(self, route):
        req = route.request
        path = urlsplit(req.url).path
        writing = req.method not in {"GET", "HEAD", "OPTIONS"}
        if not allowed(req.url, self.game.allowed_hosts) or (writing and
                (self.fault or not self.adapter.permits_write(path, req.method))):
            self.log("已阻止未授权请求")
            route.abort()
            return
        started = monotonic()
        self.pending.add(req)
        response = None
        try:
            # Inspect each Location before Chromium can follow it, including redirects
            # that Playwright would otherwise automatically follow inside route.fetch.
            response = route.fetch(max_redirects=0, timeout=30000)
            location = response.headers.get("location")
            if location and not allowed(urljoin(req.url, location), self.game.allowed_hosts):
                raise StopRun("BLOCKED_REDIRECT")
            if (writing or path.startswith("/api/")) and response.status >= 400:
                try:
                    code = response.json().get("code")
                except (AttributeError, ValueError):
                    code = None
                status = code if code in {"SAVE_CONFLICT", "SAVE_TAMPERED", "ACCOUNT_CHANGED"} else "API_HTTP_ERROR"
                raise StopRun(status, f"{req.method} {path} HTTP {response.status} {status}")
            if response.ok:
                self.adapter.observed(self, path, response)
                if writing and self.adapter.authorized:
                    self.writes += 1
            if writing or path.startswith("/api/"):
                self.log(f"{req.method} {path} {response.status} {monotonic()-started:.3f}s")
            route.fulfill(response=response)
        except Exception as exc:
            self.fail(exc.status if isinstance(exc, StopRun) else "NETWORK_ERROR",
                      str(exc) if isinstance(exc, StopRun) else type(exc).__name__)
            route.abort()
        finally:
            self.pending.discard(req)
            if response is not None:
                response.dispose()

    def screenshot(self):
        if not self.adapter.safe_capture or not allowed(self.page.url, self.game.allowed_hosts):
            raise StopRun("UNSAFE_SCREEN", "当前画面未通过会话核验")
        if self.page.locator("input[type=password]:visible").count():
            raise StopRun("UNSAFE_SCREEN", "登录画面禁止截图")
        return self.page.screenshot(type="png", mask=self.adapter.private_regions(self.page))

    def pixel(self, x, y):
        return tuple(min(s-1, round(v*s)) for v, s in zip((x, y), self.size))

    def execute(self, a, before):
        self.check()
        mouse, keyboard = self.page.mouse, self.page.keyboard
        point = self.pixel(a.x_norm, a.y_norm) if a.x_norm is not None and a.y_norm is not None else None
        previous_writes = self.writes
        if a.type in {"click", "double_click", "type_text"}:
            mouse.move(*point, steps=4)
            self.page.wait_for_timeout(90)
            mouse.click(*point, click_count=2 if a.type == "double_click" else 1, delay=65)
            if a.type == "type_text":
                keyboard.insert_text(a.text)
        elif a.type in {"drag", "swipe", "scroll"}:
            end = self.pixel(a.end_x_norm, a.end_y_norm)
            mouse.move(*point)
            if a.type == "scroll":
                mouse.wheel(end[0]-point[0], end[1]-point[1])
            else:
                mouse.down()
                try:
                    mouse.move(*end, steps=14)
                finally:
                    mouse.up()
        elif a.type == "press_key":
            keyboard.press(a.key)
        elif a.type == "wait":
            self.page.wait_for_timeout(a.wait_ms)
        elif a.type == "back":
            self.page.go_back(wait_until="domcontentloaded")
        elif a.type == "logout_reenter":
            self.adapter.reenter(self)
        else:
            raise ValueError("无浏览器输入的决策应由试玩循环处理")
        return sample(self, before, point, previous_writes)
