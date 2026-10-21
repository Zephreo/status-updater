@echo off
cd /d "%~dp0"
echo Syncing dependencies from Pipfile.lock...
call pipenv sync
if errorlevel 1 exit /b 1

for /d %%D in (extensions\*) do (
	if exist "%%D\requirements.txt" (
		echo Installing requirements for extension %%~nxD...
		call pipenv run pip install -q -r "%%D\requirements.txt"
		if errorlevel 1 exit /b 1
	)
)

echo Starting Status Updater (pipenv run python main.py)...
echo.
call pipenv run python main.py
