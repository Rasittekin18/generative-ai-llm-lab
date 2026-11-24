@echo off
chcp 65001 >nul
cd /d "%~dp0"
title WP-PC Pilot — WhatsApp Koprusu
npm run start:bridge
pause
