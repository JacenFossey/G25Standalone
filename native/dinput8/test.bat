@echo off
setlocal

if /I not "%VSCMD_ARG_TGT_ARCH%"=="x86" (
    echo ERROR: Open an "x86 Native Tools Command Prompt for VS" first.
    exit /b 1
)

if not exist build mkdir build

cl /nologo /std:c++17 /EHsc /W4 /WX ^
    tests\force_state_test.cpp ^
    /Fo:build\force_state_test.obj ^
    /Fe:build\force_state_test.exe

if errorlevel 1 exit /b 1

build\force_state_test.exe
if errorlevel 1 exit /b 1

echo Force-state tests passed.
