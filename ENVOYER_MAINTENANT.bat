@echo off
chcp 65001 >nul
title Veille IA ^& Tech - envoi
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (python veille.py envoyer) else (py -3 veille.py envoyer)
echo.
pause
