@echo off
cd /d "%~dp0.."
if not exist data\bot.pid ( echo [OFFLINE] Bot band hai. & pause & exit /b )
set /p BOTPID=<data\bot.pid
tasklist /FI "PID eq %BOTPID%" 2>NUL | find "%BOTPID%" >NUL
if "%ERRORLEVEL%"=="0" ( echo [ONLINE] Bot chal raha hai ^(PID %BOTPID%^) ) else ( echo [OFFLINE] Purani PID file hai, bot band hai. )
pause
