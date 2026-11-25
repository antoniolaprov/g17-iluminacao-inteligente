# CLAUDE.md

Poste de iluminação pública inteligente para Recife (Grupo 17, Sistemas Embarcados, CESAR School). Um ESP32
numa maquete lê luz, presença e desgaste, controla a luminária por PWM e conversa por MQTT com um dashboard web.

## Leia antes de qualquer coisa

1. [`docs/CONTEXTO_PARA_IA.md`](docs/CONTEXTO_PARA_IA.md): **fonte única e completa** do projeto: o que
   existe, como funciona, regras e a lista de **tudo o que falta fazer, com critério de pronto** (seção 11).
2. Se a tarefa for machine learning: [`MACHINE_LEARNING.md`](MACHINE_LEARNING.md) (plano) e
   [`applications/ml/README.md`](applications/ml/README.md) (dados e decisões verificadas).
3. [`README.md`](README.md): visão geral para humanos.

## Branch e sincronização

- Trabalhe na **`main`** e rode `git pull` antes de começar: vários integrantes enviam commits.
- A branch `ml-dados-risco-bairro` está **desatualizada** (tudo dela já está na `main`). Não parta dela.

## Mapa do repositório

| Pasta | O que tem |
|---|---|
| `esp32-esp8266/poste_g17/` | Firmware (`sketch.ino`, FreeRTOS + Wi-Fi + MQTT) e circuito do Wokwi (`diagram.json`) |
| `applications/dashboard/` | Dashboard web (HTML + JS + MQTT.js), abre direto no navegador |
| `applications/ml/` | Dados reais da Emlurb cruzados por bairro (`src/preparar_dados.py`, `data/processed/`) e o notebook de EDA. Modelo, MLflow, API, Airflow e Docker ainda vão entrar aqui |
| `applications/` | Mosquitto, coletor + SQLite e simulador de postes ainda vão entrar aqui |
| `schematics/` | Esquemático e fotos |
| `docs/` | Contexto, registro de testes e, no fim, o relatório CSBC em PDF |

## Regras que não podem ser quebradas

- **Contrato MQTT:** os tópicos `g17/poste/<id>/telemetria`, `/comando` (`{"potencia":N}`) e `/status`
  (`online`/`offline`, retido) e os campos do JSON são usados pelo ESP32 e pelo dashboard. Pode acrescentar
  tópicos novos, mas não mude os existentes.
- **Lógica de segurança do firmware:** de dia a luz fica apagada; à noite nunca fica abaixo de 70% (piso CPTED);
  pedestre e fail-safe vão a 100%. Um comando de potência só consegue subir acima de 70%.
- **O `sketch.ino` do repositório fica no modo Wokwi** (`SIMULACAO 1`). A versão gravada na placa física
  (`SIMULACAO 0`, com a senha do Wi-Fi) fica só no PC do Antônio e **nunca** vai para o Git.
- **Nada de senhas, tokens ou dados brutos grandes no repositório** (CSVs da Emlurb ficam fora do Git).
- **ML:** a unidade é **bairro × mês**, o alvo é `chamados_mes_seguinte` (regressão), a validação é temporal
  pelo mês do alvo (coluna `conjunto`, nunca aleatória), e o modelo tem que vencer as regras simples
  (MAE 8,66 e precisão no top 10% de 0,81 no teste). Detalhes na seção 10 do contexto.
- **A maquete é um poste só (`P01`):** um ESP32 controlando 3 mini postes juntos no GPIO18. Postes `P02` em
  diante são do simulador.
- **Relatório CSBC:** o enunciado só permite IA para **revisão de texto**, com declaração de uso. Não escreva
  o texto do relatório; ajude a revisar e a conferir fatos técnicos.
- **Commits:** a nota avalia commits colaborativos. Deixe cada integrante commitar o próprio trabalho com a
  própria conta, e termine as mensagens de commit com a linha de coautoria da IA usada.

## Como trabalhar com o grupo

- Responda em **português**, com passo a passo simples: o grupo está aprendendo ESP32 agora.
- Windows: se `python` não estiver no PATH, use `py`. O Python embutido do PlatformIO não tem pandas.
- Placa: ESP32 DevKit V1 (30 pinos, CP2102), compilada no PlatformIO (`esp32doit-devkit-v1`, 115200 baud,
  `lib_deps = knolleary/PubSubClient`).
- Broker atual: HiveMQ público (`broker.hivemq.com:1883`; dashboard em `wss://broker.hivemq.com:8884/mqtt`).
  Para a entrega final o enunciado pede Mosquitto local, então deixe o endereço do broker configurável.
- Prazos: documentação (relatório + Git) em **03/12**; apresentação ao vivo na Mostra TechDesign em **12/12**.
