"""Run the extracted shipping executable, without Python/tool paths in PATH.

No test HID stub is bundled: reaching waiting/disconnected exercises the real
hidapi import and enumeration. Run on a Windows CI host with no attached G25.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='G25 ZIP acceptance ') as temporary:
        root = Path(temporary)
        extraction = root / 'extracted bundle with spaces'
        with zipfile.ZipFile(args.archive) as archive:
            archive.extractall(extraction)
        folder, = extraction.iterdir()
        manifest = json.loads((folder / 'BUILD-INFO.json').read_text(encoding='utf-8'))
        for relative, expected in manifest['files'].items():
            assert hashlib.sha256((folder / relative).read_bytes()).hexdigest() == expected, relative
        # Load the shipping x64 COM DLL, with no side-by-side redist DLLs.
        ctypes.WinDLL(str(folder / 'drivers/x64/g25ff.dll'))
        executable = folder / 'G25Standalone.exe'
        state = root / 'user state with spaces'
        cwd = root / 'unrelated working directory'
        cwd.mkdir()
        environment = {k: v for k, v in os.environ.items()
                       if not k.upper().startswith(('PYTHON', '_PYI_', 'PYINSTALLER_'))}
        environment['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')

        def invoke(action, *extra, expected=0):
            result = subprocess.run([str(executable), action, '--data-dir', str(state), *extra],
                                    cwd=cwd, env=environment, capture_output=True, text=True, timeout=20)
            assert result.returncode == expected, (action, result.returncode, result.stdout, result.stderr)
            print(f'{action}: exit={result.returncode} {result.stdout.strip()}', flush=True)
            return result.stdout

        def status():
            return json.loads(invoke('status'))

        try:
            invoke('status', expected=3)
            assert json.loads(invoke('settings'))['steering_range'] == 900
            invoke('settings', '--range', '540')
            first = json.loads(invoke('start'))
            time.sleep(1)  # The detached child must survive the parent exiting.
            active = status()
            assert active['pid'] == first['pid']
            assert active['state'] == 'waiting' and active['wheel'] == 'disconnected', active
            assert active['steering_range'] == 540, active
            assert json.loads(invoke('start'))['pid'] == first['pid']
            invoke('run', expected=2)
            invoke('settings', '--range', '360')
            assert status()['steering_range'] == 540
            invoke('stop')
            invoke('status', expected=3)
            assert not (state / 'runtime.json').exists()
            override = json.loads(invoke('start', '--range', '450'))
            assert override['steering_range'] == 450
            assert json.loads(invoke('settings'))['steering_range'] == 360
            invoke('stop')
            assert json.loads(invoke('start'))['steering_range'] == 360
            invoke('stop')
            invoke('stop')
            log = (state / 'logs/g25.log').read_text(encoding='utf-8')
            assert 'Neutralizing force' in log
            assert 'G25Standalone stopped' in log
            assert 'Traceback' not in log
            assert 'Detection error' not in log
            print(f'PASS: ZIP integrity, native HID import, DLL load, settings, detached startup, '
                  f'status, duplicate protection, clean stop; {len(manifest["files"])} files', flush=True)
        finally:
            invoke('stop')


if __name__ == '__main__':
    main()
