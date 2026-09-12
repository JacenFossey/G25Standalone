@echo off
setlocal

if /I not "%VSCMD_ARG_TGT_ARCH%"=="x86" (
    echo ERROR: This proxy must be built with the x86 MSVC toolchain.
    echo Open an "x86 Native Tools Command Prompt for VS" and run build.bat again.
    echo Current target architecture: %VSCMD_ARG_TGT_ARCH%
    exit /b 1
)

if not exist build mkdir build

echo Building G25Standalone DirectInput proxy...
echo.

cl ^
    /nologo ^
    /std:c++17 ^
    /EHsc ^
    /MT ^
    /O2 ^
    /W4 ^
    /LD ^
    proxy.cpp ^
    /Fo:build\proxy.obj ^
    /link ^
    /DEF:dinput8.def ^
    /OUT:build\dinput8.dll ^
    /IMPLIB:build\dinput8.lib

if errorlevel 1 (
    echo.
    echo BUILD FAILED
    exit /b 1
)

echo.
echo Build succeeded.
echo.

echo Architecture:
dumpbin /headers build\dinput8.dll | findstr /i "machine"

echo.
echo Export:
dumpbin /exports build\dinput8.dll | findstr /i "DirectInput8Create"

echo.
