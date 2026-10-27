@echo off
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo Creando entorno virtual...
    python -m venv .venv
)

echo Instalando dependencias...
.venv\Scripts\pip install -q -r requirements.txt pyinstaller

echo Compilando DetectorHTs.exe...
.venv\Scripts\pyinstaller --onefile --noconsole --uac-admin --clean --version-file version_info.txt --icon docs\icono_axiios_glow.ico --add-data "docs\icono_axiios.ico;." --add-data "docs\icono_axiios_glow.ico;." --add-data "docs\portada.png;." --add-data "docs\portada_limpia.png;." --name DetectorHTs gui.py

if exist dist\DetectorHTs.exe (
    echo.
    echo  OK: dist\DetectorHTs.exe generado.
) else (
    echo.
    echo  ERROR: no se genero el exe. Revisa la salida de arriba.
)

pause