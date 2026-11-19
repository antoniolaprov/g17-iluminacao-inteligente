# CLAUDE.md

Poste de iluminação pública inteligente para Recife (Grupo 17, Sistemas Embarcados, CESAR School). Um ESP32
numa maquete lê luz, presença e desgaste, controla a luminária por PWM e conversa por MQTT com um dashboard web.

## Leia antes de qualquer coisa

1. [`docs/CONTEXTO_PARA_IA.md`](docs/CONTEXTO_PARA_IA.md): contexto completo (pinos, lógica, MQTT, decisões e histórico).
2. [`README.md`](README.md): visão geral, estados do poste e contrato MQTT.
3. Se a tarefa for machine learning: [`MACHINE_LEARNING.md`](MACHINE_LEARNING.md).

## Mapa do repositório

| Pasta | O que tem |
|---|---|
| `esp32-esp8266/poste_g17/` | Firmware (`sketch.ino`, FreeRTOS + Wi-Fi + MQTT) e circuito do Wokwi (`diagram.json`) |
| `applications/dashboard/` | Dashboard web (HTML + JS + MQTT.js), abre direto no navegador |
| `applications/` | Back-end, simulador e ML ainda vão entrar aqui |
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
- **Relatório CSBC:** o enunciado só permite IA para **revisão de texto**, com declaração de uso. Não escreva
  o texto do relatório; ajude a revisar e a conferir fatos técnicos.
- **Commits:** a nota avalia commits colaborativos. Deixe cada integrante commitar o próprio trabalho com a
  própria conta, e termine as mensagens de commit com a linha de coautoria da IA usada.

## Como trabalhar com o grupo

- Responda em **português**, com passo a passo simples: o grupo está aprendendo ESP32 agora.
- Placa: ESP32 DevKit V1 (30 pinos, CP2102), compilada no PlatformIO (`esp32doit-devkit-v1`, 115200 baud,
  `lib_deps = knolleary/PubSubClient`).
- Broker atual: HiveMQ público (`broker.hivemq.com:1883`; dashboard em `wss://broker.hivemq.com:8884/mqtt`).
  Para a entrega final o enunciado pede Mosquitto local, então deixe o endereço do broker configurável.
- Prazos: documentação (relatório + Git) em **03/12**; apresentação ao vivo na Mostra TechDesign em **12/12**.
