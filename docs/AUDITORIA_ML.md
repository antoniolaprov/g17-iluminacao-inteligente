# Auditoria de Machine Learning e Backlog de Excelência (Entregáveis CC)

> **Objetivo deste documento:** mapear exatamente **o que já está pronto**, **o que precisa de revisão** e **o que está faltando** na frente de Machine Learning quando comparamos o código atual com a rubrica oficial (**Entregáveis CC – Machine Learning**), além de servir como guia de estudo para toda a equipe defender o projeto na banca.
>
> **Última auditoria:** 26/11/2026 (branch `fase2-central-ml`) · Prazos: **03/12** (relatório CSBC + Git) e **12/12** (Mostra TechDesign).

---

## 1. Resumo Executivo: Estado Atual vs. Rubrica Oficial

| Entregável (CC) | Status | Diagnóstico direto |
|---|---|---|
| **1. Bootstrap dataset + MQTT + persistência** | ✅ **Pronto** | Dados Emlurb preparados (`data/processed/`), ESP32/simulador via MQTT e `coletor.py` gravando em SQLite. |
| **2. Pipeline Airflow + EDA + preparação** | 🟡 **Revisar** | DAG `g17_risco_bairro` existe, mas `preparar_dados` pula se `data/raw/` não estiver presente; `01_exploracao.ipynb` já lê o CSV limpo e não mostra limpeza/nulos/encoding; `treinar.py` ainda aplica `log1p` em `rpa` (categórico) e `mes_do_ano` (cíclico) sem encoding próprio (`ML-13`). |
| **3. Modelo baseline + MLflow (params, métricas, artefatos)** | 🟡 **Revisar** | Há 2 baselines heurísticos (`regra_persistencia`, `regra_media_movel_3m`), mas falta um **baseline clássico de ML** (ex.: `LinearRegression` ou `DecisionTreeRegressor`), e as runs de comparação não logam artefatos no MLflow. |
| **4. Comparação de ≥ 3 modelos + visualizações + análise crítica** | 🟡 **Revisar** | Há 4 modelos de ML (`poisson_glm`, `random_forest`, `gradient_boosting`, `hist_gb_poisson`), mas `02_modelo.ipynb` **não tem gráficos de resíduos**, **dispersão Real × Previsto por ponto** nem **R²**. |
| **5. Otimização de hiperparâmetros (Grid/Random/Optuna) + MLflow** | ❌ **Faltando** | Todos os hiperparâmetros em `treinar.py` foram fixados manualmente (`alpha=1e-3`, `n_estimators=300` etc.). Não existe busca automatizada nem registro de tuning no MLflow. |
| **6. Validação cruzada + estabilidade + overfitting/underfitting** | ✅ **Concluído (`ML-01`)** | `treinar.py` agora executa `TimeSeriesSplit(n_splits=5)` agrupado por `mes_do_alvo` (média ± desvio padrão) e mede erro no ajuste, validação e teste + $R^2$, comprovando overfitting das árvores e estabilidade do `poisson_glm`. |
| **7. Integração consumindo dados novos do embarcado/simulador** | ❌ **Faltando** | O pipeline atual prevê apenas com dados históricos da Emlurb. Embora `coletor.py` salve a telemetria viva do ESP32/simulador no SQLite (`central.db`), **nenhum modelo consome esses dados novos para gerar inferências automaticamente**. |
| **8. Docker Compose (1 comando) + Dashboard + Apresentação** | 🟡 **Revisar** | `docker-compose.yml` funciona, mas `simulador` e `airflow` exigem `--profile`. Dashboard já exibe o risco do ML via MQTT; falta decidir `contagem` vs. `taxa` e preencher `id_ponto`. |

---

## 2. Backlog de Tasks (em ordem de prioridade)

### Prioridade Crítica (Exigido diretamente pela rubrica de ML)

- [x] **ML-01 · Validação cruzada temporal (`TimeSeriesSplit`) e análise de overfitting (`treinar.py`)** *(concluído em 26/11, com refinamento ligado à `ML-02`)*
  - **O que foi feito:** implementado `avaliar_cv_temporal()` com `TimeSeriesSplit(n_splits=5)` agrupado por `mes_do_alvo` (evita vazar bairros do mesmo mês entre treino e validação), cálculo de $R^2$ em `medir()`, e registro de `ajuste_mae`/`ajuste_r2`, `val_mae`/`val_r2`, `gap_val_ajuste_mae`, `cv_*_mean`/`cv_*_std` e `teste_*` no MLflow e em `models/metadados.json`.
  - **Evidência observada (execução de `treinar.py`):**
    - `poisson_glm`: `ajuste_mae = 7.761`, `val_mae = 8.299` (gap `+0.538`), `cv_mae = 8.627 ± 1.278` (menor desvio entre todos), `val_r2 = 0.851`, `teste_mae = 7.804`, `teste_r2 = 0.903`.
    - Árvores com claro *overfitting* no ajuste: `hist_gb_poisson` (`2.816` → `9.947`, gap `+7.131`), `gradient_boosting` (`5.439` → `10.043`, gap `+4.604`), `random_forest` (`4.941` → `9.249`, gap `+4.308`, `cv_std = 1.612`).
  - **Pontos críticos notados após revisão (tratar em `ML-02` e `ML-04`):**
    1. **Paradoxo `val_mae` vs. `cv_mae_mean`:** na média dos 5 folds, `random_forest` deu `cv_mae_mean = 8.283 ± 1.612` (menor que `8.627` do `poisson_glm`), mas o código ainda escolhe o vencedor só por `val_mae` (holdout de 2024). É preciso alinhar o critério de seleção na `ML-02`.
    2. **Erro de treino por fold:** `avaliar_cv_temporal()` hoje guarda apenas o erro de validação de cada fold; registrar também o erro de treino por fold (`cv_ajuste_mae_mean` e histórico fold a fold) permite plotar a curva de aprendizado temporal.

- [ ] **ML-02 · Otimização de hiperparâmetros com registro no MLflow e critério unificado (`treinar.py`)**
  - **Problema atual:** parâmetros de todos os modelos estão fixos no código (`candidatos()` em `treinar.py`), e a seleção final usa apenas `val_mae` ignorando `cv_mae_mean`.
  - **O que fazer:**
    1. Aplicar `GridSearchCV` (ou `RandomizedSearchCV` / `Optuna`) usando o mesmo `TimeSeriesSplit` agrupado por `mes_do_alvo` como `cv` no conjunto de treino — ajustando `alpha`/`fit_intercept` do `PoissonRegressor` e regularizando as árvores (`max_depth`, `min_samples_leaf`, `n_estimators`) para tentar reduzir o overfitting observado na `ML-01`.
    2. Alinhar o critério de seleção do melhor modelo (usar `cv_mae_mean` — ou justificar formalmente o uso da validação mais recente caso o regime de 2024 tenha mudado) para eliminar a contradição `random_forest` vs. `poisson_glm`.
    3. Guardar também o erro de treino por fold na CV (para curva de aprendizado temporal) e registrar no MLflow todas as combinações avaliadas (nested runs ou tag `fase=tuning`).
  - **Pronto quando:** a UI do MLflow mostrar os experimentos de busca de hiperparâmetros, os melhores parâmetros antes do retreino final e não houver contradição entre métrica de CV e modelo escolhido.

- [ ] **ML-13 · Corrigir encoding de variáveis categóricas e cíclicas (`rpa` e `mes_do_ano` no `treinar.py`)** *(descoberta na revisão técnica)*
  - **Problema atual:** `poisson_glm` aplica `FunctionTransformer(np.log1p)` indistintamente sobre **todas as 12 features** — tratando `rpa` (código administrativo de 1 a 6, **categórico**) e `mes_do_ano` (1 a 12, **cíclico**) como grandezas contínuas em escala logarítmica.
  - **O que fazer:**
    1. Substituir o pré-processamento uniforme por um `ColumnTransformer` dentro do pipeline `sklearn`:
       - **One-Hot Encoding** (`OneHotEncoder(handle_unknown="ignore")`) para `rpa`;
       - Encoding **cíclico (`sin`/`cos`)** ou dummies para `mes_do_ano` (ou justificar se mantém sazonalidade explícita);
       - `log1p` + `StandardScaler` apenas nas features numéricas contínuas de contagem/parque.
    2. Garantir que o `ColumnTransformer` fique encapsulado no `Pipeline` salvo em `modelo_risco.joblib`, mantendo o endpoint `POST /prever` da `api.py` funcionando sem quebrar contrato.
  - **Pronto quando:** `treinar.py` rodar com o `ColumnTransformer`, `POST /prever` continuar passando e a seção de encoding no notebook/relatório refletir o pipeline real.

- [ ] **ML-03 · Baseline clássico de ML + artefatos nas runs do MLflow (`treinar.py`)**
  - **Problema atual:** existem baselines heurísticos (`regra_persistencia`, `regra_media_movel_3m`), mas nenhum baseline linear/árvore simples explícito de ML; além disso, as runs de comparação não logam artefatos (só a run `producao_*` loga o modelo).
  - **O que fazer:**
    1. Adicionar um modelo baseline clássico explícito (ex.: `LinearRegression` ou `DecisionTreeRegressor` rasa) na comparação e justificar seu papel no notebook/relatório.
    2. Logar **artefatos** nas runs do MLflow (ex.: tabela comparativa, gráfico de resíduos e gráfico de importância/coeficientes de cada modelo avaliado).
  - **Pronto quando:** todas as runs no MLflow tiverem parâmetros, métricas e artefatos associados.

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
   - **MAE (Erro Absoluto Médio):** medido em *chamados/mês*. **Quanto mais perto de 0, melhor.** (`poisson_glm` no teste: `7,80` vs. média real de `32,7` chamados/mês).
   - **RMSE (Raiz do Erro Quadrático Médio):** penaliza erros grandes ao quadrado. **Quanto mais perto de 0, melhor.** (`poisson_glm` no teste: `12,07`).
   - **$R^2$ (Coeficiente de Determinação):** proporção da variância explicada. **Quanto mais perto de 1, melhor.** (`poisson_glm`: `0,851` na validação e `0,903` no teste).
   - **Precisão no Top 10%:** dos 9 bairros mais críticos previstos no mês, quantos realmente ficaram entre os 9 piores. **Quanto mais perto de 1, melhor.** (`poisson_glm`: `0,80`, acerta ~7,2 de 9 bairros).
   - **Risco (0 a 1):** é o **percentil** relativo entre os 94 bairros no mês previsto — **não é probabilidade** de um poste queimar.

3. **Como funciona o `poisson_glm` e por que ele venceu as árvores?**
   - Pipeline: pré-processamento (`log1p` + `StandardScaler` nas contínuas; `ML-13` adicionará One-Hot em `rpa`) → `PoissonRegressor(alpha=...)`.
   - É um Modelo Linear Generalizado (GLM) próprio para dados de **contagem** ($\ge 0$), com função de ligação logarítmica ($\hat{y} = e^{\beta_0 + \sum \beta_i x_i}$): captura relações proporcionais entre bairros pequenos (Pau Ferro, ~1 chamado) e grandes (Boa Viagem, ~235 chamados) e **extrapola** bem com poucos dados.
   - Árvores (`RandomForest`, `GradientBoosting`, `HistGradientBoosting`) particionam o espaço em degraus, **não extrapolam** acima dos valores vistos e sofrem mais **overfitting** com séries persistentes e poucas linhas de ajuste (~1.880 linhas): `hist_gb_poisson` teve gap `+7,13` entre ajuste e validação, e `random_forest` teve gap `+4,31` e maior variância entre folds (`± 1,61` vs. `± 1,28` do GLM).
   - *Nota sobre os 5 folds iniciais:* nos folds de 2022–2023 o volume ainda era mais estável (favorecendo `random_forest` na média bruta da CV, `8,28` vs. `8,63`), mas na validação mais recente (2024) o volume cresce e o `poisson_glm` generaliza melhor (`8,30` vs. `9,25`).

4. **Por que a `regra_persistencia` empata no Top 10% (0,81 vs. 0,80)?**
   - A série por bairro tem altíssima autocorrelação (bairros grandes como Boa Viagem e Santo Amaro quase sempre lideram). Repetir o mês atual já acerta a ordem dos maiores, mas erra mais na magnitude (**MAE 9,21** vs. **7,80** do `poisson_glm`).

5. **Qual a diferença entre `contagem` e `taxa`?**
   - **Contagem** = volume total de chamados previstos no bairro (responde: *"onde há mais ocorrências absolutas na cidade?"*).
   - **Taxa** = chamados previstos por 1.000 postes (responde: *"onde cada poste individual tem maior chance de falhar?"*). Bairros menores como Cidade Universitária (218 postes) sobem muito na taxa, enquanto Boa Viagem permanece em risco alto nos dois critérios.

6. **Qual é a principal limitação dos dados históricos no treino?**
   - As features de parque (`total_postes`, `pct_led`, `potencia_media_w`) vêm apenas do cadastro de **2025**, aplicadas retroativamente aos chamados de **2022–2024**. Assumimos estabilidade estrutural do parque entre anos, mas declaramos isso como limitação metodológica no relatório (em produção futura, usar snapshot anual do cadastro).
