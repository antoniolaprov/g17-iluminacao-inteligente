# CONTEXTO DO PROJETO: Grupo 17 · Sistemas Embarcados (CESAR School)

> **Como usar este arquivo:** anexe-o (ou cole todo o conteúdo) no início de uma conversa com o Claude
> ou outro assistente de IA, e depois faça sua pergunta. Ele resume tudo o que o grupo decidiu e
> construiu até **24/11/2026**.
>
> Repositório: https://github.com/antoniolaprov/g17-iluminacao-inteligente

---

## 0. Instruções para o assistente de IA

Você está ajudando um integrante do **Grupo 17** no projeto da disciplina de **Sistemas Embarcados
com ESP32** (professores Bella Nunes e Jymmy Barreto). Considere:

- **O firmware do poste já existe e funciona** (v2.2, no repositório). Ele foi validado no simulador
  Wokwi, e a montagem física está em andamento (seção 9). Não reescreva o firmware do zero; parta do
  `esp32-esp8266/poste_g17/sketch.ino`.
- Parte da equipe usa ESP32 pela primeira vez. Explique de forma didática, em passos pequenos e
  testáveis, e só considere um teste aprovado com evidência (linha do Serial, print).
- **Confirmado em 24/11:** Airflow, MLflow e API fazem parte dos requisitos de ML **desta mesma
  disciplina** (não são só da proposta original de outra matéria) — ver o escopo atualizado no
  [`MACHINE_LEARNING.md`](../MACHINE_LEARNING.md). Score CPTED com AHP continua fora do MVP, só isso.
- Respeite o **contrato MQTT** (seção 7) e o **mapa de pinos** (seção 6). **O contrato da seção 7 é o
  que o firmware publica de verdade.** Se for mudar algo, avise, porque outras partes do grupo dependem disso.
- **Política de IA do edital:** o PDF diz que IA é permitida *"apenas para revisão do texto, mediante
  declaração de uso"*. O grupo ainda vai confirmar com os professores se o uso para aprendizado e
  código é aceito. Lembre a pessoa de registrar o uso na declaração exigida.
- Responda em **português**.

---

## 1. Requisitos da disciplina (edital)

**Objetivo:** sistema IoT com ESP32 + sensores/atuadores, comunicação Wi-Fi + **MQTT**, e
**dashboard** com dados em tempo real.

**Obrigatório:**
- 1 ou 2 ESP32 (ESP8266 pode ser secundário); sensores e atuadores.
- Firmware em **VSCode + PlatformIO**, com **FreeRTOS**.
- Broker MQTT (Mosquitto): no PC (Docker/VM/WSL), num Raspberry Pi ou na AWS (opcional).
- Aplicação web (Python/JS etc.).
- **GitHub público** com a estrutura `README.md`, `/docs`, `/applications`, `/esp32-esp8266`,
  `/schematics`. A falta de qualquer pasta reduz a nota de "GitHub (Organização)".

**Avaliação:**

| Item | Pts | Detalhe |
|---|---|---|
| Check Point (17/11) | 15 | Prototipagem, código-fonte, arquitetura, documentação, protótipo do dashboard |
| Funcionamento | 20 | MQTT, **IPv6**, coleta de dados, dashboard |
| Dashboard | 15 | Interface funcional em tempo real |
| Relatório (template CSBC) | 20 | Introdução, metodologia, resultados, códigos em apêndice |
| GitHub | 10 | Bem documentado, **commits colaborativos**, README detalhado |
| Apresentação (12/12) | 20 | Clareza, demo ao vivo, **divisão de tarefas** |
| **Bônus** | até +10 | Alertas por e-mail/mensageiro, infraestrutura IPv6 |

**Penalidades:** projeto não funcional na apresentação perde 50% de "Funcionamento"; não comparecer
à Mostra TechDesign = −30% da nota.

**Datas:**

| Data | Marco |
|---|---|
| 27/10 | Definição da ideia (um integrante apresenta) |
| 17/11 | **Check Point** (15 pts) |
| 03/12, 23h59 | Entrega: relatório `Projeto_Embarcados_GrupoX.pdf` + link do GitHub (Google Classroom) |
| 12/12 | Apresentação na Mostra TechDesign |

---

## 2. Grupo

Antônio Augusto, Arthur Sales, Bruno Mayer, Felipe Andrade, Henrique Figueredo, Luiz Claudio
Pinheiro e Miguel Becker.

---

## 3. Problema e proposta original (outra disciplina)

**Tema:** gestão inteligente da iluminação pública do Recife (desafio do Banco de Oportunidades da
Prefeitura; metas municipais de −35% de consumo e +50% de eficiência na manutenção).

**Problema:** o parque de iluminação usa relés fotoelétricos sem telemetria. A manutenção é reativa
(depende de inspeção ou reclamação), o consumo é estático e as falhas demoram a ser corrigidas,
afetando sobretudo pedestres e periferias. Pesquisa de campo (n=12): 11/12 nunca usaram canais
oficiais para reportar falhas; 11/12 acham essencial a detecção automática; 10/12 apoiam dimerização
desde que a segurança seja mantida; "luz piscando/instável" foi o problema mais citado (10/12).

**Proposta original completa:** telemetria via MQTT → PostgreSQL → Airflow → modelo de falha em
14 dias (Random Forest/XGBoost + MLflow) → FastAPI → dashboard geoespacial em Streamlit; priorização
de reparos por **score CPTED** (pesos AHP) e **dimerização adaptativa com piso de segurança**
(ABNT NBR 5101:2024 + piso por nível CPTED); fail-safe a 100%; tudo em Docker Compose.

**Adaptação para Embarcados:** o edital exige hardware real. Por isso, o ESP32 vira **um poste de luz
físico em miniatura**, que fala o mesmo formato MQTT dos postes simulados.

---

## 4. Escopo MVP

| Proposta original | MVP |
|---|---|
| PostgreSQL | **SQLite** + script coletor em Python |
| **Airflow** | **Confirmado em 24/11: entra no MVP**, só com um DAG leve (`preparar_dados` → `treinar` → `publicar_risco`), `LocalExecutor`, sem Celery/Postgres |
| XGBoost | `RandomForestClassifier`/`GradientBoostingClassifier` do scikit-learn, comparados com uma regra simples (seção 8) |
| **MLflow** | **Confirmado em 24/11: entra no MVP**, rastreando os experimentos de treino (parâmetros, métricas, modelo) |
| Score CPTED com AHP | **Nível CPTED fixo** por poste (o poste real é "média", piso 70%) — esse corte continua |
| **FastAPI** + Streamlit | **Confirmado em 24/11: a API entra no MVP** (serve a inferência do modelo); o dashboard em tempo real continua em HTML/JS, mas um painel de risco em Streamlit pode ser adicionado |
| 100 postes simulados | **3 postes físicos + postes simulados** (quantidade a definir no simulador) |
| INA219, DS18B20, PIR, BH1750 | **Fora do MVP** (evoluções futuras) |
| — | **Docker**: conteinerizar Mosquitto, coletor, API e Airflow (confirmado em 24/11, não estava no MVP original) |

### Arquitetura
```
        POSTE FÍSICO                              PC
┌────────────────────────────┐            ┌──────────────────────────────────┐
│  ESP32 = poste "P01"       │   Wi-Fi    │  Mosquitto (broker MQTT)         │
│  LDR ......... é noite?    │ ─────────► │      │                           │
│  Ultrassônico  tem gente?  │ telemetria │      ▼                           │
│  Potenciômetro desgaste    │   (5 s)    │  coletor.py ──► SQLite           │
│  LED RGB branco luminária  │ ◄───────── │                    │             │
│  LED RGB ..... status      │  comando   │                    ▼             │
└────────────────────────────┘            │  Dashboard Streamlit             │
                                          │   • mapa com 21 postes           │
   simulador.py = 20 postes virtuais ───► │   • gráfico em tempo real        │
   (mesmo formato de mensagem)            │   • comando de potência          │
                                          │   • alerta Telegram (bônus)      │
                                          └──────────────────────────────────┘
```

---

## 5. Hardware

**Placa:** ESP32 DevKit V1, 30 pinos, ESP-WROOM-32, micro-USB, chip USB **CP2102**. No Windows precisa
do driver **"CP210x Universal Windows Driver"** (Silicon Labs): sem ele a placa aparece com erro no
Gerenciador de Dispositivos e o PlatformIO não acha porta. No PlatformIO: board
`esp32doit-devkit-v1`, framework `arduino`, `monitor_speed = 115200`.

**Componentes:** o kit da faculdade (maleta RoboCore "My Project Box") tem tudo o que o MVP precisa,
conforme análise da professora. Inclui ESP32, protoboards, jumpers, LED RGB, LEDs, potenciômetro,
resistores, ultrassônico **HC-SR04** (precisa de 5 V, ver seção 6) e **módulo de luz (LDR) de 4 pinos**.

---

## 6. Mapa de pinos (MVP)

| GPIO | Componente | Ligação |
|---|---|---|
| **18** | Luminária (PWM) | **Mini poste de maquete com LED 3 V** (2 fios, testado em 19/11): **fio vermelho → resistor 100 Ω → GPIO18**, **fio branco → GND**. Até 3 postes em paralelo no mesmo pino, cada um com o seu resistor de 100 Ω saindo da fileira do GPIO18; mais que isso exige transistor NPN alimentado pelo VIN. *Antes era um LED RGB aceso em branco (R, G e B juntos no GPIO18), que continua sendo a luminária no Wokwi. Era o GPIO25 até 27/10* |
| **19 / 21 / 5** | LED RGB de status R / G / B | via **220 / 100 / 100 Ω** · comum no GND (cátodo comum). *Antes 16/17/23; mudou em 29/10 porque eram os pinos livres na montagem* |
| **26** | Ultrassônico TRIG | direto |
| **27** | Ultrassônico ECHO | **via divisor de tensão** (1 kΩ em cima, 2 × 1 kΩ embaixo). Sensor alimentado no **VIN (5 V)** |
| **34** | **Sensor de luz de 2 pernas** (indicado pelo professor em 03/11) | Divisor: **3V3 → sensor → GPIO34 → 10 kΩ → GND**. O fio do GPIO34 sai do ponto entre o sensor e o resistor. *Antes era o módulo de 4 pinos (AO → GPIO34). No Wokwi continua o módulo, que por dentro é o mesmo LDR + 10 kΩ* |
| **35** | Potenciômetro (desgaste) | pontas em 3V3 e GND, **meio no GPIO35** |
| **2** | LED azul da placa | aceso = conectado à central |

**Regras importantes:**
- O ESP32 é **3,3 V**. Nunca coloque 5 V num GPIO. **Alimente o módulo de luz em 3V3**, não em 5V/VIN.
- **HC-SR04:** em 3,3 V ele não responde (sempre sem eco). Alimente no **VIN** e **nunca** ligue o ECHO
  direto no GPIO: ele devolve 5 V. Use o divisor `ECHO → 1 kΩ → GPIO27`, `GPIO27 → 1 kΩ → 1 kΩ → GND`.
- Entradas analógicas **só no ADC1 (GPIO 32 a 39)**, porque o ADC2 para de funcionar com o Wi-Fi ligado.
- Evitar GPIO 0, 5, 12, 15 (boot) e 6 a 11 (flash).
- O módulo de luz tem dois pinos de saída: **AO** (analógico, o que usamos) e **DO** (digital). Ligar
  o DO no lugar do AO foi um erro real durante a montagem.
- Se a leitura de um pino analógico "copia" a do pino vizinho, esse pino está solto ou os fios estão
  na mesma fileira da protoboard.
- A leitura analógica do ESP32 satura perto de 3,1 V (fica em 4095 no fim do giro do potenciômetro)
  e não é perfeitamente linear. Isso é normal.
- **Sentido do módulo de luz:** o módulo do Wokwi dá *mais luz = número menor* (`LDR_INVERTIDO = true` no modo simulação). **O módulo físico do grupo é o contrário: mais luz = número maior** (`LDR_INVERTIDO = false` no modo placa física). Isso foi confirmado em teste em 27/10: com a sala clara, a leitura bruta fica perto de 4095; com o dedo em cima, perto de 0.

---

## 7. Contrato MQTT (implementado no firmware v2.2)

> Todos os postes, real e simulados, devem usar **exatamente** este formato.
> Ele substitui o formato provisório que aparecia na versão de 13/10 deste arquivo.

**Telemetria** (poste → central, a cada 5 s), tópico `g17/poste/<ID>/telemetria`:
```json
{"id":"P01","luz":32,"noite":1,"dist":202,"presenca":0,"desgaste":0.28,
 "pct":70,"estado":"DIMERIZADO","pedido":40,"uptime":15}
```

| Campo | Significado |
|---|---|
| `id` | Identificador do poste. O real é `P01`; os simulados devem ser `P02` a `P21` |
| `luz` | Luz ambiente, 0 a 4095 (já normalizada: maior = mais claro) |
| `noite` | 1 se está de noite |
| `dist` | Distância do ultrassônico, em cm (999 = nada detectado) |
| `presenca` | 1 se houve pedestre nos últimos 2 s |
| `desgaste` | 0.00 a 1.00 (no poste real vem do potenciômetro) |
| `pct` | Brilho aplicado, em % |
| `estado` | `DIA`, `DIMERIZADO`, `NOITE`, `PEDESTRE`, `FALHA` ou `FAILSAFE` |
| `pedido` | Última potência pedida pela central |
| `uptime` | Segundos desde que o poste ligou |

**Comando** (central → poste), tópico `g17/poste/<ID>/comando`: `{"potencia":90}` (0 a 100).
O firmware também aceita só o número, como `90`.

**Status** (LWT, retido), tópico `g17/poste/<ID>/status`: `online` ou `offline`. O broker publica
`offline` sozinho se o poste cair.

**Ainda não implementado no firmware:** timestamp `ts` via NTP e corrente estimada. Se o dashboard
precisar de hora, por enquanto use a hora em que o coletor recebeu a mensagem.

**Broker de teste atual:** `broker.hivemq.com:1883` (público). Para ver as mensagens:
https://www.hivemq.com/demos/websocket-client/ → Connect → assinar `g17/poste/P01/#`.
A entrega final deve usar o Mosquitto do grupo.

**Cadastro dos postes** (no servidor, a fazer): `id`, `lat`, `lon`, `nivel_cpted` (`alta`, `media`
ou `baixa`).

---

## 8. Lógica do sistema

### No ESP32 (implementado)
O controle roda a cada 50 ms e segue esta prioridade:
1. **De dia** → `DIA`, 0%.
2. **Sem rede há mais de 15 s** → `FAILSAFE`, 100%, RGB azul.
3. **Pedestre a menos de 5 cm nos últimos 2 s** → `PEDESTRE`, 100%, RGB verde.
4. **Senão** → `DIMERIZADO`, `max(pedido da central, 70%)`, RGB amarelo. Se o pedido for 100% → `NOITE`, RGB verde.

Por cima de tudo: **desgaste > 0,70** → `FALHA`, RGB vermelho e LED cintilando (o brilho calculado é mantido).

**Parâmetros:** piso CPTED 70% · presença a 5 cm por 2 s (escala da maquete; era 50 cm. O HC-SR04 não mede bem abaixo de ~3 cm, então não reduzir mais) · ecos < 2 cm descartados · 2 leituras seguidas · correção gama 2,2 na luminária (o `pct` é brilho percebido; sem ela 70% parecia quase 100%) · desgaste 0,70 · carência do fail-safe
15 s · telemetria a cada 5 s · potência pedida inicial 40%.

**FreeRTOS (3 tarefas + mutex do estado + mutex do Serial):**

| Tarefa | Prioridade | Período | Função |
|---|---|---|---|
| `sensores` | 2 | 60 ms | Lê LDR, ultrassônico e potenciômetro |
| `controle` | 3 | 50 ms | Decide estado e brilho, aciona LEDs |
| `comunicacao` | 1 | 20 ms | Wi-Fi, MQTT, telemetria, comandos |

**Pisos CPTED da proposta original** (para os postes simulados): alta = 100% no pico e ≥ 80% fora;
média ≥ 70%; baixa ≥ 50%; sem dado = tratar como alta.

### No servidor: regra de risco (a fazer no coletor)

| Condição | Risco |
|---|---|
| `estado = FALHA` ou desgaste > 0,7 | alto |
| desgaste entre 0,4 e 0,7 | médio |
| resto | baixo |
| `status = offline` ou sem telemetria há mais de 30 s | offline |

Risco alto ou offline → alerta no Telegram (bônus).

---

## 9. O que já foi feito

### Simulador Wokwi
- Firmware v1 (lógica): 9 testes aprovados (dia, noite, pedestre, timer, falha, pedido de 90%).
- Firmware v2.2 (FreeRTOS + MQTT): testes A a G aprovados (conexão, telemetria vista no HiveMQ,
  comando remoto, LWT, queda curta sem fail-safe, queda longa com fail-safe).
- Registro completo em `docs/testes_wokwi.md`.
- No Wokwi, o Wi-Fi pode levar até 30 s para conectar. Isso é normal.

### Repositório GitHub
- Estrutura do edital criada; firmware em `esp32-esp8266/poste_g17/` (`sketch.ino`, `diagram.json`,
  `libraries.txt`); README com contextualização, lógica, contrato MQTT e mapa de pinos.
- `applications/dashboard/` pronto e testado; `applications/ml/` com os dados reais da Emlurb
  baixados e cruzados (ver [`MACHINE_LEARNING.md`](../MACHINE_LEARNING.md)). Coletor/Mosquitto local
  e simulador de postes ainda não existem.

### Montagem física (concluída em 24/11, falta decorar a maquete)
- **São 3 postes físicos**, todos com sensores, luminária e rede testados e funcionando. Falta só a
  decoração da maquete.
- PlatformIO instalado; driver CP210x instalado (placa na COM3); gravação funcionando.
- **Montado e funcionando:** módulo de luz (AO no GPIO34) e potenciômetro (GPIO35), testados com um
  sketch que imprime os dois valores.
- **Calibração do LDR (27/10):** sala clara ≈ 4095 (satura), dedo em cima ≈ 0. Módulo com mais luz =
  número maior, então `LDR_INVERTIDO = false` e `LIMIAR_NOITE = 2000` na placa física.
- **Troca do sensor de luz (03/11):** a pedido do professor, o módulo de 4 pinos foi trocado por um
  **sensor de 2 pernas** em divisor com 10 kΩ (`3V3 → sensor → GPIO34 → 10 kΩ → GND`). Continua
  *mais luz = número maior*. Calibração: **sala ≈ 3200, dedo ≈ 400, lanterna = 4095**.
  `LIMIAR_NOITE = 2000` foi mantido (fica no meio entre sala e dedo).
- **Potenciômetro:** chegou a ficar sempre em 0 porque faltava o fio do **VCC**. Corrigido.
- **Ultrassônico (27/10):** HC-SR04 não respondia em 3,3 V. Passou a funcionar alimentado no VIN, com o
  ECHO ligado direto no GPIO27 (orientação do professor, sem divisor).
- **Os 3 sensores estão montados e funcionando** (luz, potenciômetro, ultrassônico).
- **Luminária (29/10):** o laboratório não tem LED branco, então a luminária é um **LED RGB com as
  três cores juntas no GPIO18** (fica branco). O segundo RGB continua como status, agora em 19/21/5.
  O firmware não mudou de lógica: um único PWM no GPIO18 controla o brilho.
- **Mini poste (19/11):** o LED RGB da luminária foi trocado pelo mini poste de maquete (LED 3 V, fio
  vermelho e fio branco). Testado com o firmware completo: apagado de dia, 70% com o sensor de luz
  tapado, 100% com pedestre. O código não mudou.
- **Rede (17/11):** firmware gravado com `USAR_REDE 1`; conectou no Wi-Fi da faculdade e no HiveMQ, e o
  dashboard (`applications/dashboard`) recebeu a telemetria e enviou comando de potência com sucesso.

**Ao levar o firmware para a placa física:**
- `#define SIMULACAO 0` e preencher SSID/senha do Wi-Fi (**não commitar a senha real**).
- No bloco `#else` (placa física), manter `LDR_INVERTIDO = false` (o módulo físico dá mais luz =
  número maior, ao contrário do Wokwi). Desde a v2.12 (19/11) a placa física usa histerese: escurece
  abaixo de `LIMIAR_NOITE = 2500` e só volta a ser dia acima de `LIMIAR_DIA = 2700` (sala ≈ 3000, sombra da
  mão ≈ 2200, dedo ≈ 400). O pedido foi deixar o sensor mais sensível ao escuro e acabar com o pisca-pisca
  entre DIA e DIMERIZADO perto do limite. No Wokwi: 2000 / 2200.
- O PlatformIO exige `#include <Arduino.h>` no topo e a biblioteca no `platformio.ini`:
  `lib_deps = knolleary/PubSubClient`.
- O firmware atual está num único arquivo. A estrutura em vários arquivos (`config.h`,
  `sensores.cpp` etc.) é opcional.

---

## 10. Divisão de tarefas

O grupo abandonou a divisão fixa por integrante (seção 10 de versões antigas deste arquivo): a partir de
24/11 todo mundo ajuda no que estiver em aberto, priorizando o que falta por ordem de risco para a nota
(seção 1): Mosquitto local + coletor, IPv6, simulador de postes, modelo de risco (ML) e o relatório CSBC.

Cada um deve continuar commitando no repositório do grupo com a própria conta (conta para "commits
colaborativos").

---

## 11. Cronograma

| Até | Entrega | Situação |
|---|---|---|
| 27/10 | Apresentação da ideia | data passada |
| 03/11 | Sensores funcionando + ESP32 publicando no broker | feito: firmware completo, 3 postes físicos montados e testados (sensores, luminária, rede) |
| 10/11 | Coletor + SQLite + dashboard com poste real e simulados | dashboard funciona com o poste real; coletor/SQLite e simulador de postes virtuais ainda não existem |
| **17/11** | **Check Point:** fluxo completo + relatório iniciado + repo organizado | data passada — confirmar resultado com o grupo/professores |
| 24/11 | Dados reais da Emlurb baixados e cruzados por bairro (ver `MACHINE_LEARNING.md`) | feito |
| 03/12 | Mosquitto local, IPv6, alerta Telegram, modelo de risco e relatório final | a fazer |
| 12/12 | Mostra TechDesign | a fazer |

---

## 12. Pendências / a confirmar com os professores

- O que exatamente é esperado no dia 27/10.
- Se a adaptação (proposta da outra disciplina + ESP32 físico + postes simulados) é aceita.
- Se o uso de IA para aprendizado e código é permitido e como declarar.
- Como o **IPv6** será avaliado (critério de Funcionamento e bônus).
