@echo off
chcp 65001 >nul
title Veille IA ^& Tech - apercu
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (python veille.py apercu) else (py -3 veille.py apercu)
echo.
pause
