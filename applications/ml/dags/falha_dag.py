"""
DAGs do Airflow do parque de luminárias (proposta, itens 02, 03, 07 e 08).

g17_falha_14d (de hora em hora): o pipeline de operação, sobre a telemetria que o ingestor gravou
no PostgreSQL.

    validar_dados -> prever_falha_14d -> priorizar_cpted -> planejar_dimerizacao

- validar_dados: lê os últimos 100 dias de telemetria, remove duplicatas, troca leituras
  impossíveis por ausente, preenche lacunas curtas e registra o relatório (pipeline_execucao);
- prever_falha_14d: calcula os atributos e a P(falha em 14 dias) calibrada de cada luminária;
- priorizar_cpted: ranking de manutenção (risco de falha + score CPTED com pesos AHP) e alertas;
- planejar_dimerizacao: potência por hora com os pisos CPTED e ABNT, teste de segurança
  (critério de aceite: 0% de violações) e economia de energia.

g17_falha_14d_treino (semanal): garante que existe histórico e retreina o modelo.

    garantir_historico -> treinar_falha_14d -> rodar_pipeline

- garantir_historico: se o banco estiver vazio, gera o histórico do parque com o simulador de
  degradação (calibrado com a Emlurb);
- treinar_falha_14d: RF e XGBoost com Optuna (walk-forward), calibração, PR-AUC contra os baselines
  e teste de robustez; tudo no MLflow (experimento falha_14d);
- rodar_pipeline: atualiza previsões, prioridades e dimerização com o modelo novo.

O serviço "pipeline" do docker compose roda as mesmas etapas em laço, para a demo funcionar sem o
Airflow ligado. Os scripts rodam no venv G17_PYTHON (applications/airflow/Dockerfile).
"""

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

APLICACOES = os.getenv("G17_DIR", "/opt/airflow/g17")
PYTHON = os.getenv("G17_PYTHON", "python")
PIPELINE = f'{PYTHON} "{APLICACOES}/ml/src/pipeline_parque.py"'
PADRAO = {"retries": 1, "retry_delay": timedelta(minutes=2)}

with DAG(
    dag_id="g17_falha_14d",
    description="Valida a telemetria das luminárias, prevê a falha em 14 dias, prioriza (CPTED) e planeja a dimerização",
    schedule="@hourly",
    start_date=datetime(2026, 11, 1),
    catchup=False,
    max_active_runs=1,
    default_args=PADRAO,
    tags=["g17", "ml", "parque"],
) as dag_operacao:
    validar = BashOperator(task_id="validar_dados", bash_command=f"{PIPELINE} validar")
    prever = BashOperator(task_id="prever_falha_14d", bash_command=f"{PIPELINE} prever")
    priorizar = BashOperator(task_id="priorizar_cpted", bash_command=f"{PIPELINE} priorizar")
    dimerizar = BashOperator(task_id="planejar_dimerizacao", bash_command=f"{PIPELINE} dimerizar")
    validar >> prever >> priorizar >> dimerizar

with DAG(
    dag_id="g17_falha_14d_treino",
    description="Garante o histórico do parque e retreina o modelo de falha em 14 dias (RF/XGBoost + Optuna + MLflow)",
    schedule="@weekly",
    start_date=datetime(2026, 11, 1),
    catchup=False,
    max_active_runs=1,
    default_args=PADRAO,
    tags=["g17", "ml", "parque"],
) as dag_treino:
    garantir = BashOperator(
        task_id="garantir_historico",
        bash_command=(f'{PYTHON} -c "import sys; sys.path.insert(0, \'{APLICACOES}\'); '
                      f'from banco_parque import contar; sys.exit(0 if contar(\'telemetria_luminaria\') else 1)" '
                      f'|| {PYTHON} "{APLICACOES}/simulador/parque.py" gerar'),
    )
    treinar = BashOperator(task_id="treinar_falha_14d", bash_command=f'{PYTHON} "{APLICACOES}/ml/src/treinar_falha.py"')
    rodar = BashOperator(task_id="rodar_pipeline", bash_command=f"{PIPELINE} tudo")
    garantir >> treinar >> rodar
