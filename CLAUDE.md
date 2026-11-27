# CLAUDE.md

Plataforma de gestão inteligente da iluminação pública do Recife (Grupo 17, CESAR School). Duas
frentes no mesmo repositório:

- **Sistemas Embarcados:** um ESP32 numa maquete (poste `P01`, cascata em Y) lê luz, presença e
  desgaste, controla a luminária por PWM e conversa por MQTT com um dashboard web em tempo real.
- **Projeto / Ciência da Computação (proposta de Ideação, Proposição e Planejamento):** parque de
  luminárias simuladas com degradação, manutenção preditiva (falha em 14 dias), priorização CPTED,
  dimerização com piso de segurança, PostgreSQL, Airflow, MLflow, FastAPI, Streamlit e Docker.

## Leia antes de qualquer coisa

1. [`docs/CONTEXTO_PARA_IA.md`](docs/CONTEXTO_PARA_IA.md): **fonte única e completa** do projeto: o que
   existe, como funciona, regras e a lista de **tudo o que falta fazer, com critério de pronto**.
2. [`docs/ALINHAMENTO_PROPOSTA.md`](docs/ALINHAMENTO_PROPOSTA.md): o que a **proposta original** define e
   como o repositório atende cada ponto. **A proposta é o documento oficial**: se o código divergir dela
   sem justificativa escrita nesse arquivo, o código está errado.
3. Se a tarefa for machine learning: [`docs/PREMISSAS_SIMULADOR.md`](docs/PREMISSAS_SIMULADOR.md)
   (simulador e calibração), [`applications/ml/README.md`](applications/ml/README.md) e
   [`docs/AUDITORIA_ML.md`](docs/AUDITORIA_ML.md) (rubrica de ML da disciplina).
4. [`README.md`](README.md): visão geral para humanos.

## Branch e sincronização

- O trabalho novo vai na branch **`fase2-central-ml`**. Rode `git pull` antes de começar: vários
  integrantes enviam commits.
- A branch `ml-dados-risco-bairro` é antiga: fica guardada, mas não recebe trabalho novo.
- A maquete física fica na faculdade. Sem ela, use o simulador com `SIM_INCLUIR_P01=1`, ou o
  `INICIAR_DEMO.bat` respondendo "N".

## Mapa do repositório

| Pasta | O que tem |
|---|---|
| `esp32-esp8266/poste_g17/` | Firmware (`sketch.ino`, FreeRTOS + Wi-Fi + MQTT) e circuito do Wokwi (`diagram.json`) |
| `applications/dashboard/` | Dashboard da maquete em tempo real (HTML + JS + MQTT.js) |
| `applications/dashboard_gestor/` | Painel do gestor (Streamlit + mapa Folium), consumindo a API |
| `applications/simulador/` | Postes virtuais P02..P10 (`simulador.py`, `cascata.py`) e o **parque de luminárias com degradação** (`parque.py` + `premissas_parque.json`) |
| `applications/backend/` | `coletor.py` (MQTT dos postes → SQLite) e `ingestor_parque.py` (MQTT das luminárias → PostgreSQL) |
| `applications/ml/src/` | Modelo de falha em 14 dias (`treinar_falha.py`, `parque_features.py`), CPTED (`cpted.py`), dimerização (`dimerizacao.py`), pipeline (`pipeline_parque.py`), API (`api.py`), e os modelos da maquete: risco por bairro (`treinar.py`), rota (`prever_rota.py`), anomalias (`anomalia_telemetria.py`) |
| `applications/ml/dags/` | DAGs do Airflow: `g17_falha_14d`, `g17_falha_14d_treino` e `g17_risco_bairro` |
| `applications/tests/` | Testes automáticos (pytest), incluindo o teste de segurança da dimerização |
| `applications/docker-compose.yml` | Sobe tudo: Mosquitto, PostgreSQL, MLflow, API, Streamlit, serviços de ML e (profile) Airflow |
| `schematics/` | Esquemático e fotos |
| `docs/` | Contexto, alinhamento com a proposta, premissas do simulador, auditoria de ML, testes |

## Regras que não podem ser quebradas

- **Contrato MQTT:** os tópicos `g17/poste/<id>/telemetria`, `/comando` (`{"potencia":N}`) e `/status`
  (`online`/`offline`, retido) e os campos do JSON são usados pelo ESP32 e pelo dashboard. Pode acrescentar
  tópicos novos (como `g17/luminaria/<id>/telemetria`), mas não mude os existentes.
- **Lógica de segurança do firmware:** de dia a luz fica apagada; à noite nunca fica abaixo de 70%;
  pedestre e fail-safe vão a 100%. Um comando de potência só consegue subir acima de 70%.
- **Dimerização do parque (proposta g.1/g.6):** potência final = máximo(desejada; piso CPTED; piso ABNT).
  Pisos CPTED: alta = 100% das 18h às 22h e ≥ 80% no resto; média ≥ 70%; baixa ≥ 50%; sem dados = alta.
  O teste `applications/tests/test_dimerizacao.py` tem que passar com **0% de violações**.
- **Modelo principal (proposta g.2/g.3/g.7):** classificação binária de falha em (t, t+14 dias] por
  luminária, treinada **só com dados do simulador**; divisão temporal 70/15/15 com intervalo de 14 dias;
  Optuna walk-forward; **PR-AUC** como métrica principal; baselines (regra simples e aleatório
  estratificado); probabilidade calibrada; tudo no MLflow. Dados reais (Emlurb) só calibram o simulador.
- **Modelo de risco por bairro (Emlurb)** é complementar: unidade bairro × mês, alvo
  `chamados_mes_seguinte`, validação temporal pela coluna `conjunto`.
- **O `sketch.ino` do repositório fica no modo Wokwi** (`SIMULACAO 1`). A versão gravada na placa física
  (`SIMULACAO 0`, com a senha do Wi-Fi) fica só no PC do Antônio e **nunca** vai para o Git.
- **Nada de senhas, tokens ou dados brutos grandes no repositório** (CSVs da Emlurb e o banco do parque
  simulado ficam fora do Git).
- **A maquete é um poste só (`P01`):** um ESP32 com 3 mini postes em pinos separados (cascata em Y).
  Postes `P02` em diante são do simulador; luminárias `L001` a `L500` são do parque simulado.
- **Relatório CSBC:** o enunciado só permite IA para **revisão de texto**, com declaração de uso. Não escreva
  o texto do relatório; ajude a revisar e a conferir fatos técnicos. Resultados do modelo de falha são
  sobre **dados simulados** e devem ser apresentados assim.
- **Commits:** a nota avalia commits colaborativos. Deixe cada integrante commitar o próprio trabalho com a
  própria conta, e termine as mensagens de commit com a linha de coautoria da IA usada.

## Como trabalhar com o grupo

- Responda em **português**, com passo a passo simples.
- Windows: se `python` não estiver no PATH, use `py`. O jeito mais fácil de rodar tudo é o Docker
  (`INICIAR_DEMO.bat` na raiz, ou `applications/README.md`).
- Testes: `cd applications` e `docker compose run --rm --no-deps api python -m pytest tests -q`.
- Placa: ESP32 DevKit V1 (30 pinos, CP2102), compilada no PlatformIO (`esp32doit-devkit-v1`, 115200 baud,
  `lib_deps = knolleary/PubSubClient`).
- Broker: a placa usa o HiveMQ público; o PC usa o Mosquitto local (a ponte `mosquitto-ponte.conf` liga os dois).
- Prazos: documentação (relatório + Git) em **03/12**; apresentação ao vivo na Mostra TechDesign em **12/12**.
