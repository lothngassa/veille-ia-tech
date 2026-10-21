@echo off
chcp 65001 >nul
title Veille IA ^& Tech - configuration
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (python veille.py configurer) else (py -3 veille.py configurer)
echo.
pause
