# Aplicações

Lado "central" do sistema (em desenvolvimento):

- **Broker MQTT:** Mosquitto
- **Banco de dados:** SQLite, para guardar a telemetria recebida
- **Dashboard:** página web em [`dashboard/`](dashboard/) (HTML + JavaScript + MQTT.js), com o estado dos postes em tempo real e o envio de comandos. **Pronto.**
- **Simulador:** script que publica a telemetria de 20 postes virtuais

O formato das mensagens está no [README principal](../README.md#contrato-mqtt).
