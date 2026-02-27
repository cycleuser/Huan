@echo off
setlocal

echo === Cleaning previous builds ===
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
for /d %%i in (*.egg-info) do rmdir /s /q "%%i"

echo === Installing build tools ===
pip install --upgrade build twine

echo === Building package ===
python -m build
if %errorlevel% neq 0 (
    echo Build failed!
    exit /b 1
)

echo === Uploading to PyPI ===
twine upload dist/*
if %errorlevel% neq 0 (
    echo Upload failed!
    exit /b 1
)

echo === Done ===
endlocal
