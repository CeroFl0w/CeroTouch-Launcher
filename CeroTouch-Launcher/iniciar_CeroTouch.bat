@echo off
setlocal
cd /d "%~dp0"
title CeroTouch Launcher - Primer inicio

rem ============ AJUSTES ============
rem 1 = despues de crear el acceso directo, este .bat se borra solo (ya no hace falta)
rem 0 = el .bat se conserva
set "BORRAR_BAT=1"
set "SCRIPT=cerotouch_launcher.py"
rem =================================

if not exist "%SCRIPT%" (
    echo No encuentro %SCRIPT% en esta carpeta.
    echo Pon este .bat junto a cerotouch_launcher.py y launcher_core.py.
    echo.
    pause
    exit /b 1
)

rem ---- buscar Python ----
set "PY="
set "PYW="
python --version >nul 2>&1
if not errorlevel 1 (
    set "PY=python"
    set "PYW=pythonw"
)
if not defined PY (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PY=py -3"
        set "PYW=pyw -3"
    )
)
if not defined PY (
    echo No se encontro Python en este equipo.
    echo Instalalo desde https://www.python.org/downloads/windows/
    echo y marca la casilla "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

rem ---- PyQt6 ----
%PY% -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo Instalando PyQt6, solo esta vez...
    %PY% -m pip install PyQt6
    if errorlevel 1 (
        echo.
        echo No se pudo instalar PyQt6. Revisa tu conexion a internet.
        pause
        exit /b 1
    )
)

cls
echo ================================================
echo          CeroTouch Launcher - Primer inicio
echo ================================================
echo.
echo  Para empezar se creara un acceso directo llamado
echo  "CeroTouch Launcher" en tu escritorio y en el menu Inicio.
echo.
echo    [Y]  Si: crear el acceso directo y abrir el launcher
echo    [N]  No: no se crea nada y el launcher no se abre
echo.
choice /c YN /n /m "  Presiona Y o N: "
if errorlevel 2 goto NO

:SI
echo.
echo  Creando acceso directo...
%PY% "%SCRIPT%" --crear-acceso-directo
if errorlevel 1 (
    echo.
    echo  No se pudo crear el acceso directo. Este .bat se conserva.
    echo.
    pause
    exit /b 1
)
echo.
echo  Listo: acceso directo "CeroTouch Launcher" creado.
start "" %PYW% "%SCRIPT%"
if "%BORRAR_BAT%"=="1" goto BORRAR
timeout /t 3 >nul
exit /b 0

:BORRAR
echo  Este .bat ya no hace falta y se elimina. Usa el acceso directo.
timeout /t 3 >nul
(goto) 2>nul & del "%~f0"

:NO
echo.
echo  No se creo ningun acceso directo y el launcher no se abrio.
echo  Cuando quieras empezar, vuelve a ejecutar este .bat.
echo.
pause
exit /b 0