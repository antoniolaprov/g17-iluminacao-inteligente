"""
Modelo de rota do pedestre na cascata em Y (firmware v3.0): ao entrar pelo sensor S1, ele vai
para o braço esquerdo ou para o direito?

Três modos:

    python applications/ml/src/prever_rota.py gerar     # travessias sintéticas (data/processed)
    python applications/ml/src/prever_rota.py treinar   # compara modelos, MLflow, salva o melhor
    python applications/ml/src/prever_rota.py servir    # responde a placa em tempo real (MQTT)

Dados: a tabela "travessia" do banco do coletor (DB_PATH), com o que a placa (origem vazia = real)
e o simulador (origem "simulador") mandaram, mais as travessias sintéticas geradas a partir do
mesmo modelo do simulador (applications/simulador/cascata.py). O resumo do treino mostra quantas
linhas de cada origem entraram, e as métricas só em dados reais aparecem à parte quando houver
pelo menos MIN_REAIS deles: o relatório deve deixar essa separação clara.

Entradas do modelo: dist_s1 (lado da rua em que o pedestre passou pelo S1) e a hora do dia
(seno/cosseno). Alvo: "real" (esquerda/direita), confirmado pelo S2.

Servir: assina g17/poste/+/evento; para cada entrada publica em g17/poste/<ID>/rota
{"direcao": "esquerda", "confianca": 0.87, ...}. O firmware só usa previsões com confiança >= 0,5
e acende o braço previsto antes de o pedestre chegar. A cada RETREINO_S segundos confere se
chegaram pelo menos RETREINO_NOVAS travessias novas no banco; se sim, treina de novo e passa a
usar o modelo novo (consumo automático de dados novos do embarcado).

Variáveis: MQTT_HOST, MQTT_PORT, DB_PATH, MLFLOW_TRACKING_URI, RETREINO_S, RETREINO_NOVAS.
"""

import argparse
import json
import os
import random
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import joblib
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, log_loss
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

RAIZ = Path(__file__).resolve().parent.parent              # applications/ml
APLICACOES = RAIZ.parent                                    # applications
sys.path.insert(0, str(APLICACOES))
sys.path.insert(0, str(APLICACOES / "simulador"))
from cascata import sortear_pedestre  # noqa: E402
from comum import MQTT_HOST, MQTT_PORT, MQTT_PREFIXO, novo_cliente, topico  # noqa: E402

DB_PATH = Path(os.getenv("DB_PATH", APLICACOES / "backend" / "dados" / "central.db"))
SINTETICAS = RAIZ / "data" / "processed" / "travessias_sinteticas.csv"
MODELO = RAIZ / "models" / "modelo_rota.joblib"
METADADOS = RAIZ / "models" / "metadados_rota.json"
EXPERIMENTO = "rota_pedestre"
FEATURES = ["dist_s1", "hora_sin", "hora_cos"]
CLASSES = ["direita", "esquerda"]       # ordem do predict_proba (alfabética, como o sklearn)
MIN_REAIS = 30
SEMENTE = 17


# ---------------- dados ----------------
def gerar_sinteticas(n: int = 800, consistencia: float = 0.85) -> pd.DataFrame:
    """Travessias no formato da placa, com horários espalhados nos últimos 30 dias."""
    rng = random.Random(SEMENTE)
    fim = datetime.now()
    linhas = []
    for _ in range(n):
        p = sortear_pedestre(rng, consistencia)
        quando = fim - timedelta(seconds=rng.uniform(0, 30 * 24 * 3600))
        duracao = int(p["t_s2"] * 1000) if p["real"] == "esquerda" else 4000 + rng.randint(0, 40)
        linhas.append({"recebido_em": quando.isoformat(timespec="seconds"), "id": "P01",
                       "dist_s1": p["dist_s1"], "real": p["real"], "duracao_ms": duracao,
                       "origem": "sintetico"})
    return pd.DataFrame(linhas).sort_values("recebido_em").reset_index(drop=True)


def ler_banco() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame(columns=["recebido_em", "id", "dist_s1", "real", "duracao_ms", "origem"])
    with sqlite3.connect(DB_PATH) as db:
        colunas = {linha[1] for linha in db.execute("PRAGMA table_info(travessia)")}
        if not colunas:
            return pd.DataFrame(columns=["recebido_em", "id", "dist_s1", "real", "duracao_ms", "origem"])
        origem = "origem" if "origem" in colunas else "NULL AS origem"
        df = pd.read_sql(f"SELECT recebido_em, id, dist_s1, real, duracao_ms, {origem} FROM travessia", db)
    df["origem"] = df["origem"].fillna("real")
    return df


def carregar_dados(incluir_sinteticas: bool = True) -> pd.DataFrame:
    partes = [ler_banco()]
    if incluir_sinteticas and SINTETICAS.exists():
        partes.append(pd.read_csv(SINTETICAS))
    df = pd.concat(partes, ignore_index=True)
    df = df[df["real"].isin(CLASSES) & df["dist_s1"].between(0, 400)].copy()
    hora = pd.to_datetime(df["recebido_em"]).dt.hour + pd.to_datetime(df["recebido_em"]).dt.minute / 60
    df["hora_sin"] = np.sin(2 * np.pi * hora / 24)
    df["hora_cos"] = np.cos(2 * np.pi * hora / 24)
    return df.sort_values("recebido_em").reset_index(drop=True)


def features(dist_s1: float, quando: datetime | None = None) -> pd.DataFrame:
    quando = quando or datetime.now()
    hora = quando.hour + quando.minute / 60
    return pd.DataFrame([{"dist_s1": dist_s1, "hora_sin": np.sin(2 * np.pi * hora / 24),
                          "hora_cos": np.cos(2 * np.pi * hora / 24)}])[FEATURES]


# ---------------- modelos ----------------
class RegraLado(ClassifierMixin, BaseEstimator):
    """Regra sem ML: perto do S1 (< 5 cm) = direita, longe = esquerda (o padrão esperado)."""

    def fit(self, X, y):
        self.classes_ = np.array(CLASSES)
        return self

    def predict(self, X):
        return np.where(X["dist_s1"].to_numpy() < 5, "direita", "esquerda")

    def predict_proba(self, X):
        direita = (X["dist_s1"].to_numpy() < 5).astype(float)
        return np.column_stack([direita, 1 - direita])


def candidatos() -> dict:
    return {
        "maioria": (DummyClassifier(strategy="most_frequent"), {"tipo": "baseline"}),
        "regra_lado": (RegraLado(), {"tipo": "regra", "limiar_cm": 5}),
        "regressao_logistica": (make_pipeline(StandardScaler(), LogisticRegression(C=1.0)), {"C": 1.0}),
        "arvore_rasa": (DecisionTreeClassifier(max_depth=3, min_samples_leaf=10, random_state=SEMENTE),
                        {"max_depth": 3, "min_samples_leaf": 10}),
    }


def medir(modelo, X, y, prefixo: str) -> dict:
    previsto = modelo.predict(X)
    proba = np.clip(modelo.predict_proba(X), 1e-6, 1 - 1e-6)
    return {
        f"{prefixo}_acuracia": float(accuracy_score(y, previsto)),
        f"{prefixo}_f1_macro": float(f1_score(y, previsto, average="macro")),
        f"{prefixo}_log_loss": float(log_loss(y, proba, labels=list(modelo.classes_))),
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


def treinar(incluir_sinteticas: bool = True, usar_mlflow: bool = True) -> dict:
    df = carregar_dados(incluir_sinteticas)
    origens = df["origem"].value_counts().to_dict()
    if len(df) < 40 or df["real"].nunique() < 2:
        raise SystemExit(f"Poucas travessias para treinar ({len(df)}; origens {origens}). "
                         "Rode 'gerar' ou colete mais com a placa/simulador.")
    corte = int(len(df) * 0.75)                # treino = 75% mais antigos, teste = 25% mais recentes
    treino, teste = df.iloc[:corte], df.iloc[corte:]
    reais_teste = teste[teste["origem"] == "real"]
    print(f"Travessias: {len(df)} {origens} | treino {len(treino)} | teste {len(teste)} "
          f"(reais no teste: {len(reais_teste)})")

    if usar_mlflow:
        preparar_mlflow()
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEMENTE)
    resultados = {}
    for nome, (modelo, params) in candidatos().items():
        cv_acc = cross_val_score(modelo, treino[FEATURES], treino["real"], cv=cv, scoring="accuracy")
        modelo.fit(treino[FEATURES], treino["real"])
        metricas = {"cv_acuracia_media": float(cv_acc.mean()), "cv_acuracia_desvio": float(cv_acc.std()),
                    **medir(modelo, teste[FEATURES], teste["real"], "teste")}
        if len(reais_teste) >= MIN_REAIS:
            metricas.update(medir(modelo, reais_teste[FEATURES], reais_teste["real"], "teste_reais"))
        resultados[nome] = metricas
        if usar_mlflow:
            with mlflow.start_run(run_name=nome):
                mlflow.log_params({"modelo": nome, "features": ",".join(FEATURES),
                                   "linhas_treino": len(treino), "linhas_teste": len(teste),
                                   **{f"origem_{k}": v for k, v in origens.items()}, **params})
                mlflow.set_tag("fase", "comparacao")
                mlflow.log_metrics(metricas)

    tabela = pd.DataFrame(resultados).T
    print("\nComparação (escolha pela acurácia média na validação cruzada do treino):")
    print(tabela.sort_values("cv_acuracia_media", ascending=False).round(3).to_string())

    treinaveis = ["regressao_logistica", "arvore_rasa"]
    escolhido = max(treinaveis, key=lambda n: resultados[n]["cv_acuracia_media"])
    print(f"\nEscolhido: {escolhido} (cv {resultados[escolhido]['cv_acuracia_media']:.3f}; "
          f"regra do lado {resultados['regra_lado']['cv_acuracia_media']:.3f}; "
          f"maioria {resultados['maioria']['cv_acuracia_media']:.3f})")

    modelo_final, params = candidatos()[escolhido]
    modelo_final.fit(df[FEATURES], df["real"])           # produção: treina com tudo
    MODELO.parent.mkdir(exist_ok=True)
    joblib.dump(modelo_final, MODELO)
    metadados = {
        "treinado_em": datetime.now().isoformat(timespec="seconds"),
        "modelo": escolhido, "parametros": params, "features": FEATURES, "classes": CLASSES,
        "linhas": len(df), "origens": origens,
        "metricas": {n: {k: round(v, 4) for k, v in m.items()} for n, m in resultados.items()},
    }
    METADADOS.write_text(json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8")
    if usar_mlflow:
        with mlflow.start_run(run_name=f"producao_{escolhido}"):
            mlflow.log_params({"modelo": escolhido, "treinado_com": "tudo", "linhas": len(df), **params})
            mlflow.set_tag("fase", "producao")
            mlflow.log_dict(metadados, "metadados_rota.json")
            registrar(modelo_final, df[FEATURES].head(5))
    print(f"Modelo salvo em {MODELO}")
    return metadados


# ---------------- servir ----------------
class Servico:
    def __init__(self):
        self.modelo, self.meta, self.marca = None, {}, None
        self.trava = threading.Lock()
        self.carregar()
        self.contagem_no_treino = self.contar_travessias()

    def carregar(self) -> None:
        if not MODELO.exists():
            raise SystemExit("Modelo de rota não encontrado: rode 'prever_rota.py treinar' antes.")
        marca = MODELO.stat().st_mtime
        if marca != self.marca:
            with self.trava:
                self.modelo = joblib.load(MODELO)
                self.meta = json.loads(METADADOS.read_text(encoding="utf-8")) if METADADOS.exists() else {}
                self.marca = marca
            print(f"[ROTA] modelo carregado: {self.meta.get('modelo')} ({self.meta.get('linhas')} travessias)", flush=True)

    @staticmethod
    def contar_travessias() -> int:
        try:
            with sqlite3.connect(DB_PATH) as db:
                return db.execute("SELECT COUNT(*) FROM travessia").fetchone()[0]
        except sqlite3.Error:
            return 0

    def prever(self, dist_s1: float) -> tuple[str, float]:
        with self.trava:
            proba = self.modelo.predict_proba(features(dist_s1))[0]
            classes = list(self.modelo.classes_)
        i = int(np.argmax(proba))
        return classes[i], float(proba[i])

    def ao_conectar(self, cliente, _u, _f, codigo, _p):
        if not codigo.is_failure:
            cliente.subscribe(f"{MQTT_PREFIXO}/+/evento", qos=1)
            print(f"[ROTA] escutando {MQTT_PREFIXO}/+/evento em {MQTT_HOST}:{MQTT_PORT}", flush=True)

    def ao_receber(self, cliente, _u, msg):
        try:
            evento = json.loads(msg.payload.decode("utf-8", "replace"))
            if evento.get("tipo") != "entrada" or "dist_s1" not in evento:
                return
            poste_id = msg.topic.rsplit("/", 2)[1]
            direcao, confianca = self.prever(float(evento["dist_s1"]))
            resposta = {"direcao": direcao, "confianca": round(confianca, 3),
                        "modelo": self.meta.get("modelo"), "dist_s1": evento["dist_s1"]}
            cliente.publish(topico(poste_id, "rota"), json.dumps(resposta), qos=1)
            print(f"[ROTA] {poste_id}: dist_s1 {evento['dist_s1']} cm -> {direcao} ({confianca:.2f})", flush=True)
        except Exception as erro:  # um evento estranho não pode derrubar o serviço
            print(f"[ROTA] erro: {erro}", flush=True)

    def retreinar_quando_houver_dados(self) -> None:
        intervalo = int(os.getenv("RETREINO_S", "300"))
        minimo = int(os.getenv("RETREINO_NOVAS", "30"))
        while True:
            time.sleep(intervalo)
            agora = self.contar_travessias()
            if agora - self.contagem_no_treino >= minimo:
                print(f"[ROTA] {agora - self.contagem_no_treino} travessias novas: treinando de novo", flush=True)
                try:
                    treinar()
                    self.contagem_no_treino = agora
                    self.carregar()
                except SystemExit as erro:
                    print(f"[ROTA] retreino adiado: {erro}", flush=True)

    def rodar(self) -> None:
        threading.Thread(target=self.retreinar_quando_houver_dados, daemon=True).start()
        cliente = novo_cliente("rota")
        cliente.on_connect = self.ao_conectar
        cliente.on_message = self.ao_receber
        cliente.reconnect_delay_set(min_delay=1, max_delay=10)
        cliente.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        cliente.loop_forever(retry_first_connection=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Modelo de rota do pedestre na cascata em Y")
    sub = parser.add_subparsers(dest="modo", required=True)
    g = sub.add_parser("gerar", help="gera travessias sintéticas no formato da placa")
    g.add_argument("--n", type=int, default=800)
    g.add_argument("--consistencia", type=float, default=0.85)
    t = sub.add_parser("treinar", help="compara modelos, registra no MLflow e salva o melhor")
    t.add_argument("--sem-sinteticas", action="store_true", help="usa só o banco (placa + simulador)")
    t.add_argument("--sem-mlflow", action="store_true")
    sub.add_parser("servir", help="responde os eventos da placa com a previsão de rota")
    args = parser.parse_args()

    if args.modo == "gerar":
        df = gerar_sinteticas(args.n, args.consistencia)
        SINTETICAS.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(SINTETICAS, index=False)
        print(f"{len(df)} travessias sintéticas em {SINTETICAS} ({df['real'].value_counts().to_dict()})")
    elif args.modo == "treinar":
        treinar(incluir_sinteticas=not args.sem_sinteticas, usar_mlflow=not args.sem_mlflow)
    else:
        try:
            Servico().rodar()
        except KeyboardInterrupt:
            print("\nServiço de rota encerrado.")


if __name__ == "__main__":
    main()
