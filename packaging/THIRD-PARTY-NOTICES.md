# Third-party components

Upstream license texts are copied verbatim into `licenses/`. Exact versions
and native dependency imports are recorded in `BUILD-INFO.json`. Build-only
package notices are included for traceability even when their code is not part
of the runtime.

| Component | Source and notice |
| --- | --- |
| CPython and standard library | https://www.python.org/ — `licenses/Python-LICENSE.txt`, including its bundled-library acknowledgements |
| Python hidapi wrapper and embedded HIDAPI | https://github.com/trezor/cython-hidapi and https://github.com/libusb/hidapi — upstream BSD/GPL/original texts in `licenses/hidapi/`; HIDAPI offers alternative licenses |
| PyInstaller bootloader | https://github.com/pyinstaller/pyinstaller — `licenses/pyinstaller/`, GPL with the bootloader distribution exception |
| PyInstaller hooks | https://github.com/pyinstaller/pyinstaller-hooks-contrib — `licenses/pyinstaller-hooks-contrib/` |
| altgraph, packaging, pefile, pywin32-ctypes, setuptools | Package sources at https://pypi.org/ — corresponding directories under `licenses/` |
| OpenSSL, if present in the Python bundle | https://www.openssl.org/ — Apache 2.0 text in `licenses/OpenSSL-Apache-2.0.txt` |
| Microsoft runtime DLLs bundled with CPython | Microsoft Visual C++ runtime; redistribution subject to Microsoft's terms: https://visualstudio.microsoft.com/license-terms/ |

G25Standalone's own registered DLLs statically link the MSVC runtime. Windows
system DLLs and API sets are supplied by Windows, rather than redistributed in
this ZIP. No third-party component's license is changed by these notices.
