@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

REM ============================================================
REM ホクロ自動検出 & Photoshop 一括レタッチ実行バッチ
REM 使い方:
REM   1) ダブルクリック -> 同階層の input フォルダを処理
REM   2) 画像フォルダをこの .bat にドラッグ＆ドロップ -> そのフォルダを処理
REM   3) run_mole_removal.bat "C:\path\to\images" [--detect-only]
REM ============================================================

set "SCRIPT_DIR=%~dp0"
set "DETECT_SCRIPT=%SCRIPT_DIR%detect_moles.py"
set "JSX_SCRIPT=%SCRIPT_DIR%remove_moles.jsx"

REM Python 実行ファイルの自動検出（環境変数 PYTHON_EXE > 同階層 venv/.venv > 上位 venv > PATH の python）
if defined PYTHON_EXE (
    if not exist "%PYTHON_EXE%" (
        echo [WARN] 環境変数 PYTHON_EXE が見つかりません: %PYTHON_EXE%
        set "PYTHON_EXE="
    )
)
if not defined PYTHON_EXE if exist "%SCRIPT_DIR%venv\Scripts\python.exe" set "PYTHON_EXE=%SCRIPT_DIR%venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%SCRIPT_DIR%..\..\venv\Scripts\python.exe" set "PYTHON_EXE=%SCRIPT_DIR%..\..\venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
    )
)

set "INPUT_DIR=%~1"
set "DETECT_ONLY=0"
if /i "%~1"=="--detect-only" (
    set "INPUT_DIR="
    set "DETECT_ONLY=1"
)
if /i "%~2"=="--detect-only" (
    set "DETECT_ONLY=1"
)
if "%INPUT_DIR%"=="" (
    set "INPUT_DIR=%SCRIPT_DIR%input"
)

set "OUTPUT_ROOT=%SCRIPT_DIR%output"
set "PREVIEW_DIR=%OUTPUT_ROOT%\preview"
set "PSD_DIR=%OUTPUT_ROOT%\psd"
set "JSON_PATH=%OUTPUT_ROOT%\moles_coords.json"

echo ============================================================
echo  ホクロ自動検出 ^& Photoshop 一括レタッチツール
echo ============================================================
echo  Python      : %PYTHON_EXE%
echo  入力フォルダ : %INPUT_DIR%
echo  JSON出力    : %JSON_PATH%
echo  プレビュー   : %PREVIEW_DIR%
echo  PSD出力     : %PSD_DIR%
echo ============================================================
echo.

if not defined PYTHON_EXE (
    echo [ERROR] Python が見つかりませんでした。
    echo         venv を作成して requirements.txt をインストールするか、環境変数 PYTHON_EXE を指定してください。
    pause
    exit /b 1
)

if not exist "%INPUT_DIR%" (
    echo [ERROR] 入力フォルダが見つかりません:
    echo         %INPUT_DIR%
    echo         画像を入れたフォルダを作成するか、フォルダをこのバッチにドラッグ＆ドロップしてください。
    pause
    exit /b 1
)

echo [STEP 1/2] Python (OpenCV) でホクロを検出中...
"%PYTHON_EXE%" "%DETECT_SCRIPT%" ^
    --input "%INPUT_DIR%" ^
    --json "%JSON_PATH%" ^
    --preview-dir "%PREVIEW_DIR%" ^
    --psd-dir "%PSD_DIR%"

if errorlevel 1 (
    echo.
    echo [ERROR] Python による検出処理でエラーが発生しました。
    pause
    exit /b 1
)

if "%DETECT_ONLY%"=="1" (
    echo.
    echo [INFO] --detect-only が指定されたため、Photoshop 処理はスキップしました。
    exit /b 0
)

echo.
echo [STEP 2/2] Photoshop を起動してスポット修復・PSD保存を実行します...

if defined PS_EXE (
    if not exist "%PS_EXE%" (
        echo [WARN] 環境変数 PS_EXE のパスが存在しません: %PS_EXE%
        set "PS_EXE="
    )
)

if not defined PS_EXE (
    for %%V in (2027 2026 2025 2024 2023 2022 2021 2020) do (
        if not defined PS_EXE (
            if exist "C:\Program Files\Adobe\Adobe Photoshop %%V\Photoshop.exe" (
                set "PS_EXE=C:\Program Files\Adobe\Adobe Photoshop %%V\Photoshop.exe"
            )
        )
    )
)

set "BETA_PS=C:\Program Files\Adobe\Adobe Photoshop (Beta)\Photoshop.exe"
if not defined PS_EXE if exist "%BETA_PS%" set "PS_EXE=%BETA_PS%"

if not defined PS_EXE (
    echo [ERROR] Photoshop.exe が自動検出できませんでした。
    echo         環境変数 PS_EXE に Photoshop.exe のフルパスを設定してから再実行してください。
    pause
    exit /b 1
)

echo  Photoshop   : %PS_EXE%
echo  JSX         : %JSX_SCRIPT%
echo.

start "" /wait "%PS_EXE%" "%JSX_SCRIPT%"

echo.
echo ============================================================
echo  全処理が完了しました。
echo  - プレビュー確認: %PREVIEW_DIR%
echo  - PSD出力先    : %PSD_DIR%
echo  - Photoshopログ : %PSD_DIR%\photoshop_log.txt
echo ============================================================
pause
exit /b 0
