@echo off
setlocal
chcp 65001 >nul
title G17 - Demonstracao (nao feche esta janela)
cd /d "%~dp0applications"

echo.
echo  ===== G17 - Iluminacao Inteligente: ligando a demonstracao =====
echo.

rem Modo da demo. "INICIAR_DEMO.bat maquete" ou "INICIAR_DEMO.bat simulado" pula a pergunta.
set MODO=%~1
if /i "%MODO%"=="maquete" goto modo_maquete
if /i "%MODO%"=="simulado" goto modo_simulado
echo  A maquete (placa do P01) esta ligada e conectada no Wi-Fi?
echo    S = sim: o P01 do painel e a placa de verdade (precisa de internet no PC e na placa)
echo    N = nao: o PC simula o P01 (funciona sem internet)
choice /c SN /n /m " Digite S ou N: "
if errorlevel 2 goto modo_simulado

:modo_maquete
rem A placa continua gravada com o HiveMQ; a ponte traz o P01 para o Mosquitto local.
rem Sem P01 simulado: seriam dois P01 no painel.
set MODO=maquete
set MOSQUITTO_CONF=mosquitto-ponte.conf
set SIM_INCLUIR_P01=0
set TXT_POSTES=P02..P10 simulados; o P01 e a placa, pela ponte com o HiveMQ
goto modo_ok

:modo_simulado
set MODO=simulado
set MOSQUITTO_CONF=mosquitto.conf
set SIM_INCLUIR_P01=1
set TXT_POSTES=P01 com a rua em Y + P02..P10, todos simulados

:modo_ok
echo.
echo  Modo: %MODO%
echo.

echo [1/7] Verificando o Docker...
set TENTATIVAS=0
:checa_docker
docker info >nul 2>&1
if not errorlevel 1 goto docker_ok
if %TENTATIVAS%==0 (
  echo       Docker Desktop fechado. Abrindo... espere ate 3 minutos.
  start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
)
set /a TENTATIVAS+=1
if %TENTATIVAS% GEQ 36 goto erro_docker
timeout /t 5 /nobreak >nul
goto checa_docker
:docker_ok
echo       OK

echo [2/7] Ligando a central (broker, bancos, MLflow, API, modelos e parque de luminarias)...
echo       Na primeira vez o Docker instala as bibliotecas (pode levar uns 20 minutos) e o parque
echo       gera 900 dias de historico (mais uns 4 minutos ate o painel do gestor ter dados).
docker compose up -d --build
if errorlevel 1 goto erro

echo [3/7] Ligando os postes: %TXT_POSTES%...
docker compose --profile sim up -d
if errorlevel 1 goto erro

echo [4/7] Esperando a API e o MLflow responderem...
set TENTATIVAS=0
:checa_api
curl -fs --max-time 5 -o nul http://localhost:8000/saude
if not errorlevel 1 goto api_ok
set /a TENTATIVAS+=1
if %TENTATIVAS% GEQ 30 goto erro
timeout /t 2 /nobreak >nul
goto checa_api
:api_ok
set TENTATIVAS=0
:checa_mlflow
curl -fs --max-time 5 -o nul http://localhost:5000/health
if not errorlevel 1 goto mlflow_ok
set /a TENTATIVAS+=1
if %TENTATIVAS% GEQ 30 goto erro
timeout /t 2 /nobreak >nul
goto checa_mlflow
:mlflow_ok
echo       OK

rem Os treinos ficam num volume do Docker deste PC, nao no Git. Num PC novo o MLflow abre vazio,
rem entao treina uma vez. Isso regrava applications/ml/models; nao precisa commitar.
echo [5/7] Conferindo os treinos no MLflow...
curl -sf -o nul "http://localhost:5000/api/2.0/mlflow/experiments/get-by-name?experiment_name=risco_bairro"
if not errorlevel 1 goto risco_treinado
echo       Sem o treino do modelo de risco neste PC. Treinando agora, leva alguns minutos...
docker compose run --rm treinar
if errorlevel 1 goto erro
:risco_treinado
curl -sf -o nul "http://localhost:5000/api/2.0/mlflow/experiments/get-by-name?experiment_name=rota_pedestre"
if not errorlevel 1 goto rota_treinada
echo       Sem o treino do modelo de rota neste PC. Treinando agora...
docker compose run --rm --no-deps rota python ml/src/prever_rota.py treinar
if errorlevel 1 goto erro
docker compose restart rota >nul
if errorlevel 1 goto erro
:rota_treinada
curl -sf -o nul "http://localhost:5000/api/2.0/mlflow/experiments/get-by-name?experiment_name=falha_14d"
if not errorlevel 1 goto falha_treinada
echo       Sem o treino do modelo de falha em 14 dias neste PC. Treinando agora, leva alguns minutos...
docker compose run --rm --no-deps pipeline python ml/src/treinar_falha.py
if errorlevel 1 goto erro
:falha_treinada
echo       OK

echo [6/7] Mandando o risco de cada bairro para os postes...
docker compose run --rm publicar
if errorlevel 1 goto erro

echo [7/7] Abrindo as paginas no navegador...
set DASH=%~dp0applications\dashboard\index.html
set DASH=%DASH:\=/%
start "" msedge "file:///%DASH%?broker=ws://localhost:9001" 2>nul || start "" "%~dp0applications\dashboard\index.html"
timeout /t 2 /nobreak >nul
start "" "http://localhost:8501"
start "" "http://localhost:5000"
start "" "http://localhost:8000/rota?dist_s1=3&hora=21"

echo.
echo  ================== PRONTO! O QUE OLHAR ==================
echo.
echo   MODO       - %MODO%: %TXT_POSTES%
echo   DASHBOARD  - clique no poste P01:
echo                "Risco do ML"   = modelo de risco do bairro
echo                "Cascata em Y"  = modelo de rota acendendo a rua
echo   GESTOR     - http://localhost:8501: mapa do parque, risco de falha em 14 dias,
echo                lista de manutencao (CPTED) e dimerizacao com o teste de seguranca
echo   MLFLOW     - aba Experiments: os treinos e a nota de cada modelo (falha_14d e outros)
echo   API        - a resposta do modelo para "pedestre a 3 cm as 21h"
echo                (troque o 3 na barra de endereco e aperte Enter)
echo.
echo   Para desligar tudo depois: dois cliques em PARAR_DEMO.bat
echo  =========================================================
echo.
echo Aperte qualquer tecla para ver o modelo de rota decidindo ao vivo.
echo (Cada linha = um pedestre. Feche a janela quando quiser; a demo continua ligada.)
pause >nul
docker compose logs -f --tail 10 rota
goto fim

:erro_docker
echo.
echo  O Docker nao ligou. Abra o Docker Desktop, espere "Engine running" e rode de novo.
pause
exit /b 1

:erro
echo.
echo  Algo deu errado no passo acima. Tire um print desta janela e mande para o grupo.
pause
exit /b 1

:fim
exit /b 0
