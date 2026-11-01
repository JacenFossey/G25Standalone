# Build from the repository root with: python -m PyInstaller packaging/G25Standalone.spec
from pathlib import Path

ROOT = Path(SPECPATH).parent
for arch in ('x86', 'x64'):
    dll = ROOT / 'build' / ('g25ff-' + arch) / 'Release' / 'g25ff.dll'
    if not dll.is_file():
        raise SystemExit('Build the ' + arch + ' driver first: ' + str(dll))

a = Analysis(
    [str(ROOT / 'src' / 'g25_app.py')],
    pathex=[str(ROOT / 'src')],
    binaries=[],
    # Drivers are COM payloads, not Python dependency DLLs; preserve both bitnesses.
    datas=[
        (str(ROOT / 'scripts' / 'Register-G25StandaloneFF.ps1'), 'scripts'),
        (str(ROOT / 'build' / 'g25ff-x86' / 'Release' / 'g25ff.dll'), 'drivers/x86'),
        (str(ROOT / 'build' / 'g25ff-x64' / 'Release' / 'g25ff.dll'), 'drivers/x64'),
    ],
    hiddenimports=['hid'],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='G25Standalone', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='G25Standalone')
