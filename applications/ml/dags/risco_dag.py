"""
DAG do Airflow: pipeline mensal do risco de lâmpada apagada por bairro.

    preparar_dados -> treinar -> publicar_risco
    treinar_rota e treinar_anomalia (em paralelo)

- preparar_dados: refaz a base cruzada a partir dos CSVs brutos da Emlurb. Os brutos não
  estão no Git; se não existirem, a tarefa só avisa e o pipeline segue com a base
  processada que já está no repositório.
- treinar: compara os modelos, registra tudo no MLflow e atualiza models/ (a API recarrega
  sozinha quando esses arquivos mudam).
- publicar_risco: pega o risco de cada poste na API e publica risco + comando no MQTT.
- treinar_rota: treina o modelo de rota da cascata em Y com as travessias que o coletor gravou
  (placa e simulador) mais as sintéticas, e registra no MLflow (experimento rota_pedestre). O
  serviço de rota passa a usar o modelo novo sozinho.
- treinar_anomalia: treina o detector de anomalias com a telemetria ao vivo que o coletor gravou
  (placa e simulador) e registra no MLflow (experimento anomalia_telemetria). O serviço
  "anomalia" do docker compose também retreina sozinho quando chegam leituras novas.

Mensal porque a Central 156 publica os chamados por mês. Sem catchup: rodar meses
passados não faz sentido, os dados já são o histórico inteiro.

Roda no container do docker-compose.yml (profile "airflow"), que monta applications/
em /opt/airflow/g17. Os scripts rodam no venv G17_PYTHON (ver applications/airflow/Dockerfile),
separado do Python do próprio Airflow.
"""

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

PASTA_ML = os.getenv("G17_ML_DIR", "/opt/airflow/g17/ml")
PYTHON = os.getenv("G17_PYTHON", "python")

with DAG(
    dag_id="g17_risco_bairro",
    description="Prepara os dados da Emlurb, treina o modelo de risco e publica no MQTT",
    schedule="@monthly",
    start_date=datetime(2026, 11, 1),
    catchup=False,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=2)},
    tags=["g17", "ml"],
) as dag:
    preparar_dados = BashOperator(
        task_id="preparar_dados",
        bash_command=(
            f'if [ -d "{PASTA_ML}/data/raw/central156" ] && [ -d "{PASTA_ML}/data/raw/postes" ]; then '
            f'{PYTHON} "{PASTA_ML}/src/preparar_dados.py"; '
            'else echo "Sem os CSVs brutos em data/raw: usando a base processada do repositório."; fi'
        ),
    )

    treinar = BashOperator(
        task_id="treinar",
        bash_command=f'{PYTHON} "{PASTA_ML}/src/treinar.py"',
    )

    publicar_risco = BashOperator(
        task_id="publicar_risco",
        bash_command=f'{PYTHON} "{PASTA_ML}/src/publicar_risco.py"',
    )

    treinar_rota = BashOperator(
        task_id="treinar_rota",
        bash_command=f'{PYTHON} "{PASTA_ML}/src/prever_rota.py" treinar',
    )

    treinar_anomalia = BashOperator(
        task_id="treinar_anomalia",
        bash_command=f'{PYTHON} "{PASTA_ML}/src/anomalia_telemetria.py" treinar',
    )

    preparar_dados >> treinar >> publicar_risco
