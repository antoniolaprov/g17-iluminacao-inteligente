# Registro de testes no Wokwi

Todos os testes foram feitos no simulador Wokwi em 15/10/2026, com evidência no Serial Monitor.

## v1: lógica de controle (sem rede)

| # | Teste | Evidência no Serial | Resultado |
|---|---|---|---|
| 1 | Dia → LED apagado | `[DIA] luz=3862 noite=0 ... pct=0` | Aprovado |
| 2 | Pedestre de dia → continua apagado | `[DIA] ... dist=30 presenca=1 pct=0` | Aprovado |
| 3 | Anoitecer → 70% (piso CPTED) | `luz=2942 → [DIA]`, `luz=1951 → [DIMERIZADO] pct=70` | Aprovado |
| 4 | Pedestre à noite → 100% | `[PEDESTRE] luz=32 noite=1 dist=30 presenca=1 pct=100` | Aprovado |
| 5 | Pedestre saiu → volta a 70% após ~10 s | `[PEDESTRE] dist=205` por ~10 s → `[DIMERIZADO] pct=70` | Aprovado |
| 6 | Limite da falha (0,70) | `desgaste=0.68 → normal`, `0.71 → [FALHA]` | Aprovado |
| 7 | Falha à noite → FALHA + cintilação | `[FALHA] luz=32 noite=1 ... desgaste=1.00 pct=100` | Aprovado |
| 8 | Falha de dia → FALHA, LED apagado | `[FALHA] ... noite=0 ... pct=0` | Aprovado |
| 9 | Pedido de 90% → 90% | `[DIMERIZADO] ... presenca=0 ... pct=90` | Aprovado |

## v2.2: FreeRTOS + MQTT

| # | Teste | Evidência | Resultado |
|---|---|---|---|
| A | Conexão Wi-Fi + MQTT | `[WiFi] conectado! IP: 10.10.0.2` / `[MQTT] conectado ao broker!` | Aprovado |
| B | Telemetria chega na internet a cada 5 s | JSON recebido no HiveMQ Web Client (`uptime` 51 → 56 → 61) | Aprovado |
| C | Comando remoto muda a potência | `{"potencia":90}` → `[MQTT] comando recebido` → `pct=90 pedido=90` | Aprovado |
| E | Offline automático (LWT) | `offline` publicado pelo broker ao parar a simulação | Aprovado |
| F | Queda curta (< 15 s) mantém 70% | `[DIMERIZADO] ... rede=0 (sem rede ha 3s)` → `rede=1` | Aprovado |
| G | Queda longa (≥ 15 s) → fail-safe | `(sem rede ha 14s) pct=70` → `[FAILSAFE] pct=100 (sem rede ha 15s)` | Aprovado |

## Correções aplicadas durante os testes
- **Pedestre fantasma no boot:** nos primeiros 10 s depois de ligar, o timer considerava que havia presença. Corrigido com a flag `jaViuPedestre`.
- **Fail-safe sensível demais:** quedas de 2 s do broker levavam a luz a 100%. Adicionada carência de 15 s.
- **Linhas do Serial misturadas:** duas tarefas escreviam ao mesmo tempo. Adicionado um mutex para o Serial.
- **Reinício por watchdog ao reconectar (v2.3):** quando o broker público derrubava a conexão, a PubSubClient esperava a resposta do broker por até 15 s sem ceder o processador, e o watchdog (5 s) reiniciava a placa. Corrigido com `setSocketTimeout(3)` e `setKeepAlive(30)`.
- **Presença falsa na placa física (v2.8):** o HC-SR04 às vezes devolve um eco falso de ~0 cm, e como a presença dura 10 s depois da última detecção, bastava um eco falso a cada poucos segundos para a luz nunca sair de `PEDESTRE`. Leituras abaixo de 2 cm passaram a ser descartadas e o pedestre só é aceito com 2 leituras seguidas abaixo de 50 cm.
