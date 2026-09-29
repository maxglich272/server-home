@echo off
rem ============================================================
rem  Servidor Home - doble clic aqui para abrir el panel.
rem  La primera vez descarga Python (unos 11 MB) dentro de esta
rem  carpeta y crea accesos directos en el Escritorio y en Inicio.
rem ============================================================
setlocal EnableExtensions
title Servidor Home
cd /d "%~dp0"
set "APPDIR=%~dp0"
set "PYW=%APPDIR%python\pythonw.exe"

if not exist "%PYW%" (
  echo Preparando Servidor Home por primera vez, espera un momento...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%APPDIR%herramientas\preparar-windows.ps1" -Python
)
if not exist "%PYW%" call :sistema
if not exist "%PYW%" goto :sinpython

set "MARCA="
if exist "%APPDIR%herramientas\.accesos-listos" set /p MARCA=<"%APPDIR%herramientas\.accesos-listos"
if /i not "%MARCA%"=="%APPDIR%" powershell -NoProfile -ExecutionPolicy Bypass -File "%APPDIR%herramientas\preparar-windows.ps1" -Accesos

start "" "%PYW%" "%APPDIR%servidor_home.py" %*
exit /b 0

:sinpython
echo.
echo No se pudo preparar Python. Revisa tu conexion a internet y vuelve a abrir este archivo.
echo Otra opcion: instala Python desde https://www.python.org/downloads/ y vuelve a abrirlo.
echo.
pause
exit /b 1

:sistema
rem Plan B: usar un Python 3.8+ que ya este instalado en el PC.
call :probar py -3
if exist "%PYW%" exit /b 0
call :probar python
exit /b 0

:probar
for /f "usebackq delims=" %%P in (`%* -c "import sys,os;assert sys.version_info>=(3,8);print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul`) do if exist "%%P" set "PYW=%%P"
exit /b 0
