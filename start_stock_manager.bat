@echo off
setlocal

set APP_DIR=C:\Users\infolab\ws\stock-manager
set PYTHON=%APP_DIR%\.venv\Scripts\python.exe
set PORT=5001
set URL=http://localhost:%PORT%

cd /d "%APP_DIR%"

:: Flask サーバーをバックグラウンドで起動（最小化・.venv の python を直接指定）
start "StockManager-Flask" /min "%PYTHON%" app.py

:: サーバーが起動するまで最大30秒待機（2秒ごとにポートを確認）
set TRIES=0
:WAIT
set /a TRIES+=1
if %TRIES% gtr 15 goto OPEN
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command ^
  "try { $tcp = New-Object Net.Sockets.TcpClient; $tcp.Connect('localhost', %PORT%); $tcp.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% equ 0 goto OPEN
goto WAIT

:OPEN
:: Chrome → Edge → デフォルトブラウザ の順でキオスクモード（全画面）で起動
set CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe
set EDGE_PATH=C:\Program Files\Microsoft\Edge\Application\msedge.exe
set EDGE_PATH32=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe

if exist "%CHROME_PATH%" (
    start "" "%CHROME_PATH%" --kiosk %URL%
    goto END
)
if exist "%EDGE_PATH%" (
    start "" "%EDGE_PATH%" --kiosk %URL% --edge-kiosk-type=fullscreen
    goto END
)
if exist "%EDGE_PATH32%" (
    start "" "%EDGE_PATH32%" --kiosk %URL% --edge-kiosk-type=fullscreen
    goto END
)
:: フォールバック: デフォルトブラウザで開く（全画面なし）
start %URL%

:END
endlocal
