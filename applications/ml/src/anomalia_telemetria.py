"""
Detector de anomalias na telemetria ao vivo dos postes (ML-05 da docs/AUDITORIA_ML.md).

Consome automaticamente os dados novos do sistema embarcado (ESP32 e simulador) que o coletor grava
na tabela "telemetria" do SQLite, pontua cada leitura e publica o resultado no MQTT.

O que ele procura: defeitos que as regras do firmware NÃO pegam, porque o estado do poste continua
parecendo normal. Exemplos: o sensor de luz travado numa leitura (o poste acha que é noite o dia
inteiro e fica aceso de dia), o poste aceso de dia ou apagado à noite, brilho diferente do que as
regras mandariam. O desgaste da lâmpada fica de fora de propósito: ele já tem regra própria (FALHA).

Três modos:

    python applications/ml/src/anomalia_telemetria.py treinar   # compara modelos, MLflow, salva o melhor
    python applications/ml/src/anomalia_telemetria.py servir    # pontua o que chega no banco, publica no MQTT
    python applications/ml/src/anomalia_telemetria.py pontuar   # mostra as últimas leituras pontuadas (teste)

Como a telemetria não tem rótulo de "defeito", a avaliação injeta anomalias conhecidas (os três
defeitos acima, em versões fortes e sutis) num pedaço recente dos dados que o modelo não viu e mede
precisão, recall e F1 nelas. A escolha do modelo é pelo F1 na validação; o teste é medido só para o
relatório. A regra fixa ("qualquer desvio das regras do firmware") entra como linha de base.

Servir: a cada ANOMALIA_S segundos lê as leituras novas do banco, pontua e publica, por poste,
g17/poste/<ID>/anomalia (retido). "alerta" = 1 só quando a anomalia aparece na maioria das leituras do ciclo:
    {"alerta": 1, "anomalo": 1, "score": 0.12, "motivo": "sensor de luz travado (leitura parada)",
     "anomalias": 3, "leituras": 6, "modelo": "isolation_forest", "em": "2026-11-26T21:03:05"}
O coletor grava essas mensagens na tabela "anomalia" e a API mostra em GET /anomalias. Quando o
banco ganha ANOMALIA_RETREINO leituras novas (ou se ainda não houver modelo), treina de novo sozinho.

Variáveis: MQTT_HOST, MQTT_PORT, DB_PATH, MLFLOW_TRACKING_URI, ANOMALIA_S, ANOMALIA_RETREINO.
"""

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

import joblib
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import ParameterGrid
from sklearn.neighbors import LocalOutlierFactor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

RAIZ = Path(__file__).resolve().parent.parent              # applications/ml
APLICACOES = RAIZ.parent                                    # applications
sys.path.insert(0, str(APLICACOES))
from comum import MQTT_HOST, MQTT_PORT, novo_cliente, topico  # noqa: E402

DB_PATH = Path(os.getenv("DB_PATH", APLICACOES / "backend" / "dados" / "central.db"))
MODELO = RAIZ / "models" / "modelo_anomalia.joblib"
METADADOS = RAIZ / "models" / "metadados_anomalia.json"
EXPERIMENTO = "anomalia_telemetria"
SEMENTE = 17
MIN_LINHAS = 300            # menos que isso não dá para treinar (~1 min de 10 postes = 120 linhas)
JANELA_LUZ = 6              # leituras (30 s) para medir se o sensor de luz está "parado"
FRACAO_INJETADA = 0.05      # anomalias injetadas na validação e no teste
TAXA_ALARME_MAX = 0.08      # 5% injetadas + no máximo ~3% de alarme falso
# Postes com defeito simulado de propósito (o P06 do simulador trava o sensor de luz em 1 de cada 3
# dias): ficam fora do treino e da avaliação, porque suas leituras são anomalias reais sem rótulo e
# contariam como "alarme falso". Ao vivo eles são pontuados normalmente: é o teste qualitativo da demo.
EXCLUIR_DO_TREINO = [p.strip() for p in os.getenv("ANOMALIA_EXCLUIR", "P06").split(",") if p.strip()]

# Mesmos limites do firmware (placa física), docs/CONTEXTO_PARA_IA.md seção 8
LIMIAR_NOITE = 2500
LIMIAR_DIA = 2700
PISO_PCT = 70
LUZ_SATURADA = 4000         # o ADC do ESP32 satura no máximo com luz forte: leitura parada lá em cima é normal

# "pct" (brilho aplicado) fica de fora de propósito: ele muda com os comandos da central (dimerização),
# e o modelo passaria a estranhar qualquer comando novo. O que importa é o desvio em relação às regras.
FEATURES = ["luz", "luz_std", "noite", "presenca", "dist", "desvio_pct", "incoerencia_noite"]
# Os três primeiros quebram as regras do firmware (a regra fixa pega); os dois últimos não quebram
# nenhuma regra escrita, e só um modelo que aprendeu o "normal" com os dados consegue estranhar.
TIPOS_ANOMALIA = ["sensor_luz_travado", "aceso_de_dia", "apagado_a_noite",
                  "ultrassonico_inconsistente", "luz_mau_contato"]
LUZ_STD_INSTAVEL = 600      # acima disso a leitura de luz está pulando demais (mau contato)


def salvar_atomico(caminho: Path, escrever) -> None:
    """Grava num arquivo temporário e troca de uma vez (a API nunca lê um arquivo pela metade), com
    permissão 666: os containers rodam com usuários diferentes (root no app, airflow no Airflow) e
    todos precisam conseguir regravar o modelo."""
    temporario = caminho.with_name(caminho.name + ".tmp")
    escrever(temporario)
    os.chmod(temporario, 0o666)
    os.replace(temporario, caminho)


# ---------------- features ----------------
def derivadas(df: pd.DataFrame) -> pd.DataFrame:
    """Features que dependem só da própria leitura. O brilho esperado segue as regras do firmware:
    dia = 0%, pedestre = 100%, senão max(pedido, 70)%."""
    df = df.copy()
    df["dist"] = df["dist"].fillna(999).clip(upper=400)           # 999 = nada detectado
    df["pedido"] = df["pedido"].fillna(40)
    esperado = np.where(df["noite"] == 0, 0,
                        np.where(df["presenca"] == 1, 100, np.maximum(df["pedido"], PISO_PCT)))
    df["desvio_pct"] = df["pct"] - esperado
    df["incoerencia_noite"] = (((df["noite"] == 1) & (df["luz"] > LIMIAR_DIA))
                               | ((df["noite"] == 0) & (df["luz"] < LIMIAR_NOITE))).astype(int)
    return df


def montar_features(df: pd.DataFrame, mediana_luz_std: float | None = None) -> tuple[pd.DataFrame, float]:
    """Telemetria crua (ordenada por chegada) -> features. luz_std é o desvio padrão das últimas
    JANELA_LUZ leituras de luz do mesmo poste: sensor de verdade tem ruído; travado dá zero."""
    df = df.sort_values(["recebido_em"]).copy()
    df["luz_std"] = (df.groupby("id")["luz"]
                       .transform(lambda s: s.rolling(JANELA_LUZ, min_periods=2).std()))
    if mediana_luz_std is None:
        mediana_luz_std = float(df["luz_std"].median()) if df["luz_std"].notna().any() else 50.0
    df["luz_std"] = df["luz_std"].fillna(mediana_luz_std)       # 1ª leitura de cada poste
    return derivadas(df), mediana_luz_std


def motivo(linha: pd.Series) -> str:
    """Explicação simples para o painel: qual regra a leitura parece quebrar."""
    if linha["luz_std"] < 1 and linha["luz"] < LUZ_SATURADA:
        return "sensor de luz travado (leitura parada)"
    if linha["luz_std"] > LUZ_STD_INSTAVEL:
        return "leitura de luz pulando demais (mau contato no sensor)"
    if linha["presenca"] == 1 and linha["dist"] >= 400:
        return "pedestre detectado sem nada perto do ultrassônico"
    if linha["noite"] == 0 and linha["pct"] > 0:
        return "poste aceso de dia"
    if linha["noite"] == 1 and linha["pct"] < PISO_PCT:
        return "apagado ou abaixo do piso de 70% à noite"
    if linha["incoerencia_noite"]:
        return "luz medida e estado dia/noite não batem"
    if linha["desvio_pct"] != 0:
        return "brilho diferente do que as regras mandam"
    return "combinação de leituras incomum"


# ---------------- dados ----------------
def carregar_telemetria(db_path: Path = DB_PATH) -> pd.DataFrame:
    if not db_path.exists():
        return pd.DataFrame()
    with sqlite3.connect(db_path, timeout=10) as db:
        return pd.read_sql_query(
            "SELECT rowid AS linha, recebido_em, id, luz, noite, dist, presenca, pct, pedido, estado "
            "FROM telemetria WHERE luz IS NOT NULL AND pct IS NOT NULL ORDER BY rowid", db)


def injetar_anomalias(df: pd.DataFrame, fracao: float, rng: np.random.Generator) -> tuple[pd.DataFrame, np.ndarray]:
    """Copia o pedaço de avaliação e transforma uma fração das linhas em defeitos conhecidos.
    Metade fortes, metade sutis (perto dos limites), para a métrica não ficar fácil demais."""
    df = df.copy().reset_index(drop=True)
    n = max(3, int(len(df) * fracao))
    idx = rng.choice(len(df), size=n, replace=False)
    rotulo = np.zeros(len(df), dtype=int)
    rotulo[idx] = 1
    for k, i in enumerate(idx):
        tipo = TIPOS_ANOMALIA[k % len(TIPOS_ANOMALIA)]
        sutil = k % 2 == 1
        if tipo == "sensor_luz_travado":       # acha que é noite: fica aceso, leitura parada
            df.loc[i, ["luz", "luz_std", "noite", "presenca", "dist"]] = [
                rng.integers(150, 400) if not sutil else rng.integers(1800, 2400), 0.0, 1, 0, 400]
            df.loc[i, "pct"] = max(df.loc[i, "pedido"], PISO_PCT)
        elif tipo == "aceso_de_dia":           # relé/driver preso: lâmpada acesa com sol
            df.loc[i, ["luz", "noite", "presenca", "dist"]] = [
                rng.integers(3000, 3600) if not sutil else rng.integers(2750, 2950), 0, 0, 400]
            df.loc[i, "pct"] = 100 if not sutil else PISO_PCT
        elif tipo == "apagado_a_noite":        # lâmpada apagada ou abaixo do piso à noite
            df.loc[i, ["luz", "noite", "presenca", "dist"]] = [rng.integers(150, 600), 1, 0, 400]
            df.loc[i, "pct"] = 0 if not sutil else 40
        elif tipo == "ultrassonico_inconsistente":   # diz que tem pedestre, mas não mede nada perto
            df.loc[i, ["presenca", "dist"]] = [1, 400 if not sutil else rng.integers(150, 400)]
            df.loc[i, "pct"] = 100 if df.loc[i, "noite"] == 1 else 0
        else:                                  # mau contato: a leitura de luz pula de um lado para o outro
            df.loc[i, "luz_std"] = rng.uniform(1200, 1800) if not sutil else rng.uniform(700, 1000)
    return derivadas(df), rotulo


def dividir(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Divisão temporal pela ordem de chegada: 60% treino, 20% validação, 20% teste."""
    a, b = int(len(df) * 0.6), int(len(df) * 0.8)
    return df.iloc[:a], df.iloc[a:b], df.iloc[b:]


# ---------------- modelos ----------------
def travado(X: pd.DataFrame) -> pd.Series:
    """Sensor de luz parado na mesma leitura (sem o ruído normal), fora da saturação."""
    return (X["luz_std"] < 1) & (X["luz"] < LUZ_SATURADA)


class RegraFixa:
    """Linha de base: anomalia = qualquer desvio das regras do firmware ou luz parada."""
    def fit(self, X, y=None):
        return self

    def predict(self, X):
        anomalo = (X["desvio_pct"] != 0) | (X["incoerencia_noite"] == 1) | travado(X)
        return np.where(anomalo, -1, 1)

    def decision_function(self, X):
        return -(np.abs(X["desvio_pct"]) / 100 + X["incoerencia_noite"] + travado(X)).to_numpy(float)


class Hibrido:
    """Regra fixa OU modelo: as regras pegam os defeitos conhecidos com certeza, e o modelo, que
    aprendeu o "normal" com os dados, pega as combinações estranhas que nenhuma regra descreve."""
    def __init__(self, modelo):
        self.modelo = modelo
        self.regra = RegraFixa()

    def fit(self, X, y=None):
        self.modelo.fit(X)
        return self

    def predict(self, X):
        return np.where((self.regra.predict(X) == -1) | (self.modelo.predict(X) == -1), -1, 1)

    def decision_function(self, X):
        return self.modelo.decision_function(X) - 10.0 * (self.regra.predict(X) == -1)


def candidatos() -> dict:
    return {
        "isolation_forest": (lambda **p: IsolationForest(random_state=SEMENTE, **p),
                             {"n_estimators": [100, 300], "contamination": [0.005, 0.01, 0.02],
                              "max_features": [1.0, 0.75]}),
        "local_outlier_factor": (lambda **p: make_pipeline(StandardScaler(),
                                                           LocalOutlierFactor(novelty=True, **p)),
                                 {"n_neighbors": [20, 50], "contamination": [0.005, 0.01, 0.02]}),
    }


def medir(modelo, X: pd.DataFrame, rotulo: np.ndarray, prefixo: str) -> dict:
    previsto = (modelo.predict(X[FEATURES]) == -1).astype(int)
    score = -modelo.decision_function(X[FEATURES])
    return {
        f"{prefixo}_precisao": float(precision_score(rotulo, previsto, zero_division=0)),
        f"{prefixo}_recall": float(recall_score(rotulo, previsto, zero_division=0)),
        f"{prefixo}_f1": float(f1_score(rotulo, previsto, zero_division=0)),
        f"{prefixo}_roc_auc": float(roc_auc_score(rotulo, score)),
        f"{prefixo}_taxa_alarme": float(previsto.mean()),
    }


def preparar_mlflow() -> None:
    uri = os.getenv("MLFLOW_TRACKING_URI") or f"sqlite:///{(RAIZ / 'mlflow.db').as_posix()}"
    mlflow.set_tracking_uri(uri)
    if mlflow.get_experiment_by_name(EXPERIMENTO) is None:
        local = uri.startswith("sqlite") or uri.startswith("file")
        mlflow.create_experiment(EXPERIMENTO, artifact_location=(RAIZ / "mlruns").as_uri() if local else None)
    mlflow.set_experiment(EXPERIMENTO)


def registrar(modelo, exemplo: pd.DataFrame) -> None:
    argumentos = {"input_example": exemplo, "registered_model_name": EXPERIMENTO}
    try:
        import skops.io as sio
        argumentos["skops_trusted_types"] = sio.get_untrusted_types(data=sio.dumps(modelo))
    except ImportError:
        pass
    try:
        mlflow.sklearn.log_model(modelo, name="modelo", **argumentos)
    except TypeError:
        argumentos.pop("skops_trusted_types", None)
        mlflow.sklearn.log_model(modelo, artifact_path="modelo", **argumentos)


def treinar(df_cru: pd.DataFrame | None = None, usar_mlflow: bool = True, salvar: bool = True) -> dict:
    df_cru = carregar_telemetria() if df_cru is None else df_cru
    if "id" in df_cru:
        df_cru = df_cru[~df_cru["id"].isin(EXCLUIR_DO_TREINO)]
    if len(df_cru) < MIN_LINHAS:
        raise SystemExit(f"Pouca telemetria para treinar ({len(df_cru)} linhas; mínimo {MIN_LINHAS}). "
                         "Deixe o coletor e o simulador (ou a placa) rodando alguns minutos.")
    df, mediana = montar_features(df_cru)
    treino, validacao, teste = dividir(df)
    rng = np.random.default_rng(SEMENTE)
    val_x, val_y = injetar_anomalias(validacao, FRACAO_INJETADA, rng)
    teste_x, teste_y = injetar_anomalias(teste, FRACAO_INJETADA, rng)
    postes = sorted(df["id"].unique())
    print(f"Telemetria: {len(df)} leituras de {len(postes)} postes | treino {len(treino)} | "
          f"validação {len(val_x)} ({val_y.sum()} injetadas) | teste {len(teste_x)} ({teste_y.sum()} injetadas)")

    if usar_mlflow:
        preparar_mlflow()
    resultados, melhores = {}, {}
    base = RegraFixa()
    resultados["regra_fixa"] = {**medir(base, val_x, val_y, "val"), **medir(base, teste_x, teste_y, "teste")}
    for nome, (fabrica, grade) in candidatos().items():
        melhor = None
        for params in ParameterGrid(grade):
            modelo = fabrica(**params).fit(treino[FEATURES])
            m = medir(modelo, val_x, val_y, "val")
            if usar_mlflow:
                with mlflow.start_run(run_name=f"tuning_{nome}"):
                    mlflow.set_tag("fase", "tuning")
                    mlflow.log_params({"modelo": nome, **params})
                    mlflow.log_metrics(m)
            if melhor is None or m["val_f1"] > melhor[1]["val_f1"]:
                melhor = (params, m, modelo)
        params, m_val, modelo = melhor
        melhores[nome] = params
        resultados[nome] = {**m_val, **medir(modelo, teste_x, teste_y, "teste")}
        # a mesma configuração, combinada com a regra fixa
        hibrido = Hibrido(fabrica(**params)).fit(treino[FEATURES])
        melhores[f"hibrido_{nome}"] = params
        resultados[f"hibrido_{nome}"] = {**medir(hibrido, val_x, val_y, "val"),
                                         **medir(hibrido, teste_x, teste_y, "teste")}

    if usar_mlflow:
        for nome, metricas in resultados.items():
            with mlflow.start_run(run_name=nome):
                mlflow.set_tag("fase", "comparacao")
                mlflow.set_tag("tipo_candidato", "baseline" if nome == "regra_fixa" else "ml")
                mlflow.log_params({"modelo": nome, "features": ",".join(FEATURES), "linhas_treino": len(treino),
                                   "fracao_injetada": FRACAO_INJETADA, **melhores.get(nome, {})})
                mlflow.log_metrics(metricas)

    tabela = pd.DataFrame(resultados).T
    print("\nComparação (escolha pelo F1 na validação com anomalias injetadas):")
    print(tabela[["val_f1", "val_precisao", "val_recall", "teste_f1", "teste_roc_auc",
                  "teste_taxa_alarme"]].sort_values("val_f1", ascending=False).round(3).to_string())

    # Na operação, alarme falso custo caro (equipe na rua à toa): só entram na escolha os candidatos
    # que alarmam em no máximo TAXA_ALARME_MAX das leituras da validação (se nenhum, vale o melhor F1)
    aceitos = [n for n in melhores if resultados[n]["val_taxa_alarme"] <= TAXA_ALARME_MAX] or list(melhores)
    escolhido = max(aceitos, key=lambda n: resultados[n]["val_f1"])
    vence = resultados[escolhido]["val_f1"] >= resultados["regra_fixa"]["val_f1"]
    print(f"\nEscolhido: {escolhido} {melhores[escolhido]} (F1 val {resultados[escolhido]['val_f1']:.3f}; "
          f"regra fixa {resultados['regra_fixa']['val_f1']:.3f}{'' if vence else ' — a regra ganhou'})")

    base_nome = escolhido.removeprefix("hibrido_")
    fabrica = candidatos()[base_nome][0]
    modelo_final = fabrica(**melhores[escolhido])
    if escolhido.startswith("hibrido_"):
        modelo_final = Hibrido(modelo_final)
    modelo_final.fit(df[FEATURES])                                     # produção: treina com tudo
    metadados = {
        "treinado_em": datetime.now().isoformat(timespec="seconds"),
        "modelo": escolhido, "parametros": melhores[escolhido], "features": FEATURES,
        "mediana_luz_std": round(mediana, 3), "janela_luz": JANELA_LUZ, "linhas": len(df), "postes": postes,
        "vence_regra_fixa": bool(vence), "excluidos_do_treino": EXCLUIR_DO_TREINO,
        "metricas": {n: {k: round(v, 4) for k, v in m.items()} for n, m in resultados.items()},
    }
    if salvar:
        MODELO.parent.mkdir(exist_ok=True)
        salvar_atomico(MODELO, lambda f: joblib.dump(modelo_final, f, compress=3))
        salvar_atomico(METADADOS, lambda f: f.write_text(json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8"))
        print(f"Modelo salvo em {MODELO}")
    if usar_mlflow:
        with mlflow.start_run(run_name=f"producao_{escolhido}"):
            mlflow.set_tag("fase", "producao")
            mlflow.log_params({"modelo": escolhido, "treinado_com": "tudo", "linhas": len(df), **melhores[escolhido]})
            mlflow.log_dict(metadados, "metadados_anomalia.json")
            registrar(modelo_final, df[FEATURES].head(5))
    return metadados


# ---------------- serviço ----------------
class Servico:
    def __init__(self):
        self.intervalo = float(os.getenv("ANOMALIA_S", "15"))
        self.retreino = int(os.getenv("ANOMALIA_RETREINO", "2000"))
        self.modelo, self.meta = None, {}
        self.carregar()
        self.janelas = defaultdict(lambda: deque(maxlen=JANELA_LUZ))   # id -> últimas leituras de luz
        self.ultima_linha = 0
        self.linhas_no_treino = self.contar()
        self.treinando = threading.Lock()
        self.cliente = None

    def carregar(self) -> None:
        if MODELO.exists() and METADADOS.exists():
            self.modelo = joblib.load(MODELO)
            self.meta = json.loads(METADADOS.read_text(encoding="utf-8"))
            print(f"[ANOMALIA] modelo {self.meta.get('modelo')} de {self.meta.get('treinado_em')}", flush=True)

    @staticmethod
    def contar() -> int:
        if not DB_PATH.exists():
            return 0
        try:
            with sqlite3.connect(DB_PATH, timeout=10) as db:
                return db.execute("SELECT COUNT(*) FROM telemetria").fetchone()[0]
        except sqlite3.Error:
            return 0

    def treinar_se_preciso(self) -> None:
        if not self.treinando.acquire(blocking=False):   # já tem um treino rodando
            return
        try:
            agora = self.contar()
            if self.modelo is not None and agora - self.linhas_no_treino < self.retreino:
                return
            motivo_treino = "sem modelo" if self.modelo is None else f"{agora - self.linhas_no_treino} leituras novas"
            print(f"[ANOMALIA] treinando ({motivo_treino})", flush=True)
            treinar()
            self.linhas_no_treino = agora
            self.carregar()
        except SystemExit as erro:
            print(f"[ANOMALIA] treino adiado: {erro}", flush=True)
        except Exception as erro:  # MLflow fora do ar etc. não pode derrubar o serviço
            print(f"[ANOMALIA] treino falhou: {erro}", flush=True)
        finally:
            self.treinando.release()

    def novas_leituras(self) -> pd.DataFrame:
        if not DB_PATH.exists():
            return pd.DataFrame()
        with sqlite3.connect(DB_PATH, timeout=10) as db:
            if self.ultima_linha == 0:   # na partida, começa pelos últimos 2 min de cada poste
                self.ultima_linha = max(0, (db.execute("SELECT MAX(rowid) FROM telemetria").fetchone()[0] or 0) - 300)
            return pd.read_sql_query(
                "SELECT rowid AS linha, recebido_em, id, luz, noite, dist, presenca, pct, pedido "
                "FROM telemetria WHERE rowid > ? AND luz IS NOT NULL AND pct IS NOT NULL ORDER BY rowid",
                db, params=(self.ultima_linha,))

    def pontuar(self, df: pd.DataFrame) -> pd.DataFrame:
        """Pontua na ordem de chegada, com a janela de luz de cada poste guardada entre os ciclos."""
        luz_std = []
        for poste_id, luz in zip(df["id"], df["luz"]):
            janela = self.janelas[poste_id]
            janela.append(float(luz))
            luz_std.append(float(np.std(janela, ddof=1)) if len(janela) >= 2 else self.meta.get("mediana_luz_std", 50.0))
        df = df.copy()
        df["luz_std"] = luz_std
        df = derivadas(df)
        df["anomalo"] = (self.modelo.predict(df[FEATURES]) == -1).astype(int)
        df["score"] = -self.modelo.decision_function(df[FEATURES])
        return df

    def ciclo(self) -> None:
        df = self.novas_leituras()
        if df.empty or self.modelo is None:
            return
        self.ultima_linha = int(df["linha"].max())
        df = self.pontuar(df)
        for poste_id, grupo in df.groupby("id"):
            ultima = grupo.iloc[-1]
            pior = grupo.loc[grupo["score"].idxmax()]
            destaque = pior if grupo["anomalo"].any() else ultima
            # alerta só quando a anomalia persiste na maioria das leituras do ciclo (uma leitura
            # estranha isolada não manda ninguém para a rua)
            alerta = int(grupo["anomalo"].sum() >= max(2, (len(grupo) + 1) // 2))
            mensagem = {
                "alerta": alerta,
                "anomalo": int(grupo["anomalo"].iloc[-1]), "score": round(float(ultima["score"]), 3),
                "motivo": motivo(destaque) if grupo["anomalo"].any() else "normal",
                "anomalias": int(grupo["anomalo"].sum()), "leituras": int(len(grupo)),
                "modelo": self.meta.get("modelo"), "em": str(ultima["recebido_em"]),
            }
            self.cliente.publish(topico(poste_id, "anomalia"), json.dumps(mensagem, ensure_ascii=False), qos=1, retain=True)
            if mensagem["alerta"]:
                print(f"[ANOMALIA] {poste_id}: {mensagem['anomalias']}/{mensagem['leituras']} leituras "
                      f"anômalas ({mensagem['motivo']})", flush=True)

    def rodar(self) -> None:
        self.cliente = novo_cliente("anomalia")
        self.cliente.reconnect_delay_set(min_delay=1, max_delay=10)
        self.cliente.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        self.cliente.loop_start()
        print(f"[ANOMALIA] lendo {DB_PATH} a cada {self.intervalo:.0f} s; publicando em {MQTT_HOST}:{MQTT_PORT}",
              flush=True)
        ultimo_treino_checado = 0.0
        while True:
            if time.time() - ultimo_treino_checado > 60:   # treino em paralelo: a pontuação não para
                ultimo_treino_checado = time.time()
                threading.Thread(target=self.treinar_se_preciso, daemon=True).start()
            try:
                self.ciclo()
            except Exception as erro:  # banco ocupado, leitura estranha: tenta de novo no próximo ciclo
                print(f"[ANOMALIA] erro no ciclo: {erro}", flush=True)
            time.sleep(self.intervalo)


def main() -> None:
    parser = argparse.ArgumentParser(description="Detector de anomalias na telemetria dos postes")
    sub = parser.add_subparsers(dest="modo", required=True)
    t = sub.add_parser("treinar", help="compara modelos, registra no MLflow e salva o melhor")
    t.add_argument("--sem-mlflow", action="store_true")
    p = sub.add_parser("pontuar", help="pontua as últimas leituras do banco e mostra na tela")
    p.add_argument("--n", type=int, default=20)
    sub.add_parser("servir", help="pontua o que chega no banco e publica g17/poste/<ID>/anomalia")
    args = parser.parse_args()

    if args.modo == "treinar":
        treinar(usar_mlflow=not args.sem_mlflow)
    elif args.modo == "pontuar":
        servico = Servico()
        if servico.modelo is None:
            raise SystemExit("Sem modelo: rode o modo treinar primeiro.")
        df = carregar_telemetria().tail(args.n + JANELA_LUZ * 12)
        df = servico.pontuar(df).tail(args.n)
        df["motivo"] = [motivo(l) if a else "" for (_, l), a in zip(df.iterrows(), df["anomalo"])]
        print(df[["recebido_em", "id", "luz", "luz_std", "noite", "pct", "desvio_pct", "anomalo", "score",
                  "motivo"]].round(2).to_string(index=False))
    else:
        try:
            Servico().rodar()
        except KeyboardInterrupt:
            print("\nServiço de anomalias encerrado.")


if __name__ == "__main__":
    # Roda pelo módulo importado, para o joblib gravar "anomalia_telemetria.Hibrido" e não
    # "__main__.Hibrido" (senão a API e os testes não conseguem abrir o modelo salvo).
    import anomalia_telemetria
    anomalia_telemetria.main()
