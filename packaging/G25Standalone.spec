from pathlib import Path

root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / "src/g25_service.py")],
    pathex=[str(root / "src")],
    binaries=[], datas=[], hiddenimports=["hid"],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True,
    name="G25Standalone", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True,
)
bundle = COLLECT(
    executable, analysis.binaries, analysis.datas,
    strip=False, upx=False, name="G25Standalone",
)
