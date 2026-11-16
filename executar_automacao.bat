@echo off

cd /d "C:\workspace\jobs_automation"

if not exist "logs" mkdir "logs"

set "LOG_FILE=logs\automation_%date:~6,4%-%date:~3,2%-%date:~0,2%_%time:~0,2%-%time:~3,2%-%time:~6,2%.log"

set "LOG_FILE=%LOG_FILE: =0%"

echo ================================================== >> "%LOG_FILE%"
echo AUTOMACAO INICIADA >> "%LOG_FILE%"
echo Data/Hora: %date% %time% >> "%LOG_FILE%"
echo ================================================== >> "%LOG_FILE%"

docker compose up --build --abort-on-container-exit --exit-code-from app app >> "%LOG_FILE%" 2>&1

set "APP_EXIT_CODE=%ERRORLEVEL%"

echo. >> "%LOG_FILE%"
echo ================================================== >> "%LOG_FILE%"
echo AUTOMACAO FINALIZADA >> "%LOG_FILE%"
echo Exit Code: %APP_EXIT_CODE% >> "%LOG_FILE%"
echo Data/Hora: %date% %time% >> "%LOG_FILE%"
echo ================================================== >> "%LOG_FILE%"

docker compose down --remove-orphans >> "%LOG_FILE%" 2>&1

exit /b %APP_EXIT_CODE%