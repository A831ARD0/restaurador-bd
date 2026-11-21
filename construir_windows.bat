@echo off
REM Genera "Restaurador de BD.exe" (se corre UNA vez en la PC con Windows).
REM Requisito: Python 3.10 o superior instalado desde python.org.
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo No encontre Python. Instalalo desde https://www.python.org/downloads/windows/
  echo Marca la casilla "Add python.exe to PATH" durante la instalacion.
  pause
  exit /b 1
)

if not exist .venv (
  echo Creando entorno...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
python -m pip install --quiet pymysql pywebview pyinstaller
if errorlevel 1 (
  echo Fallo la instalacion de dependencias. Revisa tu conexion.
  pause
  exit /b 1
)

pyinstaller --noconfirm --clean --windowed --onefile ^
  --name "Restaurador de BD" ^
  --icon recursos\icono.ico ^
  --collect-all webview ^
  --hidden-import pymysql ^
  restaurador_bd.py
if errorlevel 1 (
  echo Fallo la generacion del ejecutable.
  pause
  exit /b 1
)

echo.
echo Listo: dist\Restaurador de BD.exe
echo Copialo a donde quieras; no necesita instalacion ni Python en la otra PC.
pause
