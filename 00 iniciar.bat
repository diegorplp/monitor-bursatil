@echo off
:: Cambia el directorio de trabajo al lugar donde está este archivo
cd /d "%~dp0"

echo ---------------------------------------------------
echo Iniciando Monitor Bursatil...
echo ---------------------------------------------------

:: Verifica si existe el entorno virtual
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: No se encuentra la carpeta 'venv'.
    echo Asegurate de estar en la carpeta correcta.
    pause
    exit
)

:: Activa el entorno virtual
call venv\Scripts\activate.bat

:: Ejecuta la app
echo Ejecutando Streamlit...
streamlit run Home.py

:: Mantiene la ventana abierta si hay un error al cerrar
pause