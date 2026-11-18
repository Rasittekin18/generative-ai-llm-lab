@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1

cd /d "%~dp0"

title LectureMind - Video ve Ders Bilgi Studyosu

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [LectureMind] Sanal ortam olusturuluyor...
    python -m venv ".venv" --system-site-packages
    if errorlevel 1 (
        echo [HATA] Python sanal ortami olusturulamadi. Python kurulumunu kontrol edin.
        pause
        exit /b 1
    )
    echo [LectureMind] Bagimliliklar yukleniyor...
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [HATA] Paket yuklemesi sirasinda hata olustu.
        pause
        exit /b 1
    )
)

echo ========================================================
echo   LectureMind baslatiliyor...
echo   Bos port otomatik secilecek ve sunucu hazir olunca
echo   tarayiciniz otomatik acilacaktir.
echo ========================================================

"%VENV_PY%" "%~dp0launch.py"

if errorlevel 1 (
    echo.
    echo [HATA] Sunucu beklenmedik sekilde durdu.
    pause
)
endlocal
