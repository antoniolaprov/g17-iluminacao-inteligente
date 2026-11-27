# Aplicações (a central)

Tudo o que roda no PC, do lado da "central da prefeitura". O formato das mensagens MQTT está no
[README principal](../README.md#contrato-mqtt) e na seção 7 do [contexto](../docs/CONTEXTO_PARA_IA.md).

| Pasta / arquivo | O que é | Situação |
|---|---|---|
| [`broker/mosquitto.conf`](broker/mosquitto.conf) | Mosquitto local: 1883 (MQTT) e 9001 (WebSocket), IPv4 e IPv6 | Pronto, testado |
| [`broker/mosquitto-ponte.conf`](broker/mosquitto-ponte.conf) | Mosquitto local + ponte com o HiveMQ: a placa fica no broker público, sem regravar, e o PC usa o local | Pronto, testado nos dois sentidos |
| [`backend/coletor.py`](backend/coletor.py) | Assina telemetria, status, risco, evento e travessia e grava em SQLite; alertas de FALHA/offline (Telegram opcional) | Pronto, testado |
| [`simulador/simulador.py`](simulador/simulador.py) + [`cascata.py`](simulador/cascata.py) | Postes virtuais `P02`..`P10`; com `SIM_INCLUIR_P01=1`, também o `P01` com a cascata em Y do firmware v3.0, calibrado com as medidas da placa | Pronto, testado |
| [`dashboard/`](dashboard/) | Dashboard web em tempo real, com o risco do ML e a cascata em Y (3 postes, rota, travessias e acerto do modelo) | Pronto, testado |
| [`ml/`](ml/) | Dados da Emlurb, modelo de risco por bairro, **modelo de rota da cascata** (`src/prever_rota.py`), MLflow, API e DAG do Airflow ([README](ml/README.md)) | Pronto, ver detalhes |
| [`docker-compose.yml`](docker-compose.yml) + [`Dockerfile`](Dockerfile) + [`airflow/Dockerfile`](airflow/Dockerfile) | Sobe tudo em containers | Pronto, testado |
| [`comum.py`](comum.py) | Configuração MQTT compartilhada (variáveis de ambiente) | — |
| **Parque de luminárias (proposta)** | | |
| [`simulador/parque.py`](simulador/parque.py) + [`premissas_parque.json`](simulador/premissas_parque.json) | 500 luminárias simuladas com degradação (Weibull, Arrhenius, surtos, cintilação, L70), calibradas com a Emlurb; gera o histórico e depois publica `g17/luminaria/<id>/telemetria` ao vivo | Pronto, testado |
| [`banco_parque.py`](banco_parque.py) | Banco do parque: PostgreSQL no Docker (`DATABASE_URL`), SQLite fora dele | Pronto, testado |
| [`backend/ingestor_parque.py`](backend/ingestor_parque.py) | MQTT das luminárias → PostgreSQL | Pronto, testado |
| [`ml/src/treinar_falha.py`](ml/src/treinar_falha.py) | Modelo de falha em 14 dias: RF e XGBoost com Optuna, calibração, PR-AUC, baselines, robustez, MLflow | Pronto, testado |
| [`ml/src/pipeline_parque.py`](ml/src/pipeline_parque.py) | Validar → prever → priorizar (CPTED) → dimerizar; é o que o DAG `g17_falha_14d` roda | Pronto, testado |
| [`ml/src/cpted.py`](ml/src/cpted.py) / [`ml/src/dimerizacao.py`](ml/src/dimerizacao.py) | Score CPTED com pesos AHP e sensibilidade / dimerização com pisos CPTED e ABNT e teste de segurança | Pronto, testado |
| [`dashboard_gestor/app.py`](dashboard_gestor/app.py) | Painel do gestor em Streamlit, com mapa (Folium), lista de manutenção, alertas, modelo, CPTED e dimerização | Pronto, testado |
| [`tests/`](tests/) | Testes automáticos (pytest) | Pronto |

---

## Jeito 0: dois cliques

Na raiz do repositório: **`INICIAR_DEMO.bat`** (pergunta se a maquete está ligada, sobe tudo, treina o
que faltar no MLflow e abre as páginas) e **`PARAR_DEMO.bat`** para desligar.

## Jeito 1: tudo no Docker (recomendado para a demonstração)

Precisa do **Docker Desktop** ligado.

```bash
cd applications
docker compose up -d --build            # Mosquitto, PostgreSQL, coletor, MLflow, API, rota, anomalias,
                                        # parque de luminárias, ingestor, pipeline e painel do gestor
docker compose --profile sim up -d      # + postes simulados P02..P10
docker compose run --rm publicar        # manda o risco por bairro para os postes
```

Na **primeira vez**, o serviço `parque` gera 900 dias de histórico das 500 luminárias e grava no
PostgreSQL (uns 2 minutos), e o serviço `pipeline` treina o modelo de falha se ele não existir. Depois
disso, um dia simulado passa a cada 30 s (`PARQUE_DIA_S`), e o pipeline atualiza previsões,
prioridades e dimerização a cada dia novo. Para treinar de novo na mão:
`docker compose run --rm --no-deps pipeline python ml/src/treinar_falha.py`.

| O quê | Onde |
|---|---|
| **Painel do gestor** (mapa, manutenção preditiva, CPTED, dimerização) | http://localhost:8501 |
| Dashboard da maquete | abra `dashboard/index.html?broker=ws://localhost:9001` (ou configure o broker na tela) |
| API de risco | http://localhost:8000/docs |
| MLflow (experimentos e modelo registrado) | http://localhost:5000 |
| Airflow (`docker compose --profile airflow up -d --build`, pesado: ~3 GB na primeira vez) | http://localhost:8080, usuário `admin`, senha: `docker compose exec airflow cat standalone_admin_password.txt`. O DAG é o `g17_risco_bairro`; os scripts rodam num venv próprio (`airflow/Dockerfile`), porque o Airflow traz numpy 1.x e o modelo usa numpy 2 |
| Banco do coletor (maquete) | `backend/dados/central.db` (fora do Git) |
| Banco do parque (PostgreSQL) | `docker compose exec postgres psql -U g17 -d g17` (tabelas em `banco_parque.py`) |
| Logs | `docker compose logs -f coletor` (troque pelo serviço: `parque`, `pipeline`, `ingestor`, `gestor`...) |
| Testes | `docker compose run --rm --no-deps api python -m pytest tests -q` |

Para desligar: `docker compose --profile sim --profile airflow down`.

## Trabalhando sem a maquete (de casa)

A maquete (ESP32 = `P01`) fica na faculdade. Para testar tudo em casa, simule também o `P01`, que vem
com a cascata em Y do firmware v3.0 (S1, S2, eventos, travessias e obediência à previsão de rota):

```bash
cd applications
docker compose up -d --build                             # inclui o serviço de rota (modelo da cascata)
SIM_INCLUIR_P01=1 docker compose --profile sim up -d    # P01..P10 simulados
docker compose run --rm publicar                         # o P01 (Boa Viagem) recebe risco alto -> 90%
```

Com isso o ciclo completo roda em casa: o `P01` simulado manda `evento` ao passar no S1, o serviço de
rota responde `rota` na hora, o simulador acende só o braço previsto, o S2 confirma, a travessia vai para
o banco e o modelo é treinado de novo sozinho quando chegam 30 travessias novas. Ajustes do simulador:
`SIM_PEDESTRE_S` (média de segundos entre pedestres, padrão 12) e `SIM_CONSISTENCIA` (chance de o
pedestre seguir o padrão do lado da rua, padrão 0,85; com 0,5 o caminho é aleatório e nenhum modelo acerta).

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

**Jeito recomendado (sem regravar a placa): ponte com o HiveMQ.** A placa continua publicando no
`broker.hivemq.com`, como está gravada, e o Mosquitto local traz as mensagens do `P01` (telemetria,
status, evento, travessia) e leva de volta só o que é para ela (comando, rota, risco):

```bash
cd applications
MOSQUITTO_CONF=mosquitto-ponte.conf docker compose up -d
```

No PowerShell: `$env:MOSQUITTO_CONF="mosquitto-ponte.conf"; docker compose up -d`. Precisa de internet
no PC e na placa. **Não** ligue o `P01` simulado junto com a ponte.

**Jeito direto:** no firmware, troque `MQTT_BROKER` pelo **IP do PC na rede** (`ipconfig`, "Endereço
IPv4" do Wi-Fi) e grave de novo. O PC e o ESP32 precisam estar na mesma rede (o roteador do celular
resolve se a rede da faculdade isolar os aparelhos). No Windows, libere a porta 1883 no firewall na
primeira vez que o Docker pedir.

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
