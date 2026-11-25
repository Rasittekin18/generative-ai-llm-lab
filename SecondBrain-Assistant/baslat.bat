@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo [Bilgi] .env dosyasi olusturuldu. Google AI Studio API anahtarinizi .env icine ekleyebilirsiniz.
)

if not exist ".venv\Scripts\python.exe" (
    echo [Hata] .venv sanal ortami bulunamadi. Kurulum icin: py -3.12 -m venv .venv
    pause
    exit /b 1
)

".venv\Scripts\python.exe" run.py --open-browser
pause
