@echo off
rem Started by the Windows task "Twitch Auto Clipper" at logon and on wake:
rem monitoring with automatic uploads. The app writes data\output\monitor.log itself,
rem never more than 10 MB (the previous part is kept as monitor.old.log).
rem A second start exits at once (instance lock) and "exit" closes its window.
cd /d "%~dp0"
if not exist data\output mkdir data\output
rem The daily optimization routine runs inside the Claude app: open it if it is closed, so a run
rem missed while the computer was off happens now (Claude catches up missed scheduled runs).
tasklist /fi "imagename eq claude.exe" | find /i "claude.exe" >nul || start "" explorer.exe shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude
python -m twitch_auto_clipper --monitor-twitch --auto-upload-youtube --yes --log-file data\output\monitor.log
exit
