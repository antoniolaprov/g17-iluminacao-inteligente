"""
Coletor da central: assina o MQTT de todos os postes e guarda tudo em SQLite.

- g17/poste/+/telemetria -> tabela telemetria (uma linha por mensagem)
- g17/poste/+/status     -> tabela status     (online/offline)
- g17/poste/+/risco      -> tabela risco      (o que o ML publicou)
- g17/poste/+/travessia  -> tabela travessia  (cascata em Y: previsto x real; dado de treino do
                            modelo de rota)
- g17/poste/+/evento     -> tabela evento     (pedestre entrou pelo S1)
- g17/poste/+/anomalia   -> tabela anomalia   (o que o detector de anomalias do ML publicou)

Também gera alertas (bônus da disciplina) e os grava na tabela alertas:
- o poste entrou em FALHA (desgaste acima de 0,70);
- o poste ficou offline (LWT) ou parou de mandar telemetria por mais de 30 s.

Se TELEGRAM_TOKEN e TELEGRAM_CHAT_ID estiverem definidos, cada alerta também
vai para o Telegram. Sem eles, o alerta só aparece no terminal e no banco.

Uso:
    python applications/backend/coletor.py
    (variáveis: MQTT_HOST, MQTT_PORT, DB_PATH, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
"""

import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comum import MQTT_HOST, MQTT_PORT, MQTT_PREFIXO, novo_cliente  # noqa: E402

DB_PATH = Path(os.getenv("DB_PATH", Path(__file__).resolve().parent / "dados" / "central.db"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SEM_TELEMETRIA_S = 30  # a telemetria chega a cada 5 s; 30 s sem nada = poste sumiu

CAMPOS = ["id", "luz", "noite", "dist", "presenca", "desgaste", "pct", "estado", "pedido", "uptime"]
# Campos da cascata em Y (firmware v3.0). Postes sem a cascata (simulador) mandam sem eles: vira NULL.
CAMPOS_CASCATA = {
    "dist_s2": "REAL", "presenca_s2": "INTEGER", "pct_base": "INTEGER", "pct_esq": "INTEGER",
    "pct_dir": "INTEGER", "rota": "TEXT", "rota_fonte": "TEXT",
}
# "origem" só vem do simulador ("simulador"); o firmware não manda, então NULL = travessia real
CAMPOS_TRAVESSIA = ["id", "dist_s1", "previsto", "fonte", "real", "acertou", "duracao_ms", "uptime", "origem"]

ESQUEMA = """
CREATE TABLE IF NOT EXISTS telemetria (
    recebido_em TEXT NOT NULL,
    id TEXT NOT NULL,
    luz INTEGER, noite INTEGER, dist REAL, presenca INTEGER, desgaste REAL,
    pct INTEGER, estado TEXT, pedido INTEGER, uptime INTEGER
);
CREATE INDEX IF NOT EXISTS idx_telemetria_poste ON telemetria (id, recebido_em);
CREATE TABLE IF NOT EXISTS status (recebido_em TEXT NOT NULL, id TEXT NOT NULL, status TEXT);
CREATE TABLE IF NOT EXISTS risco  (recebido_em TEXT NOT NULL, id TEXT NOT NULL, payload TEXT);
CREATE TABLE IF NOT EXISTS alertas (recebido_em TEXT NOT NULL, id TEXT NOT NULL, tipo TEXT, mensagem TEXT);
CREATE TABLE IF NOT EXISTS travessia (
    recebido_em TEXT NOT NULL, id TEXT NOT NULL, dist_s1 REAL, previsto TEXT, fonte TEXT,
    real TEXT, acertou INTEGER, duracao_ms INTEGER, uptime INTEGER, origem TEXT
);
CREATE TABLE IF NOT EXISTS evento (recebido_em TEXT NOT NULL, id TEXT NOT NULL, payload TEXT);
CREATE TABLE IF NOT EXISTS anomalia (recebido_em TEXT NOT NULL, id TEXT NOT NULL, payload TEXT);
"""


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Coletor:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        # O callback do paho roda numa thread e o vigia em outra: uma conexão
        # compartilhada com trava é mais simples que uma conexão por thread.
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.db.executescript(ESQUEMA)
        # Bancos criados antes da v3.0 nao tem as colunas da cascata: acrescenta sem perder nada
        existentes = {linha[1] for linha in self.db.execute("PRAGMA table_info(telemetria)")}
        for coluna, tipo in CAMPOS_CASCATA.items():
            if coluna not in existentes:
                self.db.execute(f"ALTER TABLE telemetria ADD COLUMN {coluna} {tipo}")
        if "origem" not in {linha[1] for linha in self.db.execute("PRAGMA table_info(travessia)")}:
            self.db.execute("ALTER TABLE travessia ADD COLUMN origem TEXT")
        self.db.commit()
        self.campos = CAMPOS + list(CAMPOS_CASCATA)
        self.trava = threading.Lock()
        self.ultimo_estado = {}      # id -> último estado visto
        self.ultima_telemetria = {}  # id -> time.time() da última telemetria
        self.sumido = set()          # postes já alertados como sem telemetria
        self.mensagens = 0

    # ---------------- banco ----------------
    def gravar(self, sql: str, valores: tuple) -> None:
        with self.trava:
            self.db.execute(sql, valores)
            self.db.commit()

    # ---------------- alertas ----------------
    def alertar(self, poste_id: str, tipo: str, mensagem: str) -> None:
        print(f"[ALERTA] {mensagem}", flush=True)
        self.gravar("INSERT INTO alertas VALUES (?, ?, ?, ?)", (agora(), poste_id, tipo, mensagem))
        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            threading.Thread(target=self.enviar_telegram, args=(mensagem,), daemon=True).start()

    @staticmethod
    def enviar_telegram(texto: str) -> None:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        dados = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": f"Poste G17: {texto}"}).encode()
        try:
            with urllib.request.urlopen(url, data=dados, timeout=10) as resposta:
                retorno = json.load(resposta)
        except urllib.error.HTTPError as erro:
            print(f"[TELEGRAM] falhou (HTTP {erro.code})", flush=True)
            return
        except Exception as erro:
            # A exceção pode conter a URL com o token. Registre apenas o tipo.
            print(f"[TELEGRAM] falhou ({type(erro).__name__})", flush=True)
            return
        if isinstance(retorno, dict) and retorno.get("ok") is True:
            print("[TELEGRAM] alerta aceito pela API", flush=True)
        else:
            print("[TELEGRAM] falhou (envio não confirmado pela API)", flush=True)

    # ---------------- MQTT ----------------
    def ao_conectar(self, cliente, _userdata, _flags, codigo, _props):
        if codigo.is_failure:
            print(f"[MQTT] recusou a conexão: {codigo}", flush=True)
            return
        print(f"[MQTT] conectado a {MQTT_HOST}:{MQTT_PORT}; gravando em {DB_PATH}", flush=True)
        for tipo in ("telemetria", "status", "risco", "travessia", "evento", "anomalia"):
            cliente.subscribe(f"{MQTT_PREFIXO}/+/{tipo}", qos=1)

    def ao_receber(self, _cliente, _userdata, msg):
        try:
            _, poste_id, tipo = msg.topic.rsplit("/", 2)
            texto = msg.payload.decode("utf-8", "replace").strip()
            if tipo == "telemetria":
                self.tratar_telemetria(poste_id, texto)
            elif tipo == "status":
                self.tratar_status(poste_id, texto, retido=msg.retain)
            elif tipo == "risco":
                self.gravar("INSERT INTO risco VALUES (?, ?, ?)", (agora(), poste_id, texto))
            elif tipo == "travessia":
                dados = json.loads(texto)
                dados.setdefault("id", poste_id)
                self.gravar(
                    f"INSERT INTO travessia (recebido_em, {', '.join(CAMPOS_TRAVESSIA)}) "
                    f"VALUES (?{', ?' * len(CAMPOS_TRAVESSIA)})",
                    (agora(), *[dados.get(c) for c in CAMPOS_TRAVESSIA]),
                )
            elif tipo == "evento":
                self.gravar("INSERT INTO evento VALUES (?, ?, ?)", (agora(), poste_id, texto))
            elif tipo == "anomalia":
                self.gravar("INSERT INTO anomalia VALUES (?, ?, ?)", (agora(), poste_id, texto))
        except Exception as erro:  # uma mensagem malformada não pode parar a coleta
            print(f"[ERRO] {msg.topic}: {erro}", flush=True)

    def tratar_telemetria(self, poste_id: str, texto: str) -> None:
        dados = json.loads(texto)
        dados.setdefault("id", poste_id)
        self.gravar(
            f"INSERT INTO telemetria (recebido_em, {', '.join(self.campos)}) VALUES (?{', ?' * len(self.campos)})",
            (agora(), *[dados.get(c) for c in self.campos]),
        )
        self.mensagens += 1
        self.ultima_telemetria[poste_id] = time.time()
        self.sumido.discard(poste_id)

        estado = dados.get("estado")
        if estado == "FALHA" and self.ultimo_estado.get(poste_id) != "FALHA":
            self.alertar(poste_id, "falha",
                         f"poste {poste_id} em FALHA (desgaste {dados.get('desgaste', 0):.2f}); chamar manutenção")
        self.ultimo_estado[poste_id] = estado

    def tratar_status(self, poste_id: str, texto: str, retido: bool) -> None:
        self.gravar("INSERT INTO status VALUES (?, ?, ?)", (agora(), poste_id, texto))
        # Um "offline" retido chega na hora em que o coletor conecta e pode ser
        # antigo; só alerta o que acontece com o coletor já rodando.
        if texto == "offline" and not retido:
            self.alertar(poste_id, "offline", f"poste {poste_id} ficou offline")

    def vigiar(self) -> None:
        """Avisa uma vez quando um poste para de mandar telemetria."""
        while True:
            time.sleep(5)
            for poste_id, quando in list(self.ultima_telemetria.items()):
                if time.time() - quando > SEM_TELEMETRIA_S and poste_id not in self.sumido:
                    self.sumido.add(poste_id)
                    self.alertar(poste_id, "sem_telemetria",
                                 f"poste {poste_id} sem telemetria há mais de {SEM_TELEMETRIA_S} s")

    def rodar(self) -> None:
        cliente = novo_cliente("coletor")
        cliente.on_connect = self.ao_conectar
        cliente.on_message = self.ao_receber
        cliente.reconnect_delay_set(min_delay=1, max_delay=10)
        threading.Thread(target=self.vigiar, daemon=True).start()
        print(f"[MQTT] conectando a {MQTT_HOST}:{MQTT_PORT}...", flush=True)
        cliente.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        cliente.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    try:
        Coletor().rodar()
    except KeyboardInterrupt:
        print("\nColetor encerrado.")
