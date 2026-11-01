"""Windowless packaged entry point and installer lifecycle commands."""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys

from g25_runtime import WindowsRuntime, state_directory, stop_running
from g25_session import SessionShutdown

LOG = logging.getLogger('g25')


def load_settings(path: Path) -> int:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation avoids overwriting an editor/another launcher.
        try:
            with path.open('x', encoding='utf-8') as stream:
                json.dump({'range_degrees': 900}, stream, indent=2)
                stream.write('\n')
        except FileExistsError:
            pass
    try:
        settings = json.loads(path.read_text(encoding='utf-8-sig'))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f'Invalid settings in {path}: {exc}') from exc
    if not isinstance(settings, dict):
        raise ValueError(f'{path} must contain a JSON object.')
    degrees = settings.get('range_degrees')
    if type(degrees) is not int or not 40 <= degrees <= 900:
        raise ValueError(f'range_degrees in {path} must be an integer from 40 to 900.')
    return degrees


class LogStream:
    """Capture the service's console messages without a console window."""
    def __init__(self, level: int):
        self.level = level
        self.pending = ''

    def write(self, text: str) -> int:
        self.pending += text
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            if line.strip():
                LOG.log(self.level, line)
        return len(text)

    def flush(self) -> None:
        if self.pending.strip():
            LOG.log(self.level, self.pending)
        self.pending = ''


class SafeRotatingFileHandler(RotatingFileHandler):
    def handleError(self, record) -> None:
        # stderr is redirected into this logger. The default implementation
        # writes back to stderr, recursively logging the same disk/rotation
        # failure until it raises and can interrupt wheel cleanup.
        # Logging is best-effort; hardware safety must never depend on it.
        pass


def configure_logging(folder: Path, *, control: bool = False) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    handler = SafeRotatingFileHandler(folder / ('control.log' if control else 'service.log'),
                                     maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    sys.stdout = LogStream(logging.INFO)
    sys.stderr = LogStream(logging.ERROR)


def run_service(argv: list[str], *, stop_requested) -> int:
    # Import lazily: --stop/registration/settings never initialize hidapi.
    from g25_service import main
    return main(argv, stop_requested=stop_requested)


def start_background(folder: Path) -> int:
    runtime = WindowsRuntime(folder)
    session = None
    try:
        if not runtime.acquire():
            LOG.info('Already running; ignored duplicate launch.')
            return 0
        configure_logging(folder)
        degrees = load_settings(folder / 'settings.json')
        session = SessionShutdown(runtime.request_stop)
        LOG.info('Starting background runtime, steering range %s.', degrees)
        return run_service(['--range', str(degrees)], stop_requested=runtime.stop_requested)
    finally:
        # Released only after service finally blocks have neutralized the wheel.
        try:
            if session is not None:
                session.close()
        finally:
            runtime.close()


def bundle_directory() -> Path:
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))


def check_package(root: Path) -> None:
    """Verify bundled imports and PE bitness without registry or wheel I/O."""
    import hid
    if not callable(hid.device):
        raise RuntimeError('The packaged HID runtime is unavailable.')
    for arch, expected in (('x86', 0x014C), ('x64', 0x8664)):
        data = (root / 'drivers' / arch / 'g25ff.dll').read_bytes()
        if len(data) < 64 or data[:2] != b'MZ':
            raise ValueError(f'Invalid {arch} driver.')
        offset = int.from_bytes(data[60:64], 'little')
        if data[offset:offset + 4] != b'PE\x00\x00' or int.from_bytes(data[offset + 4:offset + 6], 'little') != expected:
            raise ValueError(f'Incorrect driver architecture: {arch}.')
    if not (root / 'scripts' / 'Register-G25StandaloneFF.ps1').is_file():
        raise FileNotFoundError('The registration script is missing.')
    LOG.info('Package smoke check passed (no hardware or registry access).')


def register_driver(root: Path, action: str) -> None:
    script = root / 'scripts' / 'Register-G25StandaloneFF.ps1'
    if not script.is_file():
        raise FileNotFoundError(f'Missing bundled registration script: {script}')
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / \
        'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    args = [str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(script), '-Action', action]
    if action == 'Install':
        for bits, option in (('x86', '-Dll32'), ('x64', '-Dll64')):
            dll = root / 'drivers' / bits / 'g25ff.dll'
            if not dll.is_file():
                raise FileNotFoundError(f'Missing bundled driver: {dll}')
            args += [option, str(dll)]
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors='replace',
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(f'Driver {action.lower()} failed:\n{result.stdout}')
    LOG.info('Driver %s: %s', action.lower(), result.stdout.strip())


def show_error(message: str) -> None:
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    user32.MessageBoxW.restype = ctypes.c_int
    user32.MessageBoxW(None, message, 'G25Standalone', 0x10)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='G25Standalone background controller')
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument('--stop', action='store_true')
    commands.add_argument('--register', action='store_true')
    commands.add_argument('--unregister', action='store_true')
    commands.add_argument('--settings', action='store_true')
    commands.add_argument('--check-package', action='store_true')
    parser.add_argument('--quiet', action='store_true', help='log errors without showing a dialog')
    args = parser.parse_args(argv)
    try:
        folder = state_directory()
        if args.stop or args.register or args.unregister or args.settings or args.check_package:
            # Short-lived commands must not hold the running service's log open.
            configure_logging(folder, control=True)
        if args.check_package:
            check_package(bundle_directory())
            return 0
        if args.stop:
            stop_running(folder)
            LOG.info('Background runtime stopped.')
            return 0
        if args.register or args.unregister:
            register_driver(bundle_directory(), 'Install' if args.register else 'Uninstall')
            return 0
        if args.settings:
            path = folder / 'settings.json'
            if not path.exists():
                load_settings(path)
            # An invalid existing file must remain editable.
            subprocess.Popen([str(Path(os.environ['SystemRoot']) / 'System32' / 'notepad.exe'), str(path)])
            return 0
        result = start_background(folder)
        if result:
            raise RuntimeError('The controller could not start. It may already be owned by a development service.')
        return 0
    except Exception as exc:
        LOG.exception('G25Standalone command failed.')
        if not args.quiet:
            show_error(f'{exc}\n\nSee diagnostic logs in %LOCALAPPDATA%\\G25Standalone for details.')
        return 1
    finally:
        for stream in (sys.stdout, sys.stderr):
            if isinstance(stream, LogStream):
                stream.flush()
        logging.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
