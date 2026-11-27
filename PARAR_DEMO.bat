@echo off
chcp 65001 >nul
title G17 - Desligando a demonstracao
cd /d "%~dp0applications"
echo Desligando todos os containers do G17 (os dados gravados ficam guardados)...
docker compose --profile sim --profile airflow down
echo.
echo Pronto, tudo desligado.
pause
