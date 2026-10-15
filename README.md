# Poste de Iluminação Pública Inteligente (Grupo 17)

Projeto da disciplina **Sistemas Embarcados** da CESAR School.
Professores: Bella Nunes e Jymmy Barreto.

## Problema
A iluminação pública em Recife ainda é, em grande parte, ligada e desligada sem
considerar a presença de pedestres, falhas de lâmpada ou a segurança urbana.

## Solução (MVP)
Um ESP32 simula um poste inteligente que:
- acende à noite (LDR) com **piso de 70%**, seguindo a diretriz CPTED de segurança;
- vai a **100%** por 10 s quando detecta um pedestre (sensor ultrassônico);
- detecta **falha ou desgaste** da lâmpada (simulada com um potenciômetro);
- envia **telemetria via MQTT** a cada 5 s e recebe comandos da central;
- entra em **fail-safe (100%)** se ficar mais de 15 s sem comunicação.

## Arquitetura
- **Firmware:** ESP32 + FreeRTOS, com 3 tarefas (sensores, controle, comunicação)
- **Comunicação:** MQTT nos tópicos `g17/poste/<ID>/telemetria`, `comando` e `status` (LWT)
- **Central:** Mosquitto + SQLite + dashboard Streamlit *(em desenvolvimento)*
- **Escala:** 20 postes simulados + 1 poste real

### Contrato MQTT

| Tópico | Direção | Conteúdo |
|---|---|---|
| `g17/poste/P01/telemetria` | poste → central | JSON a cada 5 s (ver exemplo abaixo) |
| `g17/poste/P01/comando` | central → poste | `{"potencia": 0-100}` |
| `g17/poste/P01/status` | poste → central | `online` / `offline` (retido, LWT) |

```json
{"id":"P01","luz":32,"noite":1,"dist":202,"presenca":0,"desgaste":0.28,
 "pct":70,"estado":"DIMERIZADO","pedido":40,"uptime":15}
```

Estados possíveis: `DIA`, `DIMERIZADO`, `NOITE`, `PEDESTRE`, `FALHA`, `FAILSAFE`.

### LED RGB de status

| Cor | Significado |
|---|---|
| Verde | Dia, pedestre ou noite a 100% |
| Amarelo | Dimerizado (abaixo de 100%) |
| Vermelho | Falha ou desgaste da lâmpada |
| Azul | Fail-safe (sem comunicação há mais de 15 s) |

## Estrutura do repositório

| Pasta | Conteúdo |
|---|---|
| `esp32-esp8266/` | Firmware do poste (sketch, diagrama Wokwi, bibliotecas) |
| `applications/` | Broker, banco de dados, dashboard e simulador |
| `schematics/` | Esquemáticos e fotos da montagem |
| `docs/` | Relatório CSBC, slides e registros de teste |

## Mapa de pinos (ESP32 DevKit)

| GPIO | Componente |
|---|---|
| 25 | LED branco (luminária), resistor de 100 Ω |
| 16 / 17 / 23 | LED RGB R / G / B (220 / 100 / 100 Ω) |
| 26 / 27 | HC-SR04 TRIG / ECHO |
| 34 | LDR (divisor com 10 kΩ) |
| 35 | Potenciômetro (simula desgaste) |
| 2 | LED da placa (aceso = conectado) |

## Como rodar no simulador
1. Abra o [Wokwi](https://wokwi.com) e crie um projeto ESP32.
2. Copie `sketch.ino`, `diagram.json` e `libraries.txt` da pasta `esp32-esp8266/poste_g17/`.
3. Rode a simulação e acompanhe o Serial Monitor.
4. Para ver a telemetria, abra o [HiveMQ Web Client](https://www.hivemq.com/demos/websocket-client/),
   clique em **Connect** e assine `g17/poste/P01/#`.
5. Para enviar um comando, publique `{"potencia":90}` em `g17/poste/P01/comando`.

O broker `broker.hivemq.com` é público e serve só para testes. A entrega final usará o Mosquitto do grupo.

## Status
- [x] Lógica de controle (dia/noite, pedestre, falha, piso CPTED)
- [x] FreeRTOS com 3 tarefas e mutex
- [x] Telemetria e comandos via MQTT + LWT
- [x] Fail-safe com carência de 15 s
- [ ] IPv6
- [ ] Dashboard Streamlit + SQLite
- [ ] Simulador de 20 postes
- [ ] Montagem física
- [ ] Relatório CSBC

Os testes realizados estão em [`docs/testes_wokwi.md`](docs/testes_wokwi.md).

## Equipe
- Antônio Augusto
- *(adicionar os demais integrantes)*
