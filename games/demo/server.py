"""Loopback-only sample game for hosted integration tests and the live demo."""
import hashlib
import hmac
import json
import secrets
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import parse_qs

JS = Path(__file__).with_name("game.js").read_bytes().replace(b"\r\n", b"\n")
FINGERPRINT = hashlib.sha256(JS).hexdigest()
FORM = b'<form action="/login" method="post"><input name="user"><input type="password" name="password"><button>Enter</button></form>'
GAME = b"""<meta name="viewport" content="width=device-width,initial-scale=1"><style>*{box-sizing:border-box}body{margin:0;background:#152b42}canvas{width:100vw;height:100vh;display:block}form{position:absolute;top:0;right:8px}button{padding:6px}</style><canvas width="390" height="640"></canvas><form method="post" action="/logout"><button>Leave coast</button></form><script src="/game.js"></script>"""


@contextmanager
def serve(username, password, port=0):
    sessions = set()
    lock = Lock()
    revision = 0

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, data=b"", mime="text/html", **headers):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            for key,value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def cookie(self):
            cookies = SimpleCookie(self.headers.get("Cookie",""))
            return cookies["demo_session"].value if "demo_session" in cookies else ""

        def do_GET(self):
            if self.path == "/favicon.ico":
                return self.reply(204)
            if self.path == "/login":
                return self.reply(200,FORM)
            if self.cookie() not in sessions:
                return self.reply(302,Location="/login")
            if self.path == "/":
                return self.reply(200,GAME)
            if self.path == "/game.js":
                return self.reply(200,JS,"application/javascript")
            if self.path == "/session":
                return self.reply(200,json.dumps(dict(revision=revision)).encode(),"application/json")
            self.reply(404)

        def do_POST(self):
            nonlocal revision
            body = self.rfile.read(min(int(self.headers.get("Content-Length",0)),4096))
            if self.path == "/login":
                fields = parse_qs(body.decode())
                if fields.get("user") != [username] or not hmac.compare_digest(fields.get("password",[""])[0],password):
                    return self.reply(403)
                token=secrets.token_urlsafe()
                sessions.add(token)
                return self.reply(303, Location="/", **{"Set-Cookie":f"demo_session={token}; HttpOnly; SameSite=Strict; Path=/"})
            if self.cookie() not in sessions:
                return self.reply(403)
            if self.path == "/logout":
                sessions.discard(self.cookie())
                return self.reply(303,Location="/login")
            if self.path == "/signal":
                with lock:
                    if json.loads(body)["revision"] != revision:
                        return self.reply(409,b'{"code":"SAVE_CONFLICT"}',"application/json")
                    revision+=1
                    return self.reply(200,json.dumps(dict(revision=revision)).encode(),"application/json")
            self.reply(404)
    server = ThreadingHTTPServer(("127.0.0.1",port),Handler)
    worker = Thread(target=server.serve_forever,daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()

