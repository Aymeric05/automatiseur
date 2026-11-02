@echo off
rem Started by the Windows task "Twitch Auto Clipper" at logon and on wake:
rem monitoring with automatic uploads. The app writes data\output\monitor.log itself,
rem never more than 10 MB (the previous part is kept as monitor.old.log).
rem A second start exits at once (instance lock) and "exit" closes its window.
cd /d "%~dp0"
if not exist data\output mkdir data\output
python -m twitch_auto_clipper --monitor-twitch --auto-upload-youtube --yes --log-file data\output\monitor.log
exit
