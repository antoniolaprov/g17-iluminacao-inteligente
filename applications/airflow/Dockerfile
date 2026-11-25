# Airflow com um ambiente Python separado para os scripts do projeto.
#
# A imagem oficial do Airflow traz numpy 1.x, e o scikit-learn usado pelo projeto (o mesmo da
# API, para o modelo salvo abrir nos dois lugares) precisa de numpy 2. Em vez de forçar versões
# dentro do Airflow, as tarefas do DAG rodam neste venv (G17_PYTHON).
FROM apache/airflow:2.10.5-python3.12

COPY requirements-central.txt /tmp/requirements-central.txt
RUN python -m venv /home/airflow/g17-venv \
    && /home/airflow/g17-venv/bin/pip install --no-cache-dir -r /tmp/requirements-central.txt

ENV G17_PYTHON=/home/airflow/g17-venv/bin/python \
    MLFLOW_DISABLE_AGENT_HINT=1
