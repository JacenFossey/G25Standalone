"""Per-user settings, logging and process control; no wheel hardware access."""

from __future__ import annotations

import errno
import json
import logging
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from g25_windows import SessionNotifications

LOG = logging.getLogger("g25")
DEFAULT_RANGE = 900
MIN_RANGE = 40
MAX_RANGE = 900
CONTROL_TIMEOUT = 1.0
PROCESS_TIMEOUT = 10.0


class AlreadyRunning(RuntimeError):
    pass


def data_directory() -> Path:
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "G25Standalone"
    # Non-Windows support is for runtime tests, not physical-wheel support.
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "G25Standalone"


def validate_range(value: int) -> int:
    if type(value) is not int or not MIN_RANGE <= value <= MAX_RANGE:
        raise ValueError(f"steering range must be an integer from {MIN_RANGE} to {MAX_RANGE}")
    return value


def write_json(path: Path, value: dict) -> None:
    """Replace a complete file atomically, including when multiple clients write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_settings(root: Path) -> dict:
    try:
        settings = json.loads((root / "settings.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "steering_range": DEFAULT_RANGE}
    except (ValueError, UnicodeError) as exc:
        raise ValueError("settings.json is invalid; correct it before starting") from exc
    if not isinstance(settings, dict) or settings.get("version") != 1:
        raise ValueError("settings.json has an unsupported format")
    validate_range(settings.get("steering_range"))
    return settings


def save_range(root: Path, value: int) -> dict:
    validate_range(value)
    settings = load_settings(root)
    settings["steering_range"] = value
    write_json(root / "settings.json", settings)
    return settings


class InstanceLock:
    """An OS-owned lock, released automatically even after process termination.

    The lock file is deliberately never removed: deleting it would let a new
    process lock a different file while the old instance still owns its lock.
    """

    def __init__(self, root: Path):
        self.path = root / "runtime.lock"
        self.stream = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise AlreadyRunning("G25Standalone is already running") from exc
            raise
        self.stream = stream

    def release(self) -> None:
        if self.stream is not None:
            # Closing the handle also releases its byte/flock lock.
            self.stream.close()
            self.stream = None


def configure_logging(root: Path, background: bool) -> None:
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    for handler in list(LOG.handlers):
        LOG.removeHandler(handler)
        handler.close()
    handler = RotatingFileHandler(
        log_dir / "g25.log", maxBytes=1_048_576, backupCount=3, encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    LOG.addHandler(handler)
    if not background and sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        LOG.addHandler(console)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False


def close_logging() -> None:
    for handler in list(LOG.handlers):
        LOG.removeHandler(handler)
        handler.close()


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(CONTROL_TIMEOUT)
        return connection, address


class Runtime:
    def __init__(self, root: Path, steering_range: int, background: bool = False):
        self.root = root
        self.lock = InstanceLock(root)
        self.steering_range = validate_range(steering_range)
        self.background = background
        self.stop_event = threading.Event()
        self.stopped_event = threading.Event()
        self.token = secrets.token_hex(32)
        self.started_at = time.monotonic()
        self._state_lock = threading.Lock()
        self._state = {"state": "starting", "wheel": "unknown"}
        self._server = None
        self._thread = None
        self._notifications = None
        self._signals = {}
        self._published = False
        self._owns_lock = False
        self._signal_received = None

    def update(self, **values) -> None:
        with self._state_lock:
            self._state.update(values)

    def status(self) -> dict:
        with self._state_lock:
            state = dict(self._state)
        return {
            "running": True,
            "pid": os.getpid(),
            "steering_range": self.steering_range,
            "uptime_seconds": round(time.monotonic() - self.started_at, 2),
            "log_file": str(self.root / "logs/g25.log"),
            **state,
        }

    def request_stop(self, reason: str = "control command") -> None:
        if not self.stop_event.is_set():
            LOG.info("Stopping: %s", reason)
            self.update(state="stopping")
        self.stop_event.set()

    def should_stop(self) -> bool:
        if self._signal_received is not None:
            number = self._signal_received
            self._signal_received = None
            self.request_stop(f"signal {number}")
        return self.stop_event.is_set()

    def _signal_handler(self, number, _frame) -> None:
        # A Python signal can interrupt logging/state updates on the main
        # thread. Do not acquire their locks inside the signal handler.
        self._signal_received = number

    def __enter__(self):
        self.lock.acquire()
        self._owns_lock = True
        try:
            configure_logging(self.root, self.background)
            runtime = self

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *_args):
                    pass

                def respond(self, code, value):
                    body = json.dumps(value).encode("utf-8")
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def authorized(self):
                    supplied = self.headers.get("Authorization", "")
                    return secrets.compare_digest(supplied, "Bearer " + runtime.token)

                def do_GET(self):
                    if not self.authorized():
                        self.respond(403, {"error": "unauthorized"})
                    elif self.path == "/status":
                        self.respond(200, runtime.status())
                    else:
                        self.respond(404, {"error": "unknown command"})

                def do_POST(self):
                    if not self.authorized():
                        self.respond(403, {"error": "unauthorized"})
                    elif self.path == "/stop":
                        runtime.request_stop()
                        self.respond(200, {"state": "stopping"})
                    else:
                        self.respond(404, {"error": "unknown command"})

            self._server = ControlServer(("127.0.0.1", 0), Handler)
            self._thread = threading.Thread(
                target=lambda: self._server.serve_forever(poll_interval=0.05), daemon=True
            )
            self._thread.start()
            self._notifications = SessionNotifications(self.request_stop, self.stopped_event)
            self._notifications.start()
            if threading.current_thread() is threading.main_thread():
                for signum in (signal.SIGINT, signal.SIGTERM):
                    self._signals[signum] = signal.getsignal(signum)
                    signal.signal(signum, self._signal_handler)
            write_json(self.root / "runtime.json", {
                "pid": os.getpid(), "port": self._server.server_port, "token": self.token
            })
            self._published = True
            LOG.info("G25Standalone starting; steering range %s degrees", self.steering_range)
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, exc_type, exc, _traceback):
        if exc is not None:
            LOG.error("Runtime failed", exc_info=(exc_type, exc, _traceback))
        self.close()

    def close(self) -> None:
        # The caller exits this context only after closing/neutralizing hardware.
        self.stopped_event.set()
        if self._notifications is not None:
            self._notifications.close()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        for signum, handler in self._signals.items():
            signal.signal(signum, handler)
        self._signals.clear()
        if self._published:
            (self.root / "runtime.json").unlink(missing_ok=True)
            self._published = False
        if self._owns_lock:
            LOG.info("G25Standalone stopped")
            close_logging()
            self.lock.release()
            self._owns_lock = False


def read_endpoint(root: Path) -> dict | None:
    try:
        value = json.loads((root / "runtime.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    if (not isinstance(value, dict)
            or type(value.get("port")) is not int or not 1 <= value["port"] <= 65535
            or type(value.get("pid")) is not int
            or not isinstance(value.get("token"), str) or len(value["token"]) != 64):
        return None
    return value


def control_request(endpoint: dict, command: str) -> dict:
    request = Request(
        f"http://127.0.0.1:{endpoint['port']}/{command}",
        headers={"Authorization": "Bearer " + endpoint["token"]},
        method="POST" if command == "stop" else "GET",
    )
    # Local control must work even when the user's environment configures a proxy.
    with build_opener(ProxyHandler({})).open(request, timeout=CONTROL_TIMEOUT) as response:
        result = json.loads(response.read(16_384))
    if not isinstance(result, dict):
        raise ValueError("invalid runtime response")
    return result


def query_status(root: Path) -> dict | None:
    endpoint = read_endpoint(root)
    if endpoint is None:
        return None
    try:
        status = control_request(endpoint, "status")
    except (OSError, URLError, ValueError):
        return None
    return status if status.get("pid") == endpoint["pid"] else None


def stop_process(root: Path, timeout: float = PROCESS_TIMEOUT) -> None:
    endpoint = read_endpoint(root)
    if endpoint is None or query_status(root) is None:
        # A stale endpoint never authorizes killing a PID, which may be reused.
        probe = InstanceLock(root)
        try:
            probe.acquire()
        except AlreadyRunning as exc:
            raise RuntimeError("runtime is starting or unresponsive; cannot confirm a clean stop") from exc
        else:
            probe.release()
            return
    control_request(endpoint, "stop")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        probe = InstanceLock(root)
        try:
            probe.acquire()
        except AlreadyRunning:
            time.sleep(0.05)
        else:
            probe.release()
            return
    raise TimeoutError("runtime did not stop cleanly; it has not been force-terminated")


def launch_background(root: Path, steering_range: int | None = None) -> dict:
    status = query_status(root)
    if status is not None:
        return status
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(sys.argv[0]).resolve()))
    command.extend(["run", "--background", "--data-dir", str(root)])
    if steering_range is not None:
        command.extend(["--range", str(steering_range)])
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    if getattr(sys, "frozen", False):
        # This is an independent application, not a PyInstaller worker. It must
        # remain alive after the short-lived `start` command has exited.
        options["env"] = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    child = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, **options
    )
    deadline = time.monotonic() + PROCESS_TIMEOUT
    while time.monotonic() < deadline:
        status = query_status(root)
        if status is not None and status["state"] != "starting":
            return status
        if child.poll() is not None:
            # Two simultaneous starts can race; the winner is still usable.
            status = query_status(root)
            if status is not None:
                return status
            raise RuntimeError(f"background startup failed; see {root / 'logs/g25.log'}")
        time.sleep(0.05)
    raise TimeoutError(f"startup has not completed; use status or stop; see {root / 'logs/g25.log'}")
