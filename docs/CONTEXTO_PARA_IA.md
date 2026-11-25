# CONTEXTO COMPLETO DO PROJETO: Grupo 17 · Sistemas Embarcados (CESAR School)

> **Para que serve:** este é o documento único e completo do projeto, feito para ser lido por uma IA
> (Claude, ChatGPT etc.) antes de ajudar qualquer integrante. Ele diz o que o projeto é, o que já existe e
> funciona, como cada parte funciona, as regras que não podem ser quebradas e **tudo o que ainda falta
> fazer, com critério de pronto**.
>
> **Atualizado em 25/11/2026 (noite: central e ML implementados).** Repositório: https://github.com/antoniolaprov/g17-iluminacao-inteligente
> (branch **`main`**). Se algo aqui contradisser o código, o código vale, e este arquivo deve ser corrigido.

---

## 0. Instruções para a IA (leia primeiro)

1. **Responda em português**, em passos pequenos e testáveis. Parte do grupo está aprendendo agora.
   Só considere algo "funcionando" com evidência: saída do Serial, print, métrica, teste.
2. **Não reescreva o que já funciona.** O firmware, o dashboard e a preparação dos dados de ML estão
   prontos e testados (seção 4). Parta deles.
3. **Não quebre o contrato MQTT** (seção 7) nem a lógica de segurança do poste (seção 8). Pode
   acrescentar tópicos e campos novos; mudar os existentes quebra o ESP32 e o dashboard.
4. **Branches:** a `main` tem o projeto até a Fase 2 (central + ML). O trabalho novo, a partir de 25/11, vai
   para a branch **`fase2-central-ml`** (pedido do representante), até o grupo decidir juntar na `main`.
   A branch `ml-dados-risco-bairro` é antiga e fica guardada, mas não deve receber trabalho novo.
5. **Antes de mexer, faça `git pull`.** Vários integrantes enviam commits.
6. **Relatório CSBC:** o edital só permite IA para **revisão de texto**, com declaração de uso. **Não
   escreva o texto do relatório**; ajude a revisar, a conferir números e a explicar conceitos. Lembre a
   pessoa de declarar o uso de IA (no relatório e no código).
7. **Commits:** a nota avalia "commits colaborativos". Quem fez o trabalho faz o commit com a **própria
   conta**. Termine a mensagem com a linha de coautoria da IA usada.
8. **Nunca** coloque senhas, tokens ou os CSVs brutos da Emlurb no Git.
9. O grupo usa **Windows**. Se `python` não estiver no PATH, use `py`. O Python embutido do PlatformIO
   não tem pandas.

---

## 1. A disciplina (edital)

**Objetivo:** sistema IoT com ESP32 + sensores/atuadores, Wi-Fi + **MQTT**, e **dashboard** com dados em
tempo real. Professores: **Bella Nunes** e **Jymmy Barreto**.

**Obrigatório:** 1 ou 2 ESP32; firmware em **VSCode + PlatformIO com FreeRTOS**; broker MQTT (**ESP32,
Raspberry Pi ou Mosquitto no PC** em VM/contêiner/WSL); aplicação web; **GitHub público** com
`README.md`, `/docs`, `/applications`, `/esp32-esp8266` e `/schematics` (falta ou pasta fraca tira nota).

**Requisitos de ML confirmados pelo grupo em 24/11:** EDA com visualizações, comparação de modelos,
rastreamento com **MLflow**, orquestração com **Airflow**, inferência por **API** e **Docker**.

| Item | Pts | O que é avaliado |
|---|---|---|
| Check Point (17/11) | 15 | Já apresentado |
| Funcionamento | 20 | MQTT, **IPv6**, coleta de dados, dashboard |
| Dashboard | 15 | Interface funcional em tempo real |
| Relatório (template CSBC) | 20 | Introdução, metodologia, resultados, códigos em apêndice |
| GitHub | 10 | Bem documentado, **commits colaborativos**, README detalhado |
| Apresentação (12/12) | 20 | Clareza, **demo ao vivo**, divisão de tarefas |
| Bônus | até +10 | Alertas por e-mail/mensageiro, infraestrutura IPv6 |

**Penalidades:** projeto que não funciona na apresentação perde 50% de "Funcionamento"; faltar à Mostra
TechDesign tira 30% da nota.

| Data | Marco |
|---|---|
| **03/12, 23h59** | Entrega no Google Classroom: `Projeto_Embarcados_Grupo17.pdf` (relatório CSBC) + link do GitHub. O PDF também vai em `/docs` |
| **12/12** | Apresentação ao vivo na Mostra TechDesign |

---

## 2. Grupo

Antônio Augusto (representante; firmware, hardware, dashboard), Arthur Sales, Bruno Mayer, **Felipe
Andrade** (ML: dados e EDA), Henrique Figueredo, Luiz Claudio Pinheiro e Miguel Becker. A partir de 24/11
não há divisão fixa: cada um pega uma tarefa da seção 11 e commita com a própria conta.

---

## 3. O problema e a ideia

**Problema (Recife):** a iluminação pública acende no fim da tarde e fica na mesma potência a noite toda,
sem telemetria. A manutenção é reativa (depende de reclamação na Central 156), o consumo é fixo e as falhas
demoram a ser corrigidas, prejudicando pedestres e periferias. Pesquisa do grupo (n=12): 11/12 nunca
usaram canais oficiais para reportar falha; 10/12 apoiam dimerização se a segurança for mantida.

**Ideia:** um poste que (1) só acende à noite, (2) fica em **70%** quando a rua está vazia (piso de
segurança **CPTED**, a rua nunca fica escura), (3) vai a **100%** quando passa um pedestre, (4) avisa
quando a lâmpada está se desgastando, (5) manda tudo por MQTT para uma central e (6) a central usa um
**modelo de ML treinado com dados reais da Emlurb** para prever quais bairros vão ter mais lâmpadas
apagadas e pedir mais potência neles.

**Na maquete:** o ESP32 é um poste em miniatura. O sensor de luz faz o papel do relé fotoelétrico, o
ultrassônico detecta o pedestre, o potenciômetro simula o desgaste da lâmpada e os mini postes LED são a
luminária.

---

## 4. Estado atual (25/11): o que existe e funciona

| Parte | Situação | Onde |
|---|---|---|
| Firmware do poste (FreeRTOS + Wi-Fi + MQTT) | **Pronto e testado na placa** (v2.14) | `esp32-esp8266/poste_g17/sketch.ino` |
| Montagem física | **Pronta.** 1 ESP32 = poste `P01`, controlando **3 mini postes** ligados juntos no GPIO18. Falta decorar a maquete. **A maquete fica na faculdade**; em casa, simule o `P01` (`SIM_INCLUIR_P01=1`, ver `applications/README.md`) | `schematics/` |
| Simulação no Wokwi | Pronta, testes registrados | `diagram.json`, `docs/testes_wokwi.md` |
| Telemetria e comando via MQTT | **Funcionando com a placa real** (Wi-Fi da faculdade + HiveMQ público) | — |
| Dashboard web em tempo real | **Pronto e testado com a placa**: estado, leituras, gráficos, comando de potência | `applications/dashboard/index.html` |
| Dados de ML (Emlurb) | **Baixados, limpos e cruzados por bairro** | `applications/ml/src/preparar_dados.py`, `data/processed/` |
| EDA (notebook) | **Pronta**, com a decisão de alvo, executada com o split corrigido | `applications/ml/notebooks/01_exploracao.ipynb` |
| Modelo de risco + MLflow | **Pronto e testado**: `poisson_glm` escolhido, vence a regra simples (seção 10.7) | `applications/ml/src/treinar.py`, `models/` |
| API de inferência (FastAPI) | **Pronta e testada** (`/saude`, `/risco/{bairro}`, `/riscos`, `/poste/{id}`, `/prever`) | `applications/ml/src/api.py` |
| Publicação do risco no MQTT | **Pronta e testada** (risco retido + comando de potência 90/80/70) | `applications/ml/src/publicar_risco.py`, `config.json` |
| DAG do Airflow | **Pronto e testado**: `g17_risco_bairro` rodou verde (`preparar_dados → treinar → publicar_risco`) | `applications/ml/dags/risco_dag.py`, `applications/airflow/Dockerfile` |
| Mosquitto local (IPv4 + IPv6 + WebSocket) | **Pronto e testado** em Docker | `applications/broker/`, `docker-compose.yml` |
| Coletor + SQLite + alertas (Telegram opcional) | **Pronto e testado** | `applications/backend/coletor.py` |
| Simulador de postes P02..P10 | **Pronto e testado** | `applications/simulador/simulador.py` |
| IPv6 | **Testado** no Mosquitto local (coletor conectado por `::1`) | `applications/README.md` |
| Docker Compose (broker, coletor, MLflow, API, simulador, Airflow) | **Pronto e testado**: todos os serviços subiram; treino registrado no servidor MLflow | `applications/docker-compose.yml` |
| Dashboard mostrando o risco do ML | **Pronto** | `applications/dashboard/` |
| Relatório CSBC | **Não começado** (escrito pelo grupo) | `docs/` |

---

## 5. Arquitetura

### Hoje

```
 Maquete (ESP32 = P01)              Internet                     Navegador
┌──────────────────────┐   Wi-Fi   ┌──────────────────────┐  WSS  ┌──────────────────────┐
│ sensor de luz, HC-SR04│ ───────► │ broker.hivemq.com     │ ◄───► │ Dashboard (HTML/JS)  │
│ potenciômetro         │ telemetr.│ (MQTT público, teste) │       │ estado, gráficos,    │
│ 3 mini postes + RGB   │ ◄─────── │                       │       │ comando de potência  │
└──────────────────────┘  comando └──────────────────────┘       └──────────────────────┘
```

### Meta da entrega (tudo no PC, em Docker)

```
ESP32 (P01) ─┐                 ┌─► coletor.py ──► SQLite (histórico)
simulador ───┼─► Mosquitto ────┼─► dashboard (tempo real + risco + comando)
(P02...)     ┘   1883 / 9001ws └─◄ publicar_risco.py ◄── API FastAPI ◄── modelo (MLflow)
                                                                    ▲
                     Airflow (DAG): preparar_dados → treinar → publicar_risco
                     Alerta Telegram/e-mail (bônus) quando FALHA ou offline
```

---

## 6. Hardware

**Placa:** ESP32 DevKit V1, 30 pinos, ESP-WROOM-32, chip USB **CP2102** (no Windows precisa do driver
"CP210x Universal Windows Driver"; a placa aparece na **COM3**). PlatformIO: board `esp32doit-devkit-v1`,
framework `arduino`, `monitor_speed = 115200`, `lib_deps = knolleary/PubSubClient`.

| GPIO | Componente | Ligação |
|---|---|---|
| **18** | Luminária (PWM): **3 mini postes LED 3 V** | Cada poste: **fio vermelho → resistor 100 Ω → GPIO18**; fio branco/preto → GND. Os 3 resistores saem da mesma fileira do GPIO18 (um resistor por poste). Mais de 3 postes exige transistor NPN no VIN |
| **19 / 21 / 5** | LED RGB de status (R / G / B) | via 220 / 100 / 100 Ω; perna comum (a mais comprida) no GND |
| **26** | HC-SR04 TRIG | direto |
| **27** | HC-SR04 ECHO | **direto** (orientação do professor, sem divisor). Sensor alimentado no **VIN (5 V)**, porque em 3,3 V não responde |
| **34** | Sensor de luz (LDR de 2 pernas) | divisor: **3V3 → LDR → GPIO34 → 10 kΩ → GND**. Mais luz = número maior |
| **35** | Potenciômetro (desgaste) | pontas em 3V3 e GND, pino do meio no GPIO35 |
| **2** | LED azul da placa | aceso = conectado à central |

**Regras e lições da montagem:**
- Todos os GND ligados juntos (linha azul da protoboard). Entradas analógicas só no **ADC1 (GPIO 32 a
  39)**, porque o ADC2 não funciona com Wi-Fi.
- O GPIO5 é pino de boot, mas funciona com o LED de status. Se o Upload falhar com "No serial data
  received", segure o botão **BOOT** e confira que nada está nos GPIO 0, 2, 12 e 15.
- "Acesso negado" na COM3 = outro Monitor está aberto. Feche todos os terminais antes do Upload.
- "Dispositivo não está funcionando" na COM3 = provável curto na montagem. Desligue o USB e revise.
- O ADC satura perto de 3,1 V e não é perfeitamente linear. É normal.

---

## 7. Contrato MQTT (implementado; não mudar)

**Telemetria** (poste → central, a cada 5 s), `g17/poste/<ID>/telemetria`:
```json
{"id":"P01","luz":3013,"noite":0,"dist":17,"presenca":0,"desgaste":0.00,
 "pct":0,"estado":"DIA","pedido":40,"uptime":163}
```

| Campo | Significado |
|---|---|
| `id` | `P01` = poste físico; `P02` em diante = simulador |
| `luz` | 0 a 4095, maior = mais claro |
| `noite` | 1 se é noite (com histerese, seção 8) |
| `dist` | distância do ultrassônico em cm; `999` = nada detectado |
| `presenca` | 1 se há pedestre (detecção recente) |
| `desgaste` | 0.00 a 1.00 (potenciômetro); acima de 0.70 = falha |
| `pct` | brilho aplicado, em % (valor lógico; o PWM usa correção gama) |
| `estado` | `DIA`, `DIMERIZADO`, `NOITE`, `PEDESTRE`, `FALHA`, `FAILSAFE` (ou `INICIANDO` no boot) |
| `pedido` | última potência pedida pela central (começa em 40) |
| `uptime` | segundos desde que ligou |

**Comando** (central → poste), `g17/poste/<ID>/comando`: `{"potencia":90}` (0 a 100), ou só `90`.

**Status** (retido), `g17/poste/<ID>/status`: `online` ao conectar; o broker publica `offline` (LWT) se
o poste cair. Quando a placa reinicia, o `offline` da conexão antiga pode chegar **depois** do `online`
novo; por isso o dashboard considera online quem mandou telemetria nos últimos 15 s.

**Proposto para o ML (ainda não implementado):** `g17/poste/<ID>/risco`, retido, por exemplo
`{"risco":0.82,"classe":"alto","bairro":"BOA VIAGEM","modelo":"rf-v1"}`.

**Brokers:** hoje `broker.hivemq.com:1883` (ESP32) e `wss://broker.hivemq.com:8884/mqtt` (dashboard).
Na entrega: **Mosquitto local**, com listener 1883 (ESP32) e WebSocket 9001 (dashboard). Deixe o endereço
configurável em todo código novo.

---

## 8. Lógica do poste (firmware)

Prioridade a cada ciclo de controle:
1. **De dia** → `DIA`, 0%.
2. **Sem rede há mais de 15 s** → `FAILSAFE`, 100%, status azul.
3. **Pedestre** → `PEDESTRE`, 100%, status verde.
4. **Senão** → `DIMERIZADO` com `max(pedido, 70)`, status amarelo (se der 100% → `NOITE`, verde).

Por cima de tudo: **desgaste > 0,70** → `FALHA`, status vermelho e luminária cintilando.

**Consequência para a central/ML:** um comando só consegue **subir** o brilho acima de 70% à noite; nunca
apaga nem baixa do piso.

| Parâmetro (placa física) | Valor (v2.14) |
|---|---|
| Noite | escurece abaixo de **2500**, clareia acima de **2700** (histerese). Wokwi: 2000/2200 |
| Pedestre | distância **< 5 cm** em **2 leituras seguidas** (ecos < 2 cm descartados) |
| Tempo de presença | luz forte por **0,5 s** depois da última detecção |
| Correção gama do PWM | **4,0** na placa (70% ≈ 24% de PWM, para o salto até 100% ficar visível); 2,2 no Wokwi |
| Piso CPTED | 70% |
| Falha | desgaste > 0,70 |
| Carência do fail-safe | 15 s |
| Telemetria | a cada 5 s |

**FreeRTOS:** tarefa `sensores` (prioridade 2, 60 ms), `controle` (3, 20 ms) e `comunicacao` (1, 20 ms),
com mutex no estado compartilhado e no Serial.

**Modos de compilação:** `#define SIMULACAO 1` (Wokwi) ou `0` (placa); `#define USAR_REDE 1/0`. O
`sketch.ino` do repositório fica **sempre** em `SIMULACAO 1` e sem senha. A versão da placa (com a senha
do Wi-Fi) fica só no PC do Antônio (`Documentos/PlatformIO/Projects/poste_g17`) e **nunca** vai para o Git.

> **v2.14 (25/11, aprovada na placa):** presença 0,5 s, timeout do eco de 6 ms (mede até ~1 m) e controle
> a 20 ms, para a luz reagir mais rápido ao pedestre.

---

## 9. Dashboard (`applications/dashboard/`)

Página única em HTML + JS, com **MQTT.js** (WebSocket) e **Chart.js**. Abre com dois cliques no
`index.html`. Assina `g17/poste/+/telemetria` e `+/status` e mostra: um botão por poste, estado com a cor do
LED de status, brilho, luz, pedestre, desgaste, pedido, economia na sessão, gráficos dos últimos 10
minutos, envio de comando, eventos e tabela das últimas leituras. Broker configurável na própria tela.
**Ainda não mostra** o risco do ML nem histórico do banco.

---

## 10. Machine learning

Plano detalhado: [`MACHINE_LEARNING.md`](../MACHINE_LEARNING.md). Dados e decisões verificadas:
[`applications/ml/README.md`](../applications/ml/README.md). Resumo do que uma IA precisa saber:

### 10.1 Dados
- **Cadastro de postes 2025** (111.666 linhas) e **chamados da Central 156 de 2022 a 2025**, do portal de
  dados abertos do Recife (ODbL). Os brutos ficam em `applications/ml/data/raw/` (fora do Git).
- **Filtro de "lâmpada apagada" pelos códigos, nunca pelo texto:** `GRUPOSERVICO_CODIGO`/`SERVICO_CODIGO`
  = `17`/`25` em 2022-2023 e `4`/`55` em 2024-2025. O texto de 2022-2023 vem com acentos corrompidos.
- **Cruzamento por bairro**, não por coordenada (só ~36% dos chamados têm latitude/longitude).
  `normalizar_bairro()` tira acento, deixa em caixa alta e corrige 3 erros de digitação do cadastro
  (`CIDADDE UNIVERSITARIA`, `IMBIRBEIRA`, `TEJIIPIO`). Resultado: **94 bairros**.
- Descartados: 1 linha desalinhada do cadastro, `BAIRRO NAO INFORMADO` e 3 bairros dos chamados sem
  correspondência no cadastro. **`consumo_kw`/`consumo_1` são lixo:** não usar.

### 10.2 Base de treino: `data/processed/risco_bairro_mes.csv`
4.136 linhas = 94 bairros × 44 meses (**2022-04 a 2025-11**). Features: `chamados_lampada_apagada` (mês
atual), `chamados_lag1/2/3`, `media_movel_3m`, `total_postes`, `postes_sem_id`, `potencia_media_w`,
`pct_led`, `rpa`. Alvo principal: **`chamados_mes_seguinte`**. Coluna `conjunto`: treino = linhas
2022-04 a 2024-11 (3.008), teste = linhas 2024-12 a 2025-11 (1.128), **separado pelo mês do alvo**.

### 10.3 Decisões
- **Alvo = contagem do mês seguinte (regressão/ranking)**, não binário: ~95% das linhas teriam rótulo 1, e
  nenhuma feature passa de 0,15 de correlação com o binário, contra até 0,89 com a contagem.
- **Risco de 0 a 1** = percentil da previsão entre os bairros do mesmo mês. Faixas: ≥ 0,7 alto
  (potência 90), 0,4 a 0,7 médio (80), < 0,4 baixo (70).
- **Validação temporal**, nunca aleatória.

### 10.4 O que o modelo precisa vencer (medido no teste em 25/11)

| Regra simples | MAE | Precisão no top 10% |
|---|---|---|
| Persistência: "mês seguinte = mês atual" | 9,21 | **0,81** |
| `media_movel_3m` | **8,66** | 0,75 |
| Só o tamanho do bairro | — | 0,66 |

Meta: **MAE < 8,66 e precisão no top 10% > 0,81**. "Precisão no top 10%": em cada mês, os 9 bairros com
maior previsão comparados com os 9 de maior contagem real; acertos ÷ 9; média dos 12 meses.

### 10.5 Cuidado de interpretação
Só o número de postes já acerta 66% do top 10%: em contagem absoluta, "risco" vira quase "tamanho do
bairro". Recomendação: mostrar também o ranking por **taxa prevista por 1.000 postes** e o grupo decidir
qual vira o risco publicado.

### 10.7 Modelo treinado (25/11)
`treinar.py` compara `random_forest`, `gradient_boosting`, `hist_gb_poisson`, `poisson_glm` e as duas regras,
com a escolha pela MAE de **validação** (alvos de 2024, dentro do treino), e mede o teste só para o
relatório. Escolhido: **`poisson_glm`** (regressão de Poisson sobre `log1p` das features, padronizadas):
MAE validação **8,30** (regra: 8,93), MAE teste **7,80** (meta: < 8,66), precisão no top 10% no teste
**0,80** (a persistência faz 0,81, nenhum modelo passou). Tabela completa em
`applications/ml/README.md` seção 7 e em `models/metadados.json`. O risco publicado é o percentil da
previsão de 2025-12 entre os bairros (`criterio_risco` no `config.json`: `contagem` ou `taxa`).

### 10.6 Correções feitas em 25/11 (revisão)
- **Vazamento no split:** a linha de 2024-12 (alvo = 2025-01, período de teste) estava no treino. Corrigido
  no script e no CSV processado, e o notebook de EDA foi executado de novo com a base corrigida.
- O notebook e o plano diziam que 2022-2023 tinha chamados "quase em zero". Era de antes do filtro pelos
  dois códigos; a base tem 1.700 a 3.500 chamados por mês nesses anos.
- O script agora informa quantas datas `DATA_DEMANDA` não puderam ser lidas (tem que dar 0).

---

## 11. O que falta fazer (tudo), com critério de pronto

Ordem sugerida pelo risco para a nota. Entrega dos documentos em **03/12**; demo em **12/12**.

> **Situação em 25/11 (noite):** A1-A4, B2-B8 e C1 foram implementados e testados (B3 = `notebooks/02_modelo.ipynb`). Falta testar o ESP32 no
> Mosquitto local (A5, precisa da placa, que está na faculdade), configurar o
> Telegram com um bot de verdade (D1) e toda a parte E. Como rodar: `applications/README.md`.

### A. Infraestrutura (Funcionamento, 20 pts)
| # | Tarefa | Pronto quando |
|---|---|---|
| A1 | **Mosquitto local** em Docker (`applications/broker/` ou no `docker-compose.yml`), listener 1883 + WebSocket 9001, `allow_anonymous true` só na rede local | ESP32 conecta nele (trocar `MQTT_BROKER` pelo IP do PC) e o dashboard recebe por `ws://<ip>:9001` |
| A2 | **Coletor** `applications/backend/coletor.py`: assina `g17/poste/+/telemetria` e `+/status` e grava em **SQLite** (tabela com `recebido_em` + todos os campos do JSON) | Rodando 10 min, a tabela tem ~120 linhas por poste; o `.db` fica fora do Git |
| A3 | **Simulador** `applications/simulador/simulador.py`: postes `P02`+ no mesmo formato, com dia/noite, pedestres aleatórios, desgaste subindo devagar e LWT; respeita `comando` | Os postes simulados aparecem no dashboard junto com o `P01` |
| A4 | **IPv6**: Mosquitto escutando em IPv6 e pelo menos um cliente (dashboard, coletor ou simulador) conectando por endereço IPv6; documentar o teste com print | Print/log mostrando a conexão MQTT por endereço IPv6 (ex.: `[::1]` ou o IPv6 da rede) |
| A5 | Trocar o firmware e o dashboard para o Mosquitto local na demo | Demo completa sem internet externa |

### B. Machine learning (requisito confirmado)
| # | Tarefa | Pronto quando |
|---|---|---|
| B1 | Rodar de novo o notebook de EDA (correção do split) | Saídas atualizadas, commitado |
| B2 | `src/treinar.py`: `RandomForestRegressor` e `GradientBoostingRegressor` prevendo `chamados_mes_seguinte`, com validação temporal; cada treino é uma **run do MLflow** (parâmetros, MAE, RMSE, precisão no top 10%, modelo) | Tabela comparando os modelos com as regras da seção 10.4; melhor modelo registrado no MLflow |
| B3 | `notebooks/02_modelo.ipynb` (ou seção no relatório): comparação, importância das variáveis, ranking por contagem e por taxa | Gráficos prontos para o relatório |
| B4 | `src/api.py` (FastAPI): `GET /risco/{bairro}` → `{"bairro","risco","classe"}` e `GET /saude` | `curl` retorna o risco de um bairro real |
| B5 | `config.json`: `P01` → um `id_ponto` e um bairro reais | Arquivo commitado |
| B6 | `src/publicar_risco.py`: pega o risco do bairro do `P01` (API ou modelo), publica `g17/poste/P01/risco` (retido) e o comando de potência 90/80/70 | À noite, o mini poste sobe para 80-90% conforme o risco |
| B7 | `dags/risco_dag.py` (Airflow, `LocalExecutor`): `preparar_dados → treinar → publicar_risco` | DAG roda verde na UI do Airflow (print para o relatório) |
| B8 | `Dockerfile` + `docker-compose.yml`: Mosquitto, coletor, API, MLflow, Airflow | `docker compose up` sobe tudo |

### C. Dashboard (15 pts)
| # | Tarefa | Pronto quando |
|---|---|---|
| C1 | Mostrar o **risco** do tópico `.../risco` no card do poste | Risco e classe aparecem |
| C2 | (Opcional) histórico do SQLite e mapa dos bairros | — |

### D. Bônus (até +10)
| # | Tarefa | Pronto quando |
|---|---|---|
| D1 | Alerta no **Telegram** ou por e-mail quando `estado = FALHA` ou o poste fica offline (no coletor) | Mensagem chega no celular ao girar o potenciômetro |

### E. Documentação e entrega
| # | Tarefa | Pronto quando |
|---|---|---|
| E1 | **Relatório CSBC** (introdução, metodologia, resultados, códigos em apêndice), **escrito pelo grupo**, com declaração de uso de IA | PDF `Projeto_Embarcados_Grupo17.pdf` em `/docs` e no Classroom até 03/12 |
| E2 | Fotos da montagem e esquemático em `/schematics` | Fotos commitadas |
| E3 | README final (status, como rodar tudo) | Revisado |
| E4 | Commits de todos os integrantes | Cada um com commits próprios |
| E5 | Ensaio da apresentação (roteiro, quem fala o quê, plano B sem internet) | Ensaio feito antes de 12/12 |

---

## 12. Mapa do repositório

| Caminho | Conteúdo |
|---|---|
| `README.md` | Visão geral, lógica, contrato MQTT, pinos, status |
| `CLAUDE.md` | Lido automaticamente pelo Claude Code; aponta para este arquivo |
| `MACHINE_LEARNING.md` | Plano detalhado de ML |
| `docs/CONTEXTO_PARA_IA.md` | **Este arquivo** |
| `docs/testes_wokwi.md` | Registro dos testes no simulador |
| `esp32-esp8266/poste_g17/` | `sketch.ino`, `diagram.json` (Wokwi), `libraries.txt` |
| `applications/dashboard/` | Dashboard web |
| `applications/ml/` | `src/preparar_dados.py`, `notebooks/`, `data/processed/`, `requirements.txt`, README |
| `schematics/` | Esquemático do Wokwi e descrição das ligações |

**Como rodar:** firmware no PlatformIO (pasta local do Antônio, Upload/Monitor) ou no Wokwi (colar
`sketch.ino` e `diagram.json`, biblioteca PubSubClient); dashboard abrindo o `index.html`; dados de ML com
`py applications/ml/src/preparar_dados.py` (precisa dos brutos em `data/raw/`).

---

## 13. Pendências a confirmar

- Como o **IPv6** será avaliado pelos professores (teste local basta?).
- Se o uso de IA no código é aceito e como declarar.
- Qual ranking vira o risco publicado: contagem ou taxa por 1.000 postes (seção 10.5).
