"""
Ingestor do parque de luminárias: assina g17/luminaria/+/telemetria e grava no banco do parque
(PostgreSQL no Docker), tabela telemetria_luminaria (proposta, item 01: publicação via MQTT com
persistência em PostgreSQL).

Grava em lotes (a cada INGESTOR_LOTE_S segundos) porque o parque manda centenas de leituras de uma
vez a cada dia simulado. Mensagens malformadas são descartadas e contadas, sem parar a ingestão.

Uso:
    python applications/backend/ingestor_parque.py
    (variáveis: MQTT_HOST, MQTT_PORT, DATABASE_URL, INGESTOR_LOTE_S)
"""

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from banco_parque import COLUNAS_TELEMETRIA, gravar, motor, url_banco  # noqa: E402
from comum import MQTT_HOST, MQTT_PORT, novo_cliente  # noqa: E402

LOTE_S = float(os.getenv("INGESTOR_LOTE_S", "2"))


class Ingestor:
    def __init__(self):
        motor()                                   # cria as tabelas se for a primeira vez
        self.buffer, self.trava = [], threading.Lock()
        self.gravadas = self.descartadas = 0

    def ao_conectar(self, cliente, _u, _f, codigo, _p):
        if codigo.is_failure:
            print(f"[INGESTOR] broker recusou: {codigo}", flush=True)
            return
        cliente.subscribe("g17/luminaria/+/telemetria", qos=0)
        print(f"[INGESTOR] conectado a {MQTT_HOST}:{MQTT_PORT}; gravando em {url_banco().split('@')[-1]}", flush=True)

    def ao_receber(self, _c, _u, msg):
        try:
            dados = json.loads(msg.payload.decode("utf-8"))
            dados["id_luminaria"] = dados.get("id_luminaria") or msg.topic.split("/")[2]
            if not dados.get("data"):
                raise ValueError("sem data")
            linha = {c: dados.get(c) for c in COLUNAS_TELEMETRIA}
            linha.update(origem="mqtt", recebido_em=datetime.now().isoformat(timespec="seconds"))
            with self.trava:
                self.buffer.append(linha)
        except (ValueError, KeyError, UnicodeDecodeError):
            self.descartadas += 1

    def gravar_lotes(self) -> None:
        while True:
            time.sleep(LOTE_S)
            with self.trava:
                lote, self.buffer = self.buffer, []
            if not lote:
                continue
            try:
                gravar(pd.DataFrame(lote), "telemetria_luminaria")
                self.gravadas += len(lote)
                print(f"[INGESTOR] +{len(lote)} leituras (total {self.gravadas}, descartadas {self.descartadas})",
                      flush=True)
            except Exception as erro:            # banco fora do ar: devolve o lote e tenta de novo
                print(f"[INGESTOR] erro ao gravar ({erro}); tentando de novo", flush=True)
                with self.trava:
                    self.buffer = lote + self.buffer

    def rodar(self) -> None:
        threading.Thread(target=self.gravar_lotes, daemon=True).start()
        cliente = novo_cliente("ingestor-parque")
        cliente.on_connect, cliente.on_message = self.ao_conectar, self.ao_receber
        cliente.reconnect_delay_set(min_delay=1, max_delay=10)
        cliente.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        cliente.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    try:
        Ingestor().rodar()
    except KeyboardInterrupt:
        print("\nIngestor encerrado.")
