import hashlib
from urllib.parse import urlsplit

from playtester.memory import verify
from playtester.security import StopRun


class Adapter:
    def __init__(self, game, persona, username, password):
        if username != persona.test_account or not password:
            raise StopRun("ACCOUNT_MISMATCH")
        self.username, self.password, self.game = username, password, game
        self.authenticating = self.authorized = self.safe_capture = False
        self.fingerprint = {}
        self.revision = None

    def permits_write(self, path, method):
        if method != "POST":
            return False
        return self.authenticating if path in {"/login","/logout"} else self.authorized and path == "/signal"

    def observed(self, browser, path, response):
        if path == self.game.release_path:
            actual = hashlib.sha256(response.body()).hexdigest()
            if actual != self.game.sha256:
                raise StopRun("VERSION_MISMATCH")
            self.fingerprint = dict(release_path=path,sha256=actual)
        elif path in {"/session","/signal"}:
            rev = response.json()["revision"]
            if path == "/session":
                self.safe_capture = bool(self.fingerprint)
                verify(browser.state,self.fingerprint,rev)
                self.authorized = self.safe_capture
            self.revision = rev

    def login(self, browser):
        page = browser.page
        self.authenticating = True
        try:
            page.goto(self.game.url)
            page.locator("input[name=user]").fill(self.username)
            page.locator("input[type=password]").fill(self.password)
            page.get_by_role("button",name="Enter").click()
            page.locator("canvas").wait_for()
            for _ in range(100):
                browser.check()
                if self.authorized:
                    return
                page.wait_for_timeout(50)
            raise StopRun("SESSION_UNVERIFIED")
        finally:
            self.authenticating = False

    def reenter(self,browser):
        self.authenticating = True
        try:
            browser.page.get_by_role("button",name="Leave coast").click()
            browser.page.wait_for_url(lambda url:urlsplit(url).path=="/login")
            self.authorized = self.safe_capture = False
            self.login(browser)
        finally:
            self.authenticating = False

    def private_regions(self,page):
        return [page.locator("input")]

