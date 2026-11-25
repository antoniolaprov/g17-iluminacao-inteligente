# Imagem única da central: coletor, simulador, API de risco e scripts de ML.
# O código não é copiado: o docker-compose.yml monta a pasta applications/ em /app,
# então editar um script no PC já vale no container (basta reiniciar o serviço).
FROM python:3.12-slim

WORKDIR /app
COPY requirements-central.txt /tmp/requirements-central.txt
RUN pip install --no-cache-dir -r /tmp/requirements-central.txt

ENV PYTHONUNBUFFERED=1 \
    MLFLOW_DISABLE_AGENT_HINT=1
