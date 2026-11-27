# Dashboard: Central de Postes G17

Página web que acompanha os postes em tempo real e envia comandos, falando MQTT direto do navegador (MQTT sobre WebSocket).

- **Tecnologias:** HTML, CSS e JavaScript, [MQTT.js](https://github.com/mqttjs/MQTT.js) e [Chart.js](https://www.chartjs.org/)
- **Broker padrão:** HiveMQ público, `wss://broker.hivemq.com:8884/mqtt` (o mesmo `broker.hivemq.com:1883` que o ESP32 usa)
- **Tópicos:** assina `g17/poste/+/telemetria`, `+/status`, `+/risco` e `+/travessia`; publica em `g17/poste/<id>/comando`

## O que mostra

| Área | Conteúdo |
|---|---|
| Postes | Um botão por poste que já mandou telemetria (P01, e os do simulador no futuro), com a cor do estado |
| Estado | Estado atual (DIA, DIMERIZADO, PEDESTRE, NOITE, FALHA, FAILSAFE), brilho da luminária e se o poste está online |
| Risco do ML | Classe e valor do risco previsto para o bairro do poste, publicados pelo `applications/ml/src/publicar_risco.py` |
| Cascata em Y | Só para postes com a cascata (firmware v3.0 ou o `P01` simulado): a rua em Y com o brilho de cada um dos 3 postes, a rota atual e de onde ela veio (aguardando, modelo, confirmada), o total de travessias, quantas tiveram previsão do modelo, o acerto do modelo e as últimas travessias |
| Leituras | Luz ambiente, pedestre e distância, desgaste da lâmpada, pedido da central, economia de energia na sessão e tempo ligado |
| Gráficos | Brilho da luminária (%) e luz ambiente nos últimos 10 minutos |
| Comando | Envia `{"potencia": N}` para o poste selecionado |
| Eventos | Mudanças de estado, comandos enviados, conexão com o broker |
| Últimas leituras | Tabela com as 10 leituras mais recentes |

## Como abrir

Basta abrir o `index.html` no navegador (Chrome ou Edge). Precisa de internet para carregar as bibliotecas e falar com o broker.

Se o navegador bloquear algo abrindo o arquivo direto, sirva a pasta com Python:

```bash
python -m http.server 8765
```

e acesse `http://localhost:8765`.

## Trocar de broker

Em **Configuração do broker**, troque o endereço. Para o Mosquitto local, ative um listener WebSocket no `mosquitto.conf`:

```
listener 1883
listener 9001
protocol websockets
allow_anonymous true
```

e use `ws://localhost:9001` no dashboard. O ESP32 continua na porta 1883 (troque `MQTT_BROKER` no firmware pelo IP do PC).

## Observação sobre "offline"

O ESP32 publica `online` (retido) ao conectar e deixa `offline` como LWT. Quando a placa reinicia, o LWT da conexão antiga pode chegar depois do `online` da nova. Por isso o dashboard considera o poste online sempre que recebeu telemetria nos últimos 15 s.


## Operação e telas menores (T8)

Selecione um poste para ver seus dados e o destino do comando. Os atalhos **Enviar N%** publicam
imediatamente; o slider exige o botão **Enviar**. A mensagem de envio confirma a publicação no broker:
confira o brilho e o pedido na leitura seguinte para verificar a aplicação. Controles ficam desabilitados
quando o broker está desconectado ou o poste está sem leitura recente.

O aviso no topo diferencia conexão, falta de leitura e falha. Em celulares, a seleção ocupa duas
colunas e a tabela permite rolagem horizontal. Os botões mantêm o foco nas atualizações periódicas.
O card de bairro mostra um índice relativo de ranking, não a probabilidade de falha do poste.

Revisão, cenários e capturas: [`docs/REVISAO_UX.md`](../../docs/REVISAO_UX.md).
