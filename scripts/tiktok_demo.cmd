@echo off
rem Demo of the TikTok integration for TikTok's app review (screen-recorded).
title Automatiseur - TikTok integration demo
cd /d "%~dp0.."
mode con: cols=110 lines=30
echo.
echo   AUTOMATISEUR - TikTok integration demo
echo   =====================================
echo.
echo   Step 1 - Login Kit (scope user.info.basic): the creator connects the PeakMoments TikTok account.
echo.
python -m twitch_auto_clipper --authorize-tiktok
timeout /t 6 >nul
echo.
echo   Step 2 - Content Posting API (scope video.upload): a new short video is uploaded to the creator's
echo   TikTok inbox as a draft. Nothing is posted automatically: the creator finishes and posts it in TikTok.
echo.
python -m twitch_auto_clipper --send-tiktok-draft "%~1"
echo.
echo   Demo finished.
timeout /t 15 >nul
