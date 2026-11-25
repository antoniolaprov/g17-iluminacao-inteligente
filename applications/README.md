# Aplicações

Lado "central" do sistema:

- **Broker MQTT:** Mosquitto local — *ainda não existe neste repositório*. Hoje a demonstração usa o
  broker público `broker.hivemq.com` (ver [README principal](../README.md#contrato-mqtt)).
- **Coletor + banco de dados:** script Python guardando a telemetria em SQLite — *ainda não existe*.
- **Dashboard:** página web em [`dashboard/`](dashboard/) (HTML + JavaScript + MQTT.js), com o estado
  dos postes em tempo real e o envio de comandos. **Pronto e testado com a placa real.**
- **Simulador:** script que publica a telemetria de postes virtuais `P02` em diante, no mesmo formato
  do poste físico `P01` (a maquete tem 1 ESP32 controlando 3 mini postes juntos) — *ainda não existe*.
- **`ml/`:** cruza o cadastro de postes e os chamados da Emlurb para treinar um modelo de risco de
  falha por bairro, servido por API e MQTT, orquestrado por Airflow, rastreado no MLflow — tudo
  requisito confirmado da disciplina, não bônus. Dados baixados, cruzados e EDA concluída; ver
  [`ml/README.md`](ml/README.md) e o [plano completo](../MACHINE_LEARNING.md) na raiz.

O formato das mensagens MQTT está no [README principal](../README.md#contrato-mqtt). Tudo isso
(Mosquitto, coletor, API, Airflow) vai rodar em containers Docker — ver seção 6 do
[`MACHINE_LEARNING.md`](../MACHINE_LEARNING.md).
