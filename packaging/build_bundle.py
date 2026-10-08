"""Assemble the Windows ZIP and fail if a native dependency is missing."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

import pefile

ROOT = Path(__file__).resolve().parents[1]


def native_inventory(folder: Path) -> list[dict]:
    binaries = sorted(p for p in folder.rglob('*') if p.suffix.lower() in ('.exe', '.dll', '.pyd'))
    bundled = {p.name.lower() for p in binaries if 'drivers' not in p.relative_to(folder).parts}
    system = Path(os.environ['SystemRoot']) / 'System32'
    inventory = []
    for path in binaries:
        relative = path.relative_to(folder).as_posix()
        with pefile.PE(str(path), fast_load=True) as pe:
            pe.parse_data_directories(directories=[
                pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
                pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT'],
            ])
            imports = sorted({entry.dll.decode('ascii').lower() for attribute in
                              ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT')
                              for entry in getattr(pe, attribute, [])})
            expected = 0x14c if relative.startswith('drivers/x86/') else 0x8664
            if pe.FILE_HEADER.Machine != expected:
                raise ValueError(f'Wrong native architecture: {relative}')
        driver = relative.startswith('drivers/')
        for name in imports:
            msvc = name.startswith(('vcruntime', 'msvcp', 'msvcr', 'concrt'))
            if driver and msvc:
                raise ValueError(f'Driver requires an external MSVC runtime: {relative}: {name}')
            if not driver and name in bundled:
                continue
            # Windows 11 supplies API sets and system libraries. Never use the
            # build machine's globally installed VC runtime to satisfy imports.
            if not msvc and (name.startswith(('api-ms-', 'ext-ms-')) or (system / name).is_file()):
                continue
            raise ValueError(f'Unbundled native dependency: {relative}: {name}')
        inventory.append({'path': relative, 'machine': hex(expected), 'imports': imports})
    if not any(p.name.startswith('hid.') and p.suffix == '.pyd' for p in binaries):
        raise ValueError('Missing native hidapi extension')
    return inventory


def copy_notices(folder: Path) -> dict:
    destination = folder / 'licenses'
    destination.mkdir()
    packages = {}
    for line in (ROOT / 'packaging/requirements-build.txt').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        name = line.split('==')[0]
        distribution = importlib.metadata.distribution(name)
        packages[name] = distribution.version
        count = 0
        for entry in distribution.files or []:
            if any(Path(part).name.lower().startswith(('license', 'copying', 'notice')) for part in entry.parts):
                # Keep the package's directory structure and upstream texts.
                if Path(entry).suffix.lower() in ('.py', '.pyc'):
                    continue
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    target = destination / name / Path(entry)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    count += 1
        if not count:
            raise ValueError(f'No upstream license included for {name}')
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    shutil.copy2(python_license, destination / 'Python-LICENSE.txt')
    shutil.copy2(ROOT / 'packaging/Apache-2.0.txt', destination / 'OpenSSL-Apache-2.0.txt')
    return packages


def main():
    version = (ROOT / 'packaging/bundle-version.txt').read_text().strip()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    name = f'G25Standalone-{version}-{revision[:8]}-windows-x64'
    staging = ROOT / 'build/bundle-stage' / name
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(ROOT / 'build/frozen/G25Standalone', staging)
    for arch in ('x86', 'x64'):
        destination = staging / 'drivers' / arch
        destination.mkdir(parents=True)
        shutil.copy2(ROOT / f'build/bundle-g25ff-{arch}/Release/g25ff.dll', destination / 'g25ff.dll')
    for source, target in (
        ('scripts/Register-G25StandaloneFF.ps1', 'Register-G25StandaloneFF.ps1'),
        ('packaging/QUICKSTART.md', 'QUICKSTART.md'),
        ('packaging/THIRD-PARTY-NOTICES.md', 'THIRD-PARTY-NOTICES.md'),
    ):
        shutil.copy2(ROOT / source, staging / target)
    packages = copy_notices(staging)
    native = native_inventory(staging)
    manifest = {
        'version': version, 'commit': revision, 'python': platform.python_version(),
        'platform': platform.platform(), 'packages': packages,
        'cmake': subprocess.check_output(['cmake', '--version'], text=True).splitlines()[0],
        'native': native,
        'files': {p.relative_to(staging).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(staging.rglob('*')) if p.is_file()},
    }
    (staging / 'BUILD-INFO.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    archive = output / f'{name}.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zip_file:
        for path in sorted(staging.rglob('*')):
            if path.is_file():
                zip_file.write(path, Path(name) / path.relative_to(staging))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{checksum}  {archive.name}\n', encoding='ascii')
    print(json.dumps({'archive': str(archive), 'sha256': checksum, 'files': len(manifest['files']),
                      'packages': packages, 'native': native}, indent=2))


if __name__ == '__main__':
    main()
