@echo off
rem Started by the Windows task "Twitch Auto Clipper" at logon and on wake:
rem monitoring with automatic uploads. The app writes data\output\monitor.log itself,
rem never more than 10 MB (the previous part is kept as monitor.old.log).
rem A second start exits at once (instance lock) and "exit" closes its window.
cd /d "%~dp0"
if not exist data\output mkdir data\output
rem A crash (exit code other than 0 or 1, e.g. a GPU driver crash) restarts the app after a
rem minute; 1 (another instance runs, bad configuration) and a normal stop end here.
:run
python -m twitch_auto_clipper --monitor-twitch --auto-upload-youtube --yes --log-file data\output\monitor.log
if %errorlevel% equ 0 exit
if %errorlevel% equ 1 exit
echo App arretee (code %errorlevel%) : redemarrage dans une minute.>> data\output\monitor.log
timeout /t 60 /nobreak >nul
goto run
