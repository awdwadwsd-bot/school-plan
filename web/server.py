"""Lokaler Webserver und read-only Adapter für pylanis."""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import threading
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
SESSIONS: dict[str, tuple[object, dict]] = {}
SESSION_LOCK = threading.Lock()


def plain(value):
    if is_dataclass(value):
        return {key: plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "__dict__"):
        return {key: plain(item) for key, item in vars(value).items() if not key.startswith("_")}
    return value


def list_items(value, possible_keys):
    value = plain(value)
    if isinstance(value, dict):
        for key in possible_keys:
            if isinstance(value.get(key), list):
                return value[key]
        return [value]
    return value if isinstance(value, list) else []


def fetch_all(client):
    from datetime import date, timedelta
    requests = {
        "timetable": (client.get_timetable, ("entries", "lessons", "items")),
        "tasks": (client.get_tasks, ("tasks", "entries", "items")),
        "substitutions": (client.get_substitution_plan, ("substitutions", "entries", "items")),
        "calendar": (lambda: client.get_calendar(date.today(), date.today() + timedelta(days=60)), ("events", "entries", "items")),
    }
    result, errors = {}, {}
    for key, (getter, fields) in requests.items():
        try:
            result[key] = list_items(getter(), fields)
        except Exception as error:
            result[key] = []
            errors[key] = str(error)
    if errors:
        result["errors"] = errors
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "LernZeit/1.0"

    def log_message(self, fmt, *args):
        print("[LernZeit] " + fmt % args)

    def send_json(self, status, data):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        sid = getattr(self, "_new_session_cookie", None)
        if sid:
            cookie = f"lz_session={sid}; Path=/; HttpOnly; SameSite=Lax"
            if os.environ.get("RENDER"):
                cookie += "; Secure"
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(raw)

    def session_id(self, create=False):
        sid = next((part.strip().split("=", 1)[1] for part in self.headers.get("Cookie", "").split(";") if part.strip().startswith("lz_session=")), None)
        if sid and len(sid) == 43:
            return sid
        if not create:
            return None
        sid = secrets.token_urlsafe(32)
        self._new_session_cookie = sid
        return sid

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/data":
            sid = self.session_id()
            if not sid:
                return self.send_json(401, {"error": "Nicht verbunden"})
            with SESSION_LOCK:
                session = SESSIONS.get(sid)
                if session:
                    try:
                        fresh = fetch_all(session[0])
                        session = (session[0], fresh)
                        SESSIONS[sid] = session
                    except Exception:
                        pass
            return self.send_json(200 if session else 401, session[1] if session else {"error": "Nicht verbunden"})
        relative = "index.html" if path == "/" else path.lstrip("/")
        candidate = (ROOT / relative).resolve()
        if ROOT not in candidate.parents and candidate != ROOT / "index.html":
            return self.send_json(404, {"error": "Nicht gefunden"})
        if not candidate.is_file():
            return self.send_json(404, {"error": "Nicht gefunden"})
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") or "javascript" in content_type else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urlparse(self.path).path
        sid = self.session_id(create=True)
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return self.send_json(415, {"error": "JSON wird erwartet"})
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.send_json(400, {"error": "Ungültige Anfrage"})
        if path == "/api/logout":
            with SESSION_LOCK:
                SESSIONS.pop(sid, None)
            return self.send_json(200, {"ok": True})
        if path != "/api/login":
            return self.send_json(404, {"error": "Nicht gefunden"})
        if not all(body.get(key) for key in ("school_id", "username", "password")):
            return self.send_json(400, {"error": "Schul-ID, Benutzername und Passwort werden benötigt."})
        try:
            from pylanis import Lanis
            candidate = Lanis(school_id=str(body["school_id"]).strip(), username=str(body["username"]).strip(), password=str(body["password"]))
            fresh = fetch_all(candidate)
            with SESSION_LOCK:
                SESSIONS[sid] = (candidate, fresh)
            return self.send_json(200, {"data": fresh})
        except ImportError:
            return self.send_json(503, {"error": "pylanis fehlt. Bitte die Pakete aus requirements.txt installieren."})
        except Exception as error:
            print(f"[LernZeit] Portal login failed: {type(error).__name__}")
            return self.send_json(401, {"error": "Anmeldung oder Datenabruf fehlgeschlagen. Prüfe Schul-ID und Zugangsdaten."})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    address = ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1", port)
    print(f"LernZeit läuft auf Port {address[1]}")
    print("Zum Beenden Strg+C drücken.")
    ThreadingHTTPServer(address, Handler).serve_forever()

