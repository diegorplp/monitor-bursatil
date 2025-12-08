@echo off
echo ---------------------------------------------------
echo Cerrando Monitor Bursatil (Puerto 8501)...
echo ---------------------------------------------------

:: Busca el proceso que escucha en el puerto 8501 y lo mata
FOR /F "tokens=5" %%a IN ('netstat -aon ^| find ":8501" ^| find "LISTENING"') DO (
    taskkill /f /pid %%a
    echo Servidor detenido exitosamente.
)

echo.
echo Listo. Ya puedes cerrar esta ventana.
pause