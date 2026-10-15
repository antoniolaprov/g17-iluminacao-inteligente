# Aplicações

Lado "central" do sistema (em desenvolvimento):

- **Broker MQTT:** Mosquitto
- **Banco de dados:** SQLite, para guardar a telemetria recebida
- **Dashboard:** Streamlit, com o mapa e o estado dos postes e o envio de comandos
- **Simulador:** script que publica a telemetria de 20 postes virtuais

O formato das mensagens está no [README principal](../README.md#contrato-mqtt).
