# Auditoria de Machine Learning e Backlog de Excelência (Entregáveis CC)

> **Objetivo deste documento:** mapear exatamente **o que já está pronto**, **o que precisa de revisão** e **o que está faltando** na frente de Machine Learning quando comparamos o código atual com a rubrica oficial (**Entregáveis CC – Machine Learning**), além de servir como guia de estudo para toda a equipe defender o projeto na banca.
>
> **Última auditoria:** 26/11/2026 (branch `fase2-central-ml`) · Prazos: **03/12** (relatório CSBC + Git) e **12/12** (Mostra TechDesign).

---

> ### ⚠️ Atualização de 26/11 (noite): alinhamento com a proposta original
>
> Esta auditoria comparou o código com a rubrica de ML, mas **não com a proposta oficial do projeto**
> (*Ideação, Proposição e Planejamento*). A proposta define outro modelo principal: **classificação
> binária de falha da luminária em 14 dias**, treinada com um **simulador de degradação**, com PR-AUC,
> Optuna, calibração, score CPTED (AHP) e dimerização com piso de segurança. Isso foi implementado em
> 26/11; o modelo de risco por bairro descrito abaixo continua, como análise complementar com dados
> reais. Leia primeiro [`ALINHAMENTO_PROPOSTA.md`](ALINHAMENTO_PROPOSTA.md).
>
> Como a rubrica fica com o modelo principal (`falha_14d`):
>
> | Entregável (CC) | Onde está agora |
> |---|---|
> | 1. Bootstrap dataset + MQTT + persistência | Simulador do parque (`simulador/parque.py`) → MQTT `g17/luminaria/+/telemetria` → `ingestor_parque.py` → **PostgreSQL** |
> | 2. Airflow + EDA + preparação | DAGs `g17_falha_14d` (validar → prever → priorizar → dimerizar) e `g17_falha_14d_treino`; limpeza em `parque_features.limpar_telemetria`; EDA em `notebooks/03_falha_14d.ipynb` |
> | 3. Baseline + MLflow | Regra de horas acumuladas, regra de temperatura e aleatório estratificado; experimento `falha_14d` |
> | 4. ≥ 3 modelos + visualizações + análise crítica | 3 baselines + Random Forest + XGBoost (+ calibrado); curvas PR, calibração, importância, robustez no notebook 03 e no painel do gestor |
> | 5. Otimização de hiperparâmetros | Optuna (TPE) com validação walk-forward, cada tentativa no MLflow |
> | 6. Validação cruzada + overfitting | Walk-forward com intervalo de 14 dias; treino/validação/teste temporais; teste de robustez com premissas alteradas |
> | 7. Consumir dados novos do embarcado/simulador | Serviço `pipeline` (e DAG horário) prevê a cada dia novo que chega pelo MQTT e retreina a cada 180 dias novos; detector de anomalias na telemetria dos postes (`anomalia_telemetria.py`) |
> | 8. Docker + dashboard + apresentação | `docker compose up` (ou `INICIAR_DEMO.bat`) sobe tudo, incluindo PostgreSQL e o painel do gestor em Streamlit (http://localhost:8501) |
>
> Situação das tasks abaixo depois desta atualização: **ML-05** feita (anomalias + pipeline do parque),
> **ML-08** feita (`INICIAR_DEMO.bat` + DAGs), **ML-10** feita (`applications/tests/`, 32 testes),
> **ML-11** feita (economia em `dimerizacao.py`, com extrapolação para o Recife). **ML-04** vale agora
> para o notebook 03 (feito) e continua aberta para os notebooks 01/02 do modelo de bairro. **ML-06**
> continua decisão do grupo. **ML-07** depende dos CSVs brutos (fora do Git). **ML-09** depende da placa.
> **ML-12** (K-Means) não foi feita.

## 1. Resumo Executivo: Estado Atual vs. Rubrica Oficial

| Entregável (CC) | Status | Diagnóstico direto |
|---|---|---|
| **1. Bootstrap dataset + MQTT + persistência** | ✅ **Pronto** | Dados Emlurb preparados (`data/processed/`), ESP32/simulador via MQTT e `coletor.py` gravando em SQLite. |
| **2. Pipeline Airflow + EDA + preparação** | 🟡 **Revisar** | DAG `g17_risco_bairro` existe, mas `preparar_dados` pula se `data/raw/` não estiver presente; `01_exploracao.ipynb` já lê o CSV limpo e não mostra limpeza/nulos/encoding. O encoding do pipeline no `treinar.py` foi corrigido em `ML-13`. |
| **3. Modelo baseline + MLflow (params, métricas, artefatos)** | ✅ **Concluído (`ML-03`)** | Além dos 2 baselines heurísticos, `treinar.py` inclui o baseline clássico `baseline_linear` (`LinearRegression`, provando necessidade de Poisson ao prever contagens negativas `-1.71`) e registra artefatos (modelos, pesos, CSV de resíduos e gráficos PNG) em todas as runs do MLflow. |
| **4. Comparação de ≥ 3 modelos + visualizações + análise crítica** | 🟡 **Revisar** | Há 4 modelos de ML (`poisson_glm`, `random_forest`, `gradient_boosting`, `hist_gb_poisson`), mas `02_modelo.ipynb` **não tem gráficos de resíduos**, **dispersão Real × Previsto por ponto** nem **R²**. |
| **5. Otimização de hiperparâmetros (Grid/Random/Optuna) + MLflow** | ✅ **Concluído (`ML-02`)** | `treinar.py` executa Grid Search via `TimeSeriesSplit(n_splits=5)` em todos os modelos treináveis (33 combinações logadas como nested runs `fase=tuning` no MLflow) e grava o histórico por fold (`cv_folds`) em `metadados.json`. |
| **6. Validação cruzada + estabilidade + overfitting/underfitting** | ✅ **Concluído (`ML-01`)** | `treinar.py` agora executa `TimeSeriesSplit(n_splits=5)` agrupado por `mes_do_alvo` (média ± desvio padrão) e mede erro no ajuste, validação e teste + $R^2$, comprovando overfitting das árvores e estabilidade do `poisson_glm`. |
| **7. Integração consumindo dados novos do embarcado/simulador** | ❌ **Faltando** | O pipeline atual prevê apenas com dados históricos da Emlurb. Embora `coletor.py` salve a telemetria viva do ESP32/simulador no SQLite (`central.db`), **nenhum modelo consome esses dados novos para gerar inferências automaticamente**. |
| **8. Docker Compose (1 comando) + Dashboard + Apresentação** | 🟡 **Revisar** | `docker-compose.yml` funciona, mas `simulador` e `airflow` exigem `--profile`. Dashboard já exibe o risco do ML via MQTT; falta decidir `contagem` vs. `taxa` e preencher `id_ponto`. |

---

## 2. Backlog de Tasks (em ordem de prioridade)

### Prioridade Crítica (Exigido diretamente pela rubrica de ML)

- [x] **ML-01 · Validação cruzada temporal (`TimeSeriesSplit`) e análise de overfitting (`treinar.py`)** *(concluído e refinado em 26/11)*
  - **O que foi feito:** implementado `avaliar_cv_temporal()` com `TimeSeriesSplit(n_splits=5)` agrupado por `mes_do_alvo` (evita vazar bairros do mesmo mês entre treino e validação), cálculo de $R^2$ em `medir()`, histórico por fold (treino e validação) em `cv_folds` e registro completo no MLflow e em `models/metadados.json`.

- [x] **ML-02 · Otimização de hiperparâmetros com registro no MLflow e critério unificado (`treinar.py`)** *(concluído em 26/11)*
  - **O que foi feito:** implementado `otimizar_hiperparametros()` com busca em grade (`ParameterGrid`) sobre `TimeSeriesSplit(n_splits=5)` para os 4 modelos treináveis, registrando todas as **33 combinações** avaliadas como nested runs (`fase=tuning`) no MLflow, além de `cv_ajuste_mae_mean`, `cv_gap_mae_mean` e `cv_folds` em `models/metadados.json`. Atualizada a célula 6 de `02_modelo.ipynb` para usar `T.construir_modelo(...)` com os parâmetros otimizados.
  - **Evidência observada (execução de `treinar.py` após tuning):**
    - `poisson_glm` (`alpha=5.0`): `ajuste_mae = 7.605`, `val_mae = 8.667` (gap `+1.062`), `cv_mae = 8.383 ± 1.608` (`cv_gap = +0.919`), `val_r2 = 0.836`, `teste_mae = 8.073`, `teste_rmse = 12.633`, `teste_r2 = 0.893`, `teste_precisao_top10 = 0.796`.
    - Árvores regularizadas reduziram o erro na CV (`random_forest` `8.227 ± 1.687`; `hist_gb_poisson` `8.303 ± 1.637`; `gradient_boosting` `8.357 ± 1.712`), mas mantiveram overfitting alto (`cv_gap` entre `+2.10` e `+3.22`; `val_mae` em 2024 entre `9.33` e `9.60`, atrás da `regra_media_movel_3m = 8.927`). O critério de seleção na validação recente (2024) escolhe `poisson_glm` em total consonância com o menor gap de overfitting.

- [x] **ML-13 · Corrigir encoding de variáveis categóricas e cíclicas (`rpa` e `mes_do_ano` no `treinar.py`)** *(concluído em 26/11)*
  - **O que foi feito:**
    1. Adicionados `codificar_mes_ciclico()` e `nomes_mes_ciclico()` em `preparar_dados.py` (módulo importado por `treinar.py` e `api.py`, evitando falha de desserialização `__main__` no `joblib`/`skops`).
    2. Substituído o pré-processamento uniforme em `treinar.py` por `criar_preprocessador()` (`ColumnTransformer`): `log1p` + `StandardScaler` apenas nas 10 contínuas (no `poisson_glm`), `OneHotEncoder(handle_unknown="ignore")` em `rpa` e `sin`/`cos` em `mes_do_ano` em todos os modelos de ML.
    3. Atualizada a célula 8 de `02_modelo.ipynb` para usar `modelo[:-1].get_feature_names_out()` (18 colunas transformadas).
  - **Evidência e análise crítica (antes vs. depois no `poisson_glm`):**
    - `cv_mae_mean` **melhorou** (`8.627` → **`8.451 ± 1.367`**) e o modelo continua vencendo as regras em todos os splits (`teste_mae = 7.975`, `teste_r2 = 0.897`, `teste_precisao_top10 = 0.796`).
    - **Trade-off honesto:** com `alpha=0.001` (quase sem regularização), `sin`/`cos` reduziu o erro no ajuste (`7.761` → `7.455`) mas elevou `val_mae` (`8.299` → `8.777`, ainda abaixo de `8.927` da média móvel); aumentar `alpha` na `ML-02` tende a corrigir esse pequeno sobreajuste sazonal.
    - Validado `POST /prever` (`api.py`) e `mlflow.sklearn.load_model("models:/risco_bairro/2")` sem erros.
    - *Pendência ligada à `ML-04`:* reexecutar `02_modelo.ipynb` com Jupyter para atualizar as figuras/tabelas embutidas.

- [x] **ML-03 · Baseline clássico de ML + artefatos nas runs do MLflow (`treinar.py`)** *(concluído em 26/11)*
  - **O que foi feito:**
    1. Adicionado `baseline_linear` (`LinearRegression` sobre `ColumnTransformer` sem `log1p`) com tag `tipo_candidato=baseline_ml`: `ajuste_mae = 7.743`, `val_mae = 9.135`, `cv_mae = 8.652 ± 1.337`, `teste_mae = 8.271`, `teste_r2 = 0.899`. Como previsto para regressão linear sem restrição de domínio, chegou a prever valores negativos (`-1.71`) em bairros pequenos — justificando o uso do `poisson_glm`.
    2. Adicionado `logar_artefatos_comparacao()` e `extrair_pesos_modelo()` registrando em **todas** as runs de comparação: modelo MLflow (ou `modelo_regra.json`), `cv_folds.json`, `pesos_features.json`, `residuos_validacao.csv` e (quando `matplotlib` está presente) os gráficos `residuos_validacao.png` e `curva_cv_folds.png`.
  - **Evidência observada:** `MlflowClient().list_artifacts(...)` confirmou os 4–5 artefatos em todas as 7 runs de comparação e `api.saude()` / `api.prever()` seguiram funcionando sem erro.

- [ ] **ML-04 · Visualizações de resíduos, Real × Previsto e R² (`02_modelo.ipynb` e `01_exploracao.ipynb`)**
  - **Problema atual:** `applications/ml/notebooks/02_modelo.ipynb` mostra barras de MAE, série agregada mensal, coeficientes do `poisson_glm` e contagem × taxa, mas **não possui gráficos de resíduos, dispersão Real × Previsto por bairro/mês nem R²**. Já `01_exploracao.ipynb` não documenta explicitamente a limpeza/normalização/tratamento de nulos feitos em `preparar_dados.py`.
  - **O que fazer:**
    1. Em `02_modelo.ipynb`, adicionar:
       - Gráfico de **resíduos** (`y_real - y_previsto` vs. `y_previsto`) e distribuição dos resíduos para os modelos comparados;
       - Gráfico de **dispersão Real × Previsto** com a reta de referência `y = x`;
       - Comparação **Treino × Validação × Teste** e **curva/barras de estabilidade nos 5 folds da CV** (`cv_mae_mean ± cv_mae_std`, evidenciando overfitting das árvores vs. generalização do GLM);
       - Tabela completa incluindo **$R^2$**, **MAE**, **RMSE** e **Precisão Top 10%**.
    2. Em `01_exploracao.ipynb`, adicionar uma seção inicial resumindo (com números e exemplos) as etapas de limpeza, tratamento de datas inválidas, `postes_sem_id`, `BAIRRO NAO INFORMADO`, correção de grafia e normalização/encoding de features (`ML-13`).
    3. **Seção explícita de Limitações (lembrete para o relatório CSBC):** documentar que o cadastro de postes usado como feature estática (`total_postes`, `pct_led`, `potencia_media_w`) é de **2025** aplicado sobre a série de **2022–2025** (suposição de estabilidade do parque, possível *look-ahead* leve nas features estáticas) e que o ranking por **taxa** ainda tem baixa previsibilidade (~0,55 no top 10%).
  - **Pronto quando:** ambos os notebooks estiverem reexecutados com saídas salvas e gráficos prontos para entrar no relatório CSBC.

- [ ] **ML-05 · Pipeline consumindo dados novos do embarcado/simulador (`IsolationForest` / telemetria ao vivo)**
  - **Problema atual:** `coletor.py` grava telemetria em `applications/backend/dados/central.db`, mas o ML só consome CSVs históricos da Emlurb. Isso deixa um gap literal no entregável 7 (*"consumir automaticamente novos dados provenientes do sistema embarcado (ou simulador), executar as etapas de processamento necessárias e produzir inferências"*).
  - **O que fazer:**
    1. Implementar o detector de anomalias na telemetria previsto em `MACHINE_LEARNING.md` §2.3 (ex.: `IsolationForest` em `applications/ml/src/anomalia_telemetria.py`), lendo os novos registros da tabela `telemetria` no SQLite (`central.db`), extraindo features (`luz`, `noite`, `dist`, `presenca`, `desgaste`, `pct`), registrando o experimento no MLflow e publicando o score/alerta de anomalia via API (`GET /anomalias` ou `/poste/{id}`) e/ou MQTT (`g17/poste/<ID>/anomalia`).
    2. Integrar na arquitetura Docker (worker periódico ou endpoint na API + exibição no dashboard).
  - **Pronto quando:** com o simulador ou ESP32 rodando, novas leituras no SQLite gerarem automaticamente scores de anomalia/inferência visíveis na API e no dashboard.

---

### Prioridade Alta (Configuração, Integração, Operação e Entrega)

- [ ] **ML-06 · Decisão operacional `contagem` vs. `taxa` (`applications/ml/config.json`)**
  - **Problema atual:** `criterio_risco` está em `"contagem"`, mas ainda consta como decisão em aberto no `README.md`.
  - **Análise atual:**
    - Em `"contagem"`, `poisson_glm` tem `teste_precisao_top10 = 0.7963`, os 10 postes do `config.json` ficam equilibrados (4 altos, 3 médios, 3 baixos) e o texto do dashboard já exibe `previsao_chamados`.
    - Em `"taxa"`, a precisão no top 10% cai para `0.5463` em todos os modelos (ranking bem mais ruidoso), mas o recorte é essencial no relatório para responder à crítica de viés por tamanho do bairro (Boa Viagem tem 7.013 postes; Cidade Universitária tem 218, mas lidera a taxa por 1.000 postes).
    - Em ambos os critérios, o poste físico `P01` (Boa Viagem) recebe risco **ALTO (90%)**.
  - **O que fazer:** formalizar a escolha no grupo (recomendado: manter `"contagem"` em `config.json` e discutir os dois rankings no relatório/apresentação; se escolher `"taxa"`, atualizar `publicar_risco.py` e `dashboard/index.html` para exibir também `previsao_por_1000_postes`).

- [ ] **ML-07 · Preencher `id_ponto` real no `config.json` e propagar para API/MQTT**
  - **O que fazer:** consultar o CSV bruto de postes da Emlurb (em `data/raw/postes/`, fora do Git), escolher um `id_ponto` real de Boa Viagem para `P01` (e opcionalmente para `P02`..`P10`) e garantir que `/poste/{id}` e `publicar_risco.py` exponham esse ID se desejado na demo.

- [ ] **ML-08 · Revisar fluxo do Airflow e Docker Compose "em um comando"**
  - **O que fazer:**
    1. Verificar se na apresentação `docker compose up -d` já deve subir os serviços essenciais sem depender de múltiplas flags manuais ou documentar exatamente o comando único esperado para a banca.
    2. Garantir que a task `preparar_dados` da DAG `g17_risco_bairro` não pareça "mockada" na demo (ex.: validar o pipeline completo rodando com dados acessíveis no container ou explicar claramente a origem dos dados processados).

- [ ] **ML-09 · Testar o fluxo completo com a maquete física (`P01`) + prints oficiais**
  - **O que fazer:**
    1. Rodar `publicar_risco.py` com o ESP32 conectado ao Mosquitto local e validar a resposta física no LED (90% à noite em Boa Viagem, 100% com pedestre, piso 70%).
    2. Capturar prints nítidos para o relatório CSBC (03/12): UI do **MLflow** (experimentos, tuning e modelo registrado), UI do **Airflow** (DAG verde), Swagger da **API FastAPI** (`/docs`) e **Dashboard** recebendo risco + telemetria ao vivo.

- [ ] **ML-10 · Testes automatizados da camada de ML e Backend**
  - **Problema atual:** não há nenhum teste automatizado no repositório.
  - **O que fazer:** criar testes (`pytest` ou `unittest`) validando `normalizar_bairro()`, carregamento/schema de `risco_por_bairro.csv`, endpoints da API (`/saude`, `/risco/{bairro}`, `/poste/{id}`, `/prever`) e cálculo de métricas.

### Extras Opcionais do Plano (`MACHINE_LEARNING.md`, se sobrar tempo)

- [ ] **ML-11 · Cálculo de economia de energia estimada para o Recife (`MACHINE_LEARNING.md` §2.4)**
  - Usar a coluna `potencia` do cadastro de postes (nunca `consumo_kw`/`consumo_1`) para estimar a economia em kWh/R\$ da dimerização para 70% em horários sem pedestre.
- [ ] **ML-12 · Agrupamento de zonas prioritárias com K-Means (`MACHINE_LEARNING.md` §2.2)**
  - Clusterizar os 94 bairros por volume de chamados e número de postes para reforçar visualmente a priorização CPTED no relatório.

---

## 3. Guia Rápido de Explicabilidade (Estudo Obrigatório para a Banca)

Todo integrante do grupo precisa saber responder estas 5 perguntas sem hesitar:

1. **Por que Regressão (contagem) e não Classificação Binária?**
   - Na agregação por bairro × mês, ~95% dos meses têm pelo menos 1 chamado (`teve_chamado_mes_seguinte = 1`). Qualquer feature tem correlação ≤ 0,15 com o binário — o modelo aprenderia só a responder "sim".
   - Prevendo a **contagem** (`chamados_mes_seguinte`), a correlação histórica chega a **0,89** e transformamos a previsão em um ranking por percentil (0 a 1).
   - *Por isso não usamos matriz de confusão nem ROC/AUC no modelo de bairros:* essas métricas são de classificação binária; para contagem usamos **MAE, RMSE, $R^2$ e Precisão Top 10%**.

2. **Qual a direção de cada métrica? (Não confundir "perto de 0" com "perto de 1"!)**
   - **MAE (Erro Absoluto Médio):** medido em *chamados/mês*. **Quanto mais perto de 0, melhor.** (`poisson_glm` no teste: `8,07` vs. média real de `32,7` chamados/mês).
   - **RMSE (Raiz do Erro Quadrático Médio):** penaliza erros grandes ao quadrado. **Quanto mais perto de 0, melhor.** (`poisson_glm` no teste: `12,63`).
   - **$R^2$ (Coeficiente de Determinação):** proporção da variância explicada. **Quanto mais perto de 1, melhor.** (`poisson_glm`: `0,836` na validação e `0,893` no teste).
   - **Precisão no Top 10%:** dos 9 bairros mais críticos previstos no mês, quantos realmente ficaram entre os 9 piores. **Quanto mais perto de 1, melhor.** (`poisson_glm`: `0,80`, acerta ~7,2 de 9 bairros).
   - **Risco (0 a 1):** é o **percentil** relativo entre os 94 bairros no mês previsto — **não é probabilidade** de um poste queimar.

3. **Como funciona o `poisson_glm` e por que ele venceu as árvores?**
   - Pipeline: `ColumnTransformer` (`log1p` + `StandardScaler` nas contínuas, `OneHotEncoder` em `rpa` e `sin`/`cos` em `mes_do_ano`) → `PoissonRegressor(alpha=5.0)`.
   - É um Modelo Linear Generalizado (GLM) próprio para dados de **contagem** ($\ge 0$), com função de ligação logarítmica ($\hat{y} = e^{\beta_0 + \sum \beta_i x_i}$): captura relações proporcionais entre bairros pequenos (Pau Ferro, ~1 chamado) e grandes (Boa Viagem, ~219 chamados) e **extrapola** bem com poucos dados.
   - Árvores (`RandomForest`, `GradientBoosting`, `HistGradientBoosting`) particionam o espaço em degraus, **não extrapolam** acima dos valores vistos e sofrem mais **overfitting** com séries persistentes e poucas linhas de ajuste (~1.880 linhas): nos 5 folds da CV, o gap médio entre treino e validação foi `+3,22` (`random_forest`) e `+3,19` (`hist_gb_poisson`), contra apenas `+0,92` do `poisson_glm`, que ainda tem menor variância entre folds (`± 1,61` vs. `± 1,69`).
   - *Nota sobre os 5 folds iniciais:* nos folds de 2022–2023 o volume ainda era mais estável (favorecendo árvores na média bruta da CV, `8,23` vs. `8,38`), mas na validação recente de 2024 as árvores perdem até para a `regra_media_movel_3m` (`9,33`–`9,60` vs. `8,93`), enquanto o `poisson_glm` generaliza melhor (`8,67`).

4. **Por que a `regra_persistencia` empata no Top 10% (0,81 vs. 0,80)?**
   - A série por bairro tem altíssima autocorrelação (bairros grandes como Boa Viagem e Santo Amaro quase sempre lideram). Repetir o mês atual já acerta a ordem dos maiores, mas erra mais na magnitude (**MAE 9,21** vs. **8,07** do `poisson_glm`).

5. **Qual a diferença entre `contagem` e `taxa`?**
   - **Contagem** = volume total de chamados previstos no bairro (responde: *"onde há mais ocorrências absolutas na cidade?"*).
   - **Taxa** = chamados previstos por 1.000 postes (responde: *"onde cada poste individual tem maior chance de falhar?"*). Bairros menores como Cidade Universitária (218 postes) sobem muito na taxa, enquanto Boa Viagem permanece em risco alto nos dois critérios.

6. **Qual é a principal limitação dos dados históricos no treino?**
   - As features de parque (`total_postes`, `pct_led`, `potencia_media_w`) vêm apenas do cadastro de **2025**, aplicadas retroativamente aos chamados de **2022–2024**. Assumimos estabilidade estrutural do parque entre anos, mas declaramos isso como limitação metodológica no relatório (em produção futura, usar snapshot anual do cadastro).
