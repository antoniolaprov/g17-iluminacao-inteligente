# Plano de Machine Learning (Grupo 17)

Guia para quem vai desenvolver a parte de machine learning do **Poste de Iluminação Pública Inteligente**.
Leia junto com o [README](README.md), que explica o projeto, e com o [contexto completo](docs/CONTEXTO_PARA_IA.md),
que tem todos os detalhes técnicos e pode ser entregue para uma IA de apoio.

> **Situação em 24/11/2026:** dados baixados e cruzados. O cadastro de postes (2025) e os chamados da
> Central 156 (2022-2025) já foram baixados, o dicionário de dados foi lido e a decisão de cruzar as duas
> bases **por bairro** (não por poste/coordenada) foi tomada e já está implementada. Detalhes, números reais
> e os problemas de qualidade encontrados nos dados (e como foram corrigidos) estão em
> [`applications/ml/README.md`](applications/ml/README.md) — leia antes de mexer nos dados ou treinar o
> modelo.
>
> **Confirmado em 24/11: o ML não é mais "extra".** A disciplina cobra, além do que já estava aqui,
> EDA com visualizações, comparação de modelos, rastreamento de experimentos com **MLflow**,
> orquestração do pipeline com **Airflow**, inferência servida por **API** e **Docker**. Esta seção
> inteira foi reescrita para refletir isso — não é mais o MVP reduzido de versões antigas deste arquivo.
>
> **Notebook de EDA pronto** (`applications/ml/notebooks/01_exploracao.ipynb`), e já rendeu a decisão
> mais importante antes de treinar: o alvo é a **contagem** de chamados do mês seguinte (regressão/
> ranking), não um binário sim/não — o binário tem no máximo 0,15 de correlação com qualquer feature,
> contra até 0,89 na contagem (seção 2.1 e seção 5 do `applications/ml/README.md`). No caminho, um bug
> de digitação no cadastro de postes foi achado e corrigido (3 bairros fantasmas que nunca tinham
> chamado, por erro de grafia, não por serem seguros). **Ainda não feito:** MLflow, modelo treinado,
> Airflow, API, Docker, `publicar_risco.py`.

---

## 1. Onde o ML entra no projeto

O projeto já funciona de ponta a ponta: o ESP32 da maquete lê os sensores, controla a luminária e conversa
por MQTT com um dashboard web. **O ML não roda no ESP32.** Ele roda em Python no computador, no papel da
"central da prefeitura", e fala com o poste pelo mesmo MQTT:

```
Dados abertos da Emlurb ──► Airflow (DAG) ──► preparar dados ──► treinar modelo ──► MLflow (registro)
                                                                       │
                                                                  API (serve o modelo)
                                                                       │
ESP32 (maquete) ── telemetria ──► broker MQTT ◄── comando/risco ──── publicar_risco.py
                                      │
                                  dashboard
```

A ideia central: **a maquete representa um poste real do Recife, tirado do cadastro da Emlurb, e o ML decide
como a central trata esse poste.** O firmware não precisa mudar: ele já aceita comando de potência.
Mosquitto, o coletor, a API e o Airflow rodam como containers Docker (seção 6).

## 2. O que fazer (por prioridade)

### 2.0 Obrigatório: EDA e visualizações

Antes de treinar qualquer modelo: notebook (`notebooks/01_exploracao.ipynb`) com, no mínimo:
- chamados de "lâmpada apagada" por mês (ver a queda abrupta em 2022-2023 documentada no
  [`applications/ml/README.md`](applications/ml/README.md) — isso já é um achado para mostrar);
- chamados por bairro (top 10 e bottom 10);
- distribuição de `tipo_lampa` e `pct_led` por bairro (quanto da cidade já é LED);
- balanço da classe do rótulo (`teve_chamado_mes_seguinte`), que já sabemos estar em ~91% positivo.

### 2.1 Principal: risco de falha (manutenção preditiva)

Prever **quais postes ou bairros têm mais chance de ter chamado de "lâmpada apagada"** no próximo período.

- **Entrada:** características do poste (tipo de lâmpada, tipo de luminária, potência, bairro, RPA, data de
  atualização), features de defasagem (`chamados_lag1/2/3`, `media_movel_3m`) e o histórico de chamados de
  iluminação da região.
- **Rótulo — decidido em 24/11, não é mais sim/não:** a EDA (seção 5 do
  [`applications/ml/README.md`](applications/ml/README.md)) mostrou que o binário "teve chamado no mês
  seguinte" correlaciona no máximo 0,15 com qualquer feature (a classe positiva é ~95% das linhas, não dá
  pra discriminar nada), enquanto a **contagem** de chamados do mês seguinte correlaciona até 0,89 com o
  histórico do bairro. **O alvo é `chamados_mes_seguinte` (regressão/ranking)**, convertido em risco de 0 a
  1 por percentil entre os bairros do mesmo mês.
- **Validação:** split temporal (2022-2024 treino, 2025 teste — já implementado no `preparar_dados.py`),
  nunca aleatório, porque o objetivo é prever o futuro.
- **Modelos a comparar:** pelo menos `RandomForestRegressor` e `GradientBoostingRegressor` do
  scikit-learn, contra uma regra simples (ex.: `media_movel_3m`) e contra a seção 4. **Cada treino é uma
  run do MLflow** (`mlflow.log_param`/`log_metric`/`log_model`), para comparar os experimentos pela UI do
  MLflow (`mlflow ui`) em vez de só print no terminal.
- **Saída:** um número de 0 a 1 (risco, normalizado por percentil a partir da contagem prevista) por
  bairro, servido por uma API (seção 5.2).
- **Ligação com a maquete:** o potenciômetro do poste já simula o **desgaste ao vivo** (acima de 0,70 = falha).
  O modelo dá o **risco histórico**. No dashboard, os dois aparecem juntos: "o modelo previa risco alto e o
  sensor confirmou a falha → mandar a equipe".

### 2.2 Complementar: zonas prioritárias (agrupamento)

Usar **K-means** para agrupar bairros pela quantidade de chamados e de postes. O resultado mostra onde a falta
de luz é mais crítica, o que reforça o argumento de segurança (CPTED). Nessas zonas, a central pode pedir mais
potência.

### 2.3 Extra (só se sobrar tempo): anomalia na telemetria

Treinar um **Isolation Forest** com a telemetria do próprio poste (luz, desgaste, brilho) para avisar quando
algo foge do normal.

### 2.4 Sem ML, mas forte para a apresentação: economia de energia

Com as colunas de potência e consumo do cadastro, calcular quanto o Recife economizaria se cada poste ficasse
em 70% quando não há ninguém na rua. É uma conta simples e dá um número concreto para o relatório.

## 3. Os dados

Portal de dados abertos da Prefeitura do Recife (licença ODbL).

### 3.1 Cadastro de postes de iluminação pública

- **Página:** https://dados.recife.pe.gov.br/dataset/postes-iluminacao-publica-do-recife
- **Arquivos:** um CSV por ano, de 2022 a 2025 (o de 2025 tem cerca de 24 MB).
- **Download direto do CSV de 2025:**
  https://dados.recife.pe.gov.br/dataset/cb834849-e07e-43a1-a101-204b599aaebb/resource/76cb7e65-1362-4ea7-ac04-453d67e41c64/download/iluminacao-publica-do-recife-2025.csv
- **Colunas segundo o dicionário do portal (conferir no arquivo; alguns nomes parecem cortados):**
  `id_ponto`, `sequencia`, `rpa`, `localizaca`, `endereco`, `barrament0`, `latitude`, `longitude`, `bairro`,
  `medicao`, `tipo_lumin`, `tipo_de_po`, `tipo_lampa`, `qtde`, `potencia`, `perdas`, `total_carg`,
  `consumo_kw`, `potencia_1`, `perdas_1`, `total_ca_1`, `consumo_1`, `atualizaca`, `bloq_amp`
- **Atenção:** a descrição do recurso de 2025 no portal fala em "2023", o que parece erro de cópia. Confira o
  ano no conteúdo.

### 3.2 Chamados da Central 156 da Emlurb

- **Página:** https://dados.recife.pe.gov.br/dataset/central-de-atendimento-de-servicos-da-emlurb-156
- **Arquivos:** um CSV por ano, de 2012 a 2026, mais um **dicionário de dados** (PDF e JSON). Baixe o
  dicionário primeiro.
- Tem pedidos de arborização, drenagem, **iluminação**, limpeza e pavimentação. É preciso **filtrar só os de
  iluminação**.
- **Decidido:** o cruzamento é **por bairro**. O campo `BAIRRO` está 100% preenchido nos chamados; já
  `latitude`/`longitude` (que existem no CSV mas não no dicionário) só vêm preenchidas em ~36% dos chamados
  de iluminação, preenchimento baixo demais para ser a fonte principal. Detalhes e números em
  [`applications/ml/README.md`](applications/ml/README.md).

### 3.3 Cuidados com os dados

- **Não suba os CSVs brutos para o GitHub** (são grandes). Guarde em `applications/ml/data/raw/`, que está no
  `.gitignore` sugerido abaixo, e documente no README da pasta de onde baixar.
- **Separe treino e teste por tempo** (por exemplo, treinar com 2022–2024 e testar com 2025), nunca
  aleatoriamente: o objetivo é prever o futuro.
- O rótulo binário "teve chamado" é raro ao contrário (~95% positivo) — foi exatamente por isso que a
  seção 2.1 trocou o alvo para a contagem do mês seguinte (regressão/ranking) em vez de classificação.

## 4. Como avaliar

| O que medir | Por quê |
|---|---|
| **MAE/RMSE da contagem prevista** | Erro básico da regressão (`chamados_mes_seguinte` previsto vs. real) |
| **Precisão no top 10%** | "Dos bairros que o modelo apontou como mais prováveis, quantos de fato tiveram volume alto no mês seguinte?" Métrica de ranking, é a que a Emlurb usaria, e se encaixa na regressão |
| **Comparação com uma regra simples** | Ex.: "risco = `media_movel_3m`" ou "chamados do bairro no ano anterior". O modelo só vale a pena se for melhor que isso |

Coloque esses números no relatório, com um gráfico da importância das variáveis.

## 5. Como integrar com o projeto

### 5.1 Contrato MQTT que já existe (não mudar)

| Tópico | Quem publica | Conteúdo |
|---|---|---|
| `g17/poste/P01/telemetria` | ESP32, a cada 5 s | `{"id":"P01","luz":3013,"noite":0,"dist":17,"presenca":0,"desgaste":0.00,"pct":0,"estado":"DIA","pedido":40,"uptime":163}` |
| `g17/poste/P01/comando` | Central (dashboard ou ML) | `{"potencia":90}` (0 a 100) |
| `g17/poste/P01/status` | ESP32 / broker (LWT) | `online` ou `offline`, retido |

- **Broker atual:** HiveMQ público, `broker.hivemq.com:1883` (o dashboard usa `wss://broker.hivemq.com:8884/mqtt`).
  Para a entrega final o enunciado pede **Mosquitto local**, então deixe o endereço do broker configurável.
- **Regras do firmware que o ML precisa respeitar:**
  - de **dia** a luz fica apagada, seja qual for o comando;
  - à **noite**, o brilho é `max(pedido, 70)`: o ML **só consegue subir acima de 70%**, nunca baixar
    (piso de segurança CPTED);
  - **pedestre** e **fail-safe** sempre vão a 100%.

### 5.2 API de inferência (requisito confirmado em 24/11)

Uma API (FastAPI) separada do MQTT, servindo o modelo treinado/registrado no MLflow:

| Rota | Retorno |
|---|---|
| `GET /risco/{bairro}` | `{"bairro":"...", "risco":0.82, "classe":"alto"}` |
| `GET /saude` | status da API, para o `docker-compose` verificar se o container está de pé |

O `publicar_risco.py` chama essa API (ou carrega o mesmo modelo direto) e publica o resultado no MQTT —
assim a inferência fica disponível **dos dois jeitos**: via API (requisito do ML) e via MQTT (contrato
que o firmware/dashboard já usam).

### 5.3 O que o ML deve publicar no MQTT (proposta)

1. **Comando de potência**, conforme o risco (valores a calibrar):

   | Risco | Potência pedida |
   |---|---|
   | alto (≥ 0,7) | 90 |
   | médio (0,4 a 0,7) | 80 |
   | baixo (< 0,4) | 70 |

2. **Um tópico novo com o risco**, para o dashboard mostrar:
   `g17/poste/P01/risco`, retido, por exemplo
   `{"risco":0.82,"classe":"alto","bairro":"Boa Viagem","id_ponto":"<id do cadastro>","modelo":"rf-v1"}`.
   Mostrar isso no dashboard é uma tarefa separada (`applications/dashboard/index.html`), combinada com quem
   cuida do dashboard.

### 5.4 Ligar a maquete a um poste real

Escolha um poste do cadastro (um `id_ponto` de um bairro com muitos chamados dá uma boa história) e guarde o
mapeamento num arquivo, por exemplo `applications/ml/config.json`:

```json
{ "P01": { "id_ponto": "<id do cadastro>", "bairro": "<bairro>", "potencia_w": 0 } }
```

Com isso, a apresentação pode dizer "esta maquete é o poste X do bairro Y" e o dashboard pode calcular a
economia em watts reais.

### 5.5 Exemplo mínimo de publicação (paho-mqtt)

```python
import json
import paho.mqtt.publish as publish

BROKER = "broker.hivemq.com"   # trocar pelo Mosquitto local na entrega
risco = 0.82                   # vindo do modelo
potencia = 90 if risco >= 0.7 else 80 if risco >= 0.4 else 70

publish.single("g17/poste/P01/comando", json.dumps({"potencia": potencia}), qos=1, hostname=BROKER)
publish.single("g17/poste/P01/risco", json.dumps({"risco": risco, "modelo": "rf-v1"}),
               qos=1, retain=True, hostname=BROKER)
```

Para testar sem a placa, abra o dashboard (`applications/dashboard/index.html`) e veja os eventos, ou rode o
circuito no Wokwi (instruções no README).

## 6. Estrutura sugerida

```
applications/ml/
├── README.md            # como baixar os dados, rodar e o que cada script faz
├── requirements.txt     # pandas, scikit-learn, matplotlib, mlflow, fastapi, uvicorn, paho-mqtt, jupyter
├── config.json          # mapeamento P01 -> poste real
├── Dockerfile           # imagem da API + scripts de treino/publicação
├── docker-compose.yml   # Mosquitto + coletor + API + MLflow + Airflow
├── dags/
│   └── risco_dag.py     # Airflow: preparar_dados -> treinar -> publicar_risco
├── data/
│   ├── raw/             # CSVs baixados do portal (fora do Git)
│   └── processed/       # bases limpas e cruzadas (pequenas podem ir para o Git)
├── notebooks/
│   ├── 01_exploracao.ipynb
│   └── 02_modelo.ipynb
├── mlruns/              # tracking local do MLflow (fora do Git)
├── src/
│   ├── preparar_dados.py
│   ├── treinar.py       # treina, compara e registra os modelos no MLflow
│   ├── api.py            # FastAPI: serve a inferência do modelo registrado
│   └── publicar_risco.py # chama a API/modelo e publica risco + comando no MQTT
└── models/              # modelo treinado (.joblib), se for pequeno
```

E acrescente ao `.gitignore` da raiz:

```
applications/ml/data/raw/
applications/ml/mlruns/
.ipynb_checkpoints/
```

## 7. Cronograma

**O ML não é mais extra** (confirmado em 24/11) — tem o mesmo peso que o resto do que falta
(Mosquitto local, IPv6, simulador, relatório). Com 9 dias até 03/12, o Airflow e o Docker ficam na
versão mais simples possível (1 DAG, `LocalExecutor`, sem Celery/Postgres) só para cumprir o
requisito sem consumir o tempo que falta para o resto.

| Até | Entrega |
|---|---|
| 24/11 | ✅ Dados baixados e cruzados por bairro |
| 24/11 | ✅ Notebook de EDA + visualizações + decisão de alvo (contagem, não binário — seção 2.0/2.1) |
| 27/11 | Modelos de regressão treinados e comparados (RandomForest, GradientBoosting, regra simples), com MLflow registrando cada run |
| 29/11 | API (FastAPI) servindo o modelo escolhido + `publicar_risco.py` publicando no MQTT |
| 30/11 | DAG do Airflow rodando o pipeline completo (preparar → treinar → publicar) |
| 01/12 | `docker-compose` com Mosquitto + coletor + API + Airflow + MLflow, testado de ponta a ponta |
| 03/12 | Resultados (métricas, gráfico de importância de variáveis, prints do MLflow/Airflow) entregues para o relatório |
| 12/12 | Demonstração: maquete = poste real, modelo decide a potência ao vivo |

## 8. Regras do grupo

- **Faça os seus próprios commits.** O GitHub vale 10 pontos e conta "commits colaborativos".
- **Relatório CSBC:** o enunciado só permite IA para **revisão de texto**, com declaração de uso. A seção de
  ML do relatório tem que ser escrita pelo grupo. Declare também o uso de IA no código.
- **Não coloque senhas nem tokens no repositório.**
- Dúvidas sobre o firmware, os tópicos ou o dashboard: fale com o Antônio.
