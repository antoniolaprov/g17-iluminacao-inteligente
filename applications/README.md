# Aplicações (a central)

Tudo o que roda no PC, do lado da "central da prefeitura". O formato das mensagens MQTT está no
[README principal](../README.md#contrato-mqtt) e na seção 7 do [contexto](../docs/CONTEXTO_PARA_IA.md).

| Pasta / arquivo | O que é | Situação |
|---|---|---|
| [`broker/mosquitto.conf`](broker/mosquitto.conf) | Mosquitto local: 1883 (MQTT) e 9001 (WebSocket), IPv4 e IPv6 | Pronto, testado |
| [`backend/coletor.py`](backend/coletor.py) | Assina telemetria, status e risco e grava em SQLite; alertas de FALHA/offline (Telegram opcional) | Pronto, testado |
| [`simulador/simulador.py`](simulador/simulador.py) | Postes virtuais `P02`..`P10` no mesmo contrato do ESP32 | Pronto, testado |
| [`dashboard/`](dashboard/) | Dashboard web em tempo real, com o risco do ML | Pronto, testado com a placa |
| [`ml/`](ml/) | Dados da Emlurb, modelo de risco, MLflow, API e DAG do Airflow ([README](ml/README.md)) | Pronto, ver detalhes |
| [`docker-compose.yml`](docker-compose.yml) + [`Dockerfile`](Dockerfile) + [`airflow/Dockerfile`](airflow/Dockerfile) | Sobe tudo em containers | Pronto, testado |
| [`comum.py`](comum.py) | Configuração MQTT compartilhada (variáveis de ambiente) | — |

---

## Jeito 1: tudo no Docker (recomendado para a demonstração)

Precisa do **Docker Desktop** ligado.

```bash
cd applications
docker compose up -d --build            # Mosquitto, coletor, MLflow e API
docker compose --profile sim up -d      # + postes simulados P02..P10
docker compose run --rm publicar        # manda o risco e o comando de potência para os postes
```

| O quê | Onde |
|---|---|
| Dashboard | abra `dashboard/index.html`, vá em **Configuração do broker** e use `ws://localhost:9001` |
| API de risco | http://localhost:8000/docs |
| MLflow (experimentos e modelo registrado) | http://localhost:5000 |
| Airflow (`docker compose --profile airflow up -d --build`, pesado: ~3 GB na primeira vez) | http://localhost:8080, usuário `admin`, senha: `docker compose exec airflow cat standalone_admin_password.txt`. O DAG é o `g17_risco_bairro`; os scripts rodam num venv próprio (`airflow/Dockerfile`), porque o Airflow traz numpy 1.x e o modelo usa numpy 2 |
| Banco do coletor | `backend/dados/central.db` (fora do Git) |
| Logs | `docker compose logs -f coletor` (troque pelo serviço) |

Para desligar: `docker compose --profile sim --profile airflow down`.

## Trabalhando sem a maquete (de casa)

A maquete (ESP32 = `P01`) fica na faculdade. Para testar tudo em casa, simule também o `P01`:

```bash
cd applications
docker compose up -d --build
SIM_INCLUIR_P01=1 docker compose --profile sim up -d    # P01..P10 simulados
docker compose run --rm publicar                         # o P01 (Boa Viagem) recebe risco alto -> 90%
```

No PowerShell, troque a segunda linha por `$env:SIM_INCLUIR_P01=1; docker compose --profile sim up -d`.

- O `P01` simulado tem o mesmo contrato e a mesma lógica do firmware, então o dashboard, o coletor e o
  ML funcionam igual. **Não** ligue o `P01` simulado com a placa conectada no mesmo broker.
- Para testar o **firmware** sem a placa, use o Wokwi (instruções no README principal). O Wokwi roda na
  nuvem e só alcança brokers públicos (`broker.hivemq.com`), não o Mosquitto do seu PC.
- Ligar o ESP32 no Mosquitto local (seção abaixo) só dá para fazer com a placa em mãos.

## Jeito 2: scripts direto no PC

```bash
python -m pip install -r applications/requirements-central.txt
python applications/backend/coletor.py
python applications/simulador/simulador.py
python applications/ml/src/treinar.py
uvicorn api:app --app-dir applications/ml/src --port 8000
python applications/ml/src/publicar_risco.py
```

Todos leem o broker de `MQTT_HOST` / `MQTT_PORT` (padrão `localhost:1883`). Para usar o broker
público de teste: `MQTT_HOST=broker.hivemq.com`.

---

## Ligar o poste físico (ESP32) no Mosquitto local

No firmware, troque `MQTT_BROKER` (hoje `broker.hivemq.com`) pelo **IP do PC na rede** (veja com
`ipconfig`, "Endereço IPv4" do Wi-Fi) e grave de novo. O PC e o ESP32 precisam estar na mesma rede
(o roteador do celular resolve se a rede da faculdade isolar os aparelhos). No Windows, libere a
porta 1883 no firewall na primeira vez que o Docker pedir.

## IPv6

O Mosquitto escuta em IPv4 **e IPv6** (o log mostra `Opening ipv6 listen socket on port 1883`). Teste
que já foi feito: o coletor conectou e gravou os dados usando o endereço IPv6 de loopback:

```bash
MQTT_HOST=::1 python applications/backend/coletor.py
# [MQTT] conectado a ::1:1883
```

A rede da faculdade não entrega IPv6 público (só `fe80::`, de enlace local). Na rede local, qualquer
cliente pode usar o IPv6 do PC (`ipconfig`, "Endereço IPv6"); o ESP32 com a biblioteca atual
(PubSubClient) só conecta por IPv4.

## Alertas no Telegram (bônus)

1. No Telegram, fale com o **@BotFather**, crie um bot e copie o token.
2. Mande uma mensagem para o bot e abra `https://api.telegram.org/bot<TOKEN>/getUpdates` para ver o
   `chat.id`.
3. Crie `applications/.env` (fora do Git) com `TELEGRAM_TOKEN=...` e `TELEGRAM_CHAT_ID=...` e reinicie o
   coletor (`docker compose up -d coletor`).

O coletor avisa quando um poste entra em FALHA, fica offline ou para de mandar telemetria por 30 s.
Sem o `.env`, os alertas aparecem só no log e na tabela `alertas` do banco.
