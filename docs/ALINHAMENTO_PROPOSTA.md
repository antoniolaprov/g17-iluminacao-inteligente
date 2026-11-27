# Alinhamento com a proposta original (Ideação, Proposição e Planejamento)

> **Para que serve:** o documento oficial do projeto é a proposta
> *"Proposta de Projeto: Ideação, Proposição e Planejamento — Grupo 17"* (versão FINAL, entregue à
> disciplina). Em 26/11 o repositório foi comparado com ela, e as diferenças estão abaixo, junto com
> o que foi feito para corrigir cada uma. **Quando este repositório e a proposta divergirem, a proposta
> vale**, a não ser que a divergência esteja justificada aqui.
>
> Seções citadas como "g.1", "g.2" etc. são as da seção 7.g da proposta (definições técnicas).

---

## 1. Onde o repositório tinha se afastado da proposta

O firmware, a maquete, o MQTT e o dashboard em tempo real atendem a disciplina de **Sistemas
Embarcados** e continuam valendo. O afastamento estava na parte de **Ciência da Computação / ML**,
que tinha virado um modelo de risco por bairro com os chamados da Emlurb. Esse modelo é bom, mas
**não é o que a proposta definiu**:

| Tema | O que a proposta define | O que o repositório tinha (até 26/11) | Situação agora |
|---|---|---|---|
| **Problema de ML** (g.2) | Classificação binária: para cada luminária e data *t*, P(falha em (*t*, *t*+14 dias]) | Regressão: chamados do bairro no mês seguinte (bairro × mês) | ✅ Modelo `falha_14d` implementado (`ml/src/treinar_falha.py`). O de bairro continua como complemento |
| **Dados do modelo** (g.7) | Treinado e avaliado **inteiramente com dados do simulador**; dados reais só para conferir a coerência do simulador (taxas de falha, sazonalidade) | Treinado com dados reais da Emlurb | ✅ O simulador do parque é calibrado com a Emlurb (2,4%/mês e sazonalidade mensal), que é o uso previsto na g.7 |
| **Simulador de degradação** (g.5) | L70 (LM-80/TM-21), Arrhenius na temperatura, driver como modo de falha dominante, surtos e ciclos, cintilação antes da queima, falha probabilística com fatores latentes e ruído, parâmetros num arquivo versionado, documento de premissas, teste de robustez | Simulador só de estados (dia/noite/pedestre) e desgaste linear por potenciômetro | ✅ `simulador/parque.py` + `simulador/premissas_parque.json` + `docs/PREMISSAS_SIMULADOR.md` |
| **Telemetria** | Parâmetros elétricos e térmicos (tensão, corrente, temperatura, horas, ciclos) | Luz, presença, desgaste, brilho | ✅ Luminárias simuladas publicam `g17/luminaria/<id>/telemetria` com os campos elétricos e térmicos. O contrato dos postes (`g17/poste/...`) não mudou |
| **Protocolo de avaliação** (g.3) | Divisão temporal 70/15/15 com **intervalo de 14 dias**; Optuna com validação walk-forward; **PR-AUC** principal; recall@k, precision@k, ROC-AUC, Brier, F1; baselines regra simples **e** classificador aleatório estratificado; probabilidade **calibrada** | MAE, precisão no top 10% (regressão) | ✅ Implementado como descrito |
| **Modelos** | Random Forest e XGBoost, com Optuna, no MLflow | Poisson GLM, RF, GB, HistGB (regressão) | ✅ RF e XGBoost com Optuna, no MLflow (experimento `falha_14d`) |
| **Banco de dados** | PostgreSQL | SQLite | ✅ PostgreSQL no Docker para a telemetria das luminárias, previsões e prioridades. A maquete continua no SQLite do coletor (ver seção 3) |
| **Pipeline Airflow** (item 02) | DAGs que validam, limpam, normalizam e preparam a telemetria | DAG que só retreina o modelo de bairro | ✅ DAG `g17_falha_14d`: ingestão → validação → features → previsão → priorização |
| **Score CPTED** (g.4) | Critérios (fluxo de pedestres, vulnerabilidade noturna, relevância da via) com pesos **AHP** (CR < 0,10); prioridade = α·P(falha) + (1−α)·CPTED com α = 0,5; análise de sensibilidade ±20% (Spearman e top-k) | Não existia | ✅ `ml/src/cpted.py` |
| **Dimerização** (g.1, g.6) | Potência final = máx(desejada; piso CPTED). Pisos: alta = sem dimerizar no pico noturno e ≥ 80% no resto; média ≥ 70%; baixa ≥ 50%; sem dados = alta. Limite ABNT NBR 5101 (classes P). Fail-safe 100%. Teste automático com **0% de violações** e economia de energia junto | Piso fixo de 70% no firmware | ✅ `ml/src/dimerizacao.py` + teste automático. Firmware mantido (ver seção 3) |
| **Dashboard do gestor** | Streamlit + mapa geoespacial (Folium/PyDeck) com estado, risco e prioridade | Dashboard HTML em tempo real, sem mapa | ✅ `dashboard_gestor/app.py` (Streamlit + Folium). O HTML continua como painel da maquete em tempo real |
| **API** | Endpoints de luminárias, alertas e previsões | Risco por bairro, rota, anomalias | ✅ Novos endpoints `/luminarias`, `/previsoes`, `/prioridades`, `/alertas`, `/dimerizacao` |
| **Docker Compose** | Mosquitto, PostgreSQL, Airflow, MLflow, FastAPI, Streamlit | Sem PostgreSQL e sem Streamlit | ✅ Serviços `postgres`, `parque` e `gestor` adicionados |

### Como foi verificado (26/11)

| Verificação | Resultado |
|---|---|
| Testes automáticos (`applications/tests/`) | 32 passando, incluindo o teste de segurança da dimerização |
| Fluxo ao vivo no Docker | parque → MQTT → ingestor → PostgreSQL → pipeline → API → painel do gestor, rodando |
| DAGs no Airflow | `g17_falha_14d` (validar → prever → priorizar → dimerizar), `g17_falha_14d_treino` (garantir histórico → treinar → rodar pipeline) e `g17_risco_bairro` (com a nova tarefa `treinar_anomalia`): runs verdes |
| Modelo de falha (teste) | XGBoost calibrado: PR-AUC 0,071 (regras 0,020 e 0,038; aleatório 0,010), ROC-AUC 0,77, precision@10 0,12, recall@10 0,23, Brier 0,010. Em três treinos no mesmo dia a PR-AUC de teste variou de 0,067 a 0,098, sempre acima dos baselines |
| Robustez (premissas alteradas) | PR-AUC de 0,034 a 0,058: o modelo perde desempenho fora das premissas exatas (limitação) |
| Score CPTED | CR = 0,008; ranking estável com ±20% nos pesos (Spearman ≥ 0,98, top-20 ≥ 80%) |
| Dimerização | 6.000 comandos, 0 violações; economia de 27% por noite |
| Coerência do simulador com a Emlurb | taxa de 2,46% ao mês (real: 2,39%); sazonalidade com correlação de 0,74 |

Números completos na seção 10.0 do [contexto](CONTEXTO_PARA_IA.md) e no notebook
`applications/ml/notebooks/03_falha_14d.ipynb`.

## 2. O que foi mantido, e por quê

- **Modelo de risco por bairro (Emlurb).** Continua no repositório e na API, como análise
  complementar com dados reais: mostra a sazonalidade e os bairros com mais chamados, e é a base da
  calibração do simulador (g.7). Não é o modelo principal do projeto.
- **Detector de anomalias na telemetria** (`ml/src/anomalia_telemetria.py`). Atende a hipótese da
  funcionalidade 1 da proposta ("tornar mais rápida a identificação de anomalias e falhas") e o
  entregável de consumir dados novos do embarcado.
- **Modelo de rota da cascata em Y.** Faz parte da demonstração da maquete (Embarcados).

- **Perfis históricos por K-Means (T19, 27/11).** Complemento descritivo dos 94 bairros por chamados e
  postes, com notebook, API e painel. Apoia a leitura da demanda sem substituir os critérios AHP,
  o modelo de falha ou os pisos de dimerização. Detalhes em [ZONAS_PRIORITARIAS.md](ZONAS_PRIORITARIAS.md).

## 3. Divergências que continuam, justificadas

| Divergência | Justificativa |
|---|---|
| **Firmware com piso fixo de 70%**, e não 50/70/80% por nível CPTED | A regra de segurança do firmware é da disciplina de Embarcados e não pode ser quebrada. Ela não conflita com a g.6: o firmware só deixa um comando **subir** acima de 70%, então a central aplica os pisos de prioridade alta (80% e 100% no pico) por comando, e o piso de prioridade baixa (50%) fica coberto por um limite mais restritivo (70%). Vale sempre o mais restritivo, como a própria g.6 manda |
| **Maquete no SQLite do coletor**, e não no PostgreSQL | O coletor da maquete, o modelo de rota e o detector de anomalias já estavam testados com SQLite. A proposta pede PostgreSQL para a telemetria do parque de luminárias, e é isso que está lá |
| **Coordenadas das luminárias são aproximadas** | Os dados brutos com latitude/longitude da Emlurb não estão no Git. As luminárias simuladas ficam em volta de coordenadas aproximadas dos 10 bairros do `config.json`; isso é declarado no documento de premissas |
| **Critérios CPTED estimados** | Não há dados abertos de fluxo de pedestres por trecho. Os critérios são sintéticos, com a origem de cada proxy documentada, como a g.4 já prevê ("calibração futura") |

## 4. O que ainda depende do grupo

- Revisar os **pesos AHP** em `ml/src/cpted.py` (a matriz de comparação par a par é uma proposta
  inicial; a g.4 pede que o grupo justifique cada comparação).
- Conferir as **premissas do simulador** (`docs/PREMISSAS_SIMULADOR.md`) e as fontes.
- No relatório, apresentar os resultados como **desempenho sobre dados simulados** (g.5).
