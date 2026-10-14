@echo off
rem Started by the Windows task "Twitch Auto Clipper" at logon and on wake:
rem monitoring with automatic uploads. Output is appended to data\output\monitor.log.
rem A second start exits at once (instance lock) and "exit" closes its window.
cd /d "%~dp0"
if not exist data\output mkdir data\output
python -m twitch_auto_clipper --monitor-twitch --auto-upload-youtube --yes >> data\output\monitor.log 2>&1
exit
