@echo off
cd /d "%~dp0.."
if exist data\bot.pid (
    for /f %%p in (data\bot.pid) do taskkill /F /PID %%p >nul 2>&1
    del data\bot.pid >nul 2>&1
    echo [OK] PSX bot band ho gaya (sirf is bot ka process, baqi node apps safe hain).
) else (
    echo Bot chal nahi raha (PID file nahi mili).
)
pause
