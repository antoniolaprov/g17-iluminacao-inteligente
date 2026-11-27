"""
Modelo de manutenção preditiva: probabilidade de a luminária falhar nos próximos 14 dias
(proposta, funcionalidade 2, seções g.2, g.3 e g.5; item 03 do backlog).

Protocolo (g.3):
    - divisão temporal: treino (~70% dos dias), validação (~15%) e teste (~15%), com um intervalo de
      14 dias entre os conjuntos (o rótulo olha 14 dias à frente);
    - Optuna com validação walk-forward (janela expansiva) dentro do treino;
    - métrica principal: PR-AUC (average precision); secundárias: recall@k e precision@k (k = equipe
      consegue inspecionar k luminárias por quinzena), ROC-AUC, Brier e F1 no limiar operacional;
    - baselines: regra simples (horas acumuladas ou temperatura) e classificador aleatório
      estratificado; o modelo só vale se vencer os dois na PR-AUC;
    - probabilidade calibrada (Platt ou isotônica, a que tiver o menor Brier na 2ª metade da
      validação), para o valor virar "risco" no painel e entrar no score de prioridade;
    - teste usado uma vez só, no fim;
    - teste de robustez (g.5): o modelo é avaliado em dados gerados com premissas alteradas.
Tudo vai para o MLflow (experimento falha_14d) e o modelo calibrado é registrado como falha_14d.

Dados: a telemetria do banco do parque (PostgreSQL no Docker), que tem o histórico gerado pelo
simulador e o que chegou depois por MQTT. Sem banco, gera o histórico na hora (parque.gerar_dados).

Uso:
    python applications/ml/src/treinar_falha.py              # treino completo (alguns minutos)
    python applications/ml/src/treinar_falha.py --rapido     # menos tentativas do Optuna (teste)
    (variáveis: DATABASE_URL, MLFLOW_TRACKING_URI, FALHA_TRIALS)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import joblib
import mlflow
import mlflow.sklearn
import numpy as np
import optuna
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import average_precision_score, brier_score_loss, f1_score, precision_recall_curve, roc_auc_score
from xgboost import XGBClassifier

RAIZ = Path(__file__).resolve().parent.parent              # applications/ml
APLICACOES = RAIZ.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(APLICACOES))
sys.path.insert(0, str(APLICACOES / "simulador"))
from parque_features import FEATURES, JANELA_DIAS, construir_features, limpar_telemetria, linhas_para_modelo, rotular  # noqa: E402

MODELO = RAIZ / "models" / "modelo_falha.joblib"
METADADOS = RAIZ / "models" / "metadados_falha.json"
EXPERIMENTO = "falha_14d"
SEMENTE = 17
CAPACIDADE_K = int(os.getenv("FALHA_CAPACIDADE_K", "10"))   # inspeções por quinzena (2% de 500)
FRACAO_NEGATIVOS = 0.25    # no treino, 1 em cada 4 negativos (todos os positivos): mais rápido;
                           # a calibração na validação (com todas as linhas) corrige as probabilidades
CENARIOS_ROBUSTEZ = {
    "noites_mais_quentes_+3C": {"temperatura.ambiente_noite_c": 28.5},
    "surtos_em_dobro": {"surtos.taxa_dia": 0.02},
    "lote_mais_irregular": {"driver.sigma_latente": 0.9},
}


def salvar_atomico(caminho: Path, escrever) -> None:
    """Grava num arquivo temporário e troca de uma vez (a API nunca lê um arquivo pela metade), com
    permissão 666: os containers rodam com usuários diferentes (root no app, airflow no Airflow) e
    todos precisam conseguir regravar o modelo."""
    temporario = caminho.with_name(caminho.name + ".tmp")
    escrever(temporario)
    os.chmod(temporario, 0o666)
    os.replace(temporario, caminho)


# ---------------- dados ----------------
def carregar_dados() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    from banco_parque import contar, ler
    if contar("telemetria_luminaria") > 0:
        return ler("SELECT * FROM luminaria"), ler("SELECT * FROM telemetria_luminaria"), "banco"
    from parque import gerar_dados
    catalogo, telemetria, _, _ = gerar_dados()
    return catalogo, telemetria, "gerado_na_hora"


def preparar(catalogo: pd.DataFrame, telemetria: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    limpo, relatorio = limpar_telemetria(telemetria)
    df = rotular(construir_features(limpo, catalogo))
    df = df[linhas_para_modelo(df)].reset_index(drop=True)
    return df, relatorio


def dividir(df: pd.DataFrame) -> dict:
    """Treino / validação / teste por data, com intervalo de 14 dias entre eles."""
    inicio = df["data"].min() + pd.Timedelta(days=30)       # 1º mês: janelas de 30 dias incompletas
    fim = df["data"].max() - pd.Timedelta(days=JANELA_DIAS)  # rótulo do teste precisa dos 14 dias
    dias = (fim - inicio).days
    corte1 = inicio + pd.Timedelta(days=int(dias * 0.70))
    corte2 = inicio + pd.Timedelta(days=int(dias * 0.85))
    gap = pd.Timedelta(days=JANELA_DIAS)
    completo = df["rotulo_completo"]
    partes = {
        "treino": df[(df["data"] >= inicio) & (df["data"] <= corte1 - gap) & completo],
        "validacao": df[(df["data"] >= corte1) & (df["data"] <= corte2 - gap) & completo],
        "teste": df[(df["data"] >= corte2) & (df["data"] <= fim) & completo],
    }
    return partes


def amostrar(df: pd.DataFrame, semente: int = SEMENTE) -> pd.DataFrame:
    rng = np.random.default_rng(semente)
    manter = (df["y"] == 1) | (rng.uniform(size=len(df)) < FRACAO_NEGATIVOS)
    return df[manter]


def folds_walk_forward(treino: pd.DataFrame, n: int = 3):
    """Janela expansiva dentro do treino: treina até o dia D, valida de D+14 até o próximo corte."""
    datas = np.sort(treino["data"].unique())
    cortes = np.linspace(0, len(datas), n + 2).astype(int)[1:]
    for i in range(n):
        fim_treino = datas[cortes[i] - 1]
        ini_val = fim_treino + np.timedelta64(JANELA_DIAS, "D")
        fim_val = datas[min(cortes[i + 1], len(datas)) - 1]
        a = treino[treino["data"] <= fim_treino - np.timedelta64(JANELA_DIAS, "D")]
        b = treino[(treino["data"] >= ini_val) & (treino["data"] <= fim_val)]
        if b["y"].sum() > 0 and a["y"].sum() > 0:
            yield a, b


# ---------------- métricas ----------------
def em_k(df: pd.DataFrame, prob: np.ndarray, k: int = CAPACIDADE_K) -> tuple[float, float]:
    """precision@k e recall@k médios por data: das k luminárias de maior risco em cada dia, quantas
    falharam nos 14 dias seguintes, e que fração das que falharam estava entre elas."""
    t = pd.DataFrame({"data": df["data"].to_numpy(), "y": df["y"].to_numpy(), "p": prob})
    precisoes, recalls = [], []
    for _, dia in t.groupby("data"):
        topo = dia.nlargest(k, "p")
        precisoes.append(topo["y"].sum() / k)
        if dia["y"].sum() > 0:
            recalls.append(topo["y"].sum() / dia["y"].sum())
    return float(np.mean(precisoes)), float(np.mean(recalls)) if recalls else 0.0


def medir(df: pd.DataFrame, prob: np.ndarray, prefixo: str, limiar: float | None = None) -> dict:
    y = df["y"].to_numpy()
    p_k, r_k = em_k(df, prob)
    m = {f"{prefixo}_pr_auc": float(average_precision_score(y, prob)),
         f"{prefixo}_roc_auc": float(roc_auc_score(y, prob)),
         f"{prefixo}_precision_at_k": p_k, f"{prefixo}_recall_at_k": r_k,
         f"{prefixo}_taxa_positivos": float(y.mean())}
    if 0 <= prob.min() and prob.max() <= 1:
        m[f"{prefixo}_brier"] = float(brier_score_loss(y, prob))
    if limiar is not None:
        m[f"{prefixo}_f1"] = float(f1_score(y, prob >= limiar, zero_division=0))
    return m


# ---------------- modelos ----------------
class RegraSimples:
    """Baseline da proposta: maior valor de um atributo = maior risco (horas acumuladas ou temperatura)."""
    def __init__(self, coluna: str):
        self.coluna = coluna

    def fit(self, X, y=None):
        self.min_, self.max_ = float(X[self.coluna].min()), float(X[self.coluna].max())
        return self

    def predict_proba(self, X):
        p = ((X[self.coluna] - self.min_) / (self.max_ - self.min_ or 1)).clip(0, 1).to_numpy()
        return np.column_stack([1 - p, p])


def criar(nome: str, params: dict, pos_peso: float):
    if nome == "random_forest":
        return RandomForestClassifier(n_jobs=-1, random_state=SEMENTE, class_weight="balanced_subsample", **params)
    return XGBClassifier(tree_method="hist", eval_metric="aucpr", random_state=SEMENTE, n_jobs=-1,
                         scale_pos_weight=pos_peso, **params)


def espaco(nome: str, trial: optuna.Trial) -> dict:
    if nome == "random_forest":
        return {"n_estimators": trial.suggest_int("n_estimators", 100, 300, step=50),
                "max_depth": trial.suggest_int("max_depth", 4, 12),
                "min_samples_leaf": trial.suggest_int("min_samples_leaf", 5, 60),
                "max_features": trial.suggest_float("max_features", 0.2, 0.8)}
    return {"n_estimators": trial.suggest_int("n_estimators", 100, 500, step=50),
            "max_depth": trial.suggest_int("max_depth", 2, 7),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "min_child_weight": trial.suggest_float("min_child_weight", 1, 20, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 0.1, 10, log=True)}


def otimizar(nome: str, treino: pd.DataFrame, n_trials: int, usar_mlflow: bool) -> dict:
    folds = [(amostrar(a), b) for a, b in folds_walk_forward(treino)]

    def objetivo(trial: optuna.Trial) -> float:
        params = espaco(nome, trial)
        notas = []
        for a, b in folds:
            pos_peso = (a["y"] == 0).sum() / max((a["y"] == 1).sum(), 1)
            modelo = criar(nome, params, pos_peso).fit(a[FEATURES], a["y"])
            notas.append(average_precision_score(b["y"], modelo.predict_proba(b[FEATURES])[:, 1]))
        nota = float(np.mean(notas))
        if usar_mlflow:
            with mlflow.start_run(run_name=f"tuning_{nome}", nested=True):
                mlflow.set_tag("fase", "tuning")
                mlflow.log_params({"modelo": nome, **params})
                mlflow.log_metrics({"cv_pr_auc_media": nota, "cv_pr_auc_desvio": float(np.std(notas))})
        return nota

    estudo = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=SEMENTE))
    estudo.optimize(objetivo, n_trials=n_trials, show_progress_bar=False)
    print(f"  {nome}: melhor PR-AUC walk-forward {estudo.best_value:.3f} com {estudo.best_params}")
    return {"params": estudo.best_params, "cv_pr_auc": estudo.best_value}


def calibrar(modelo, validacao: pd.DataFrame):
    """Platt (sigmoid) ou isotônica: escolhe pelo Brier na 2ª metade da validação, depois ajusta a
    escolhida na validação inteira."""
    datas = np.sort(validacao["data"].unique())
    meio = datas[len(datas) // 2]
    a, b = validacao[validacao["data"] < meio], validacao[validacao["data"] >= meio]
    brier = {}
    for metodo in ("sigmoid", "isotonic"):
        cal = CalibratedClassifierCV(FrozenEstimator(modelo), method=metodo).fit(a[FEATURES], a["y"])
        brier[metodo] = brier_score_loss(b["y"], cal.predict_proba(b[FEATURES])[:, 1])
    metodo = min(brier, key=brier.get)
    final = CalibratedClassifierCV(FrozenEstimator(modelo), method=metodo).fit(validacao[FEATURES], validacao["y"])
    return final, metodo, {k: round(float(v), 5) for k, v in brier.items()}


def limiar_f1(y: np.ndarray, prob: np.ndarray) -> float:
    precisao, recall, limiares = precision_recall_curve(y, prob)
    f1 = 2 * precisao * recall / np.maximum(precisao + recall, 1e-12)
    return float(limiares[np.argmax(f1[:-1])]) if len(limiares) else 0.5


# ---------------- gráficos ----------------
def graficos(df_teste: pd.DataFrame, probs: dict, prob_cal: np.ndarray, pasta: Path) -> list[Path]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from sklearn.calibration import calibration_curve
    except ImportError:
        return []
    arquivos = []
    fig, ax = plt.subplots(figsize=(6, 4.5))
    for nome, prob in probs.items():
        p, r, _ = precision_recall_curve(df_teste["y"], prob)
        ax.plot(r, p, label=f"{nome} (PR-AUC {average_precision_score(df_teste['y'], prob):.3f})")
    ax.set_xlabel("recall"); ax.set_ylabel("precisão"); ax.set_title("Curva precisão x recall (teste)")
    ax.legend(fontsize=8); fig.tight_layout()
    arquivos.append(pasta / "curva_pr_teste.png"); fig.savefig(arquivos[-1], dpi=120); plt.close(fig)

    fig, ax = plt.subplots(figsize=(5, 4.5))
    frac, media = calibration_curve(df_teste["y"], prob_cal, n_bins=10, strategy="quantile")
    ax.plot(media, frac, "o-", label="modelo calibrado"); ax.plot([0, 1], [0, 1], "--", color="gray", label="ideal")
    lim = max(media.max(), frac.max()) * 1.1
    ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.set_xlabel("probabilidade prevista"); ax.set_ylabel("fração que falhou"); ax.set_title("Calibração (teste)")
    ax.legend(fontsize=8); fig.tight_layout()
    arquivos.append(pasta / "calibracao_teste.png"); fig.savefig(arquivos[-1], dpi=120); plt.close(fig)
    return arquivos


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
    except Exception:
        pass
    try:
        mlflow.sklearn.log_model(modelo, name="modelo", **argumentos)
    except TypeError:
        argumentos.pop("skops_trusted_types", None)
        mlflow.sklearn.log_model(modelo, artifact_path="modelo", **argumentos)


# ---------------- robustez ----------------
def robustez(modelo, limiar: float) -> dict:
    """Avalia o modelo em parques gerados com premissas alteradas (mesma calibração do cenário base)."""
    from parque import ARQ_CALIBRACAO, gerar_dados
    escala = None
    if ARQ_CALIBRACAO.exists():
        escala = json.loads(ARQ_CALIBRACAO.read_text(encoding="utf-8")).get("escala_risco_driver_por_mes")
    resultado = {}
    for nome, alteracoes in CENARIOS_ROBUSTEZ.items():
        catalogo, telemetria, _, _ = gerar_dados(alteracoes, dias=400, escala=escala)
        df, _ = preparar(catalogo, telemetria)
        df = df[(df["data"] >= df["data"].min() + pd.Timedelta(days=30)) & df["rotulo_completo"]]
        prob = modelo.predict_proba(df[FEATURES])[:, 1]
        resultado[nome] = {k.replace("robustez_", ""): round(v, 4) for k, v in medir(df, prob, "robustez", limiar).items()}
        print(f"  robustez {nome}: PR-AUC {resultado[nome]['pr_auc']:.3f} (positivos {resultado[nome]['taxa_positivos']:.3%})")
    return resultado


# ---------------- treino ----------------
def treinar(n_trials: int = 20, usar_mlflow: bool = True, com_robustez: bool = True) -> dict:
    inicio = time.time()
    catalogo, telemetria, origem = carregar_dados()
    df, limpeza = preparar(catalogo, telemetria)
    partes = dividir(df)
    treino, validacao, teste = partes["treino"], partes["validacao"], partes["teste"]
    for nome, parte in partes.items():
        print(f"{nome:10s} {parte['data'].min().date()} a {parte['data'].max().date()}: {len(parte):6d} linhas, "
              f"{int(parte['y'].sum())} positivas ({parte['y'].mean():.2%})")

    if usar_mlflow:
        preparar_mlflow()
    resultados, ajustados = {}, {}
    # baselines
    for nome, modelo in {"regra_horas_acumuladas": RegraSimples("horas_acumuladas"),
                         "regra_temperatura_7d": RegraSimples("temp_7d"),
                         "aleatorio_estratificado": DummyClassifier(strategy="stratified", random_state=SEMENTE)}.items():
        modelo.fit(treino[FEATURES], treino["y"])
        ajustados[nome] = modelo
        resultados[nome] = {**medir(validacao, modelo.predict_proba(validacao[FEATURES])[:, 1], "val"),
                            **medir(teste, modelo.predict_proba(teste[FEATURES])[:, 1], "teste")}

    # modelos, com Optuna
    amostra = amostrar(treino)
    pos_peso = (amostra["y"] == 0).sum() / max((amostra["y"] == 1).sum(), 1)
    melhores = {}
    for nome in ("random_forest", "xgboost"):
        if usar_mlflow:
            with mlflow.start_run(run_name=f"optuna_{nome}"):
                mlflow.set_tag("fase", "tuning")
                melhores[nome] = otimizar(nome, treino, n_trials, usar_mlflow)
        else:
            melhores[nome] = otimizar(nome, treino, n_trials, usar_mlflow)
        modelo = criar(nome, melhores[nome]["params"], pos_peso).fit(amostra[FEATURES], amostra["y"])
        ajustados[nome] = modelo
        resultados[nome] = {"cv_pr_auc": melhores[nome]["cv_pr_auc"],
                            **medir(validacao, modelo.predict_proba(validacao[FEATURES])[:, 1], "val"),
                            **medir(teste, modelo.predict_proba(teste[FEATURES])[:, 1], "teste")}

    escolhido = max(("random_forest", "xgboost"), key=lambda n: resultados[n]["val_pr_auc"])
    melhor_baseline = max(("regra_horas_acumuladas", "regra_temperatura_7d", "aleatorio_estratificado"),
                          key=lambda n: resultados[n]["val_pr_auc"])
    vence = resultados[escolhido]["val_pr_auc"] > resultados[melhor_baseline]["val_pr_auc"]

    calibrado, metodo, brier_metodos = calibrar(ajustados[escolhido], validacao)
    prob_val = calibrado.predict_proba(validacao[FEATURES])[:, 1]
    limiar = limiar_f1(validacao["y"].to_numpy(), prob_val)
    prob_teste = calibrado.predict_proba(teste[FEATURES])[:, 1]
    resultados[f"{escolhido}_calibrado"] = {**medir(validacao, prob_val, "val", limiar),
                                            **medir(teste, prob_teste, "teste", limiar)}

    tabela = pd.DataFrame(resultados).T
    print("\nComparação (escolha pela PR-AUC na validação; teste só para o relatório):")
    print(tabela[["val_pr_auc", "teste_pr_auc", "teste_roc_auc", "teste_precision_at_k", "teste_recall_at_k",
                  "teste_brier"]].round(4).to_string())
    print(f"\nEscolhido: {escolhido}, calibração {metodo} (Brier na validação: {brier_metodos}); limiar F1 {limiar:.3f}")
    print(f"Melhor baseline: {melhor_baseline}. O modelo {'VENCE' if vence else 'NÃO vence'} os baselines na PR-AUC.")

    rob = robustez(calibrado, limiar) if com_robustez else {}
    importancias = dict(sorted(zip(FEATURES, getattr(ajustados[escolhido], "feature_importances_", np.zeros(len(FEATURES))).tolist()),
                               key=lambda kv: -kv[1]))
    metadados = {
        "treinado_em": datetime.now().isoformat(timespec="seconds"), "origem_dados": origem,
        "modelo": escolhido, "calibracao": metodo, "parametros": melhores[escolhido]["params"],
        "features": FEATURES, "janela_dias": JANELA_DIAS, "limiar_f1": round(limiar, 4), "capacidade_k": CAPACIDADE_K,
        "fracao_negativos_treino": FRACAO_NEGATIVOS, "vence_baselines": bool(vence), "melhor_baseline": melhor_baseline,
        "periodos": {n: [str(p["data"].min().date()), str(p["data"].max().date()), int(len(p)), int(p["y"].sum())]
                     for n, p in partes.items()},
        "limpeza": limpeza, "metricas": {n: {k: round(v, 4) for k, v in m.items()} for n, m in resultados.items()},
        "brier_metodos_calibracao": brier_metodos, "robustez": rob,
        "importancia_features": {k: round(v, 4) for k, v in importancias.items()},
    }
    MODELO.parent.mkdir(exist_ok=True)
    salvar_atomico(MODELO, lambda f: joblib.dump(calibrado, f, compress=3))
    salvar_atomico(METADADOS, lambda f: f.write_text(json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8"))
    print(f"Modelo salvo em {MODELO} ({MODELO.stat().st_size / 1e6:.1f} MB)")

    if usar_mlflow:
        pasta = RAIZ / "models"
        figs = graficos(teste, {n: ajustados[n].predict_proba(teste[FEATURES])[:, 1] for n in ajustados}, prob_teste, pasta)
        for nome, metricas in resultados.items():
            with mlflow.start_run(run_name=nome):
                mlflow.set_tag("fase", "comparacao")
                mlflow.set_tag("tipo_candidato", "baseline" if nome in ("regra_horas_acumuladas", "regra_temperatura_7d",
                                                                        "aleatorio_estratificado") else "ml")
                mlflow.log_params({"modelo": nome, "janela_dias": JANELA_DIAS, "linhas_treino": len(treino),
                                   "origem_dados": origem, **melhores.get(nome.replace("_calibrado", ""), {}).get("params", {})})
                mlflow.log_metrics(metricas)
        with mlflow.start_run(run_name=f"producao_{escolhido}_calibrado"):
            mlflow.set_tag("fase", "producao")
            mlflow.log_params({"modelo": escolhido, "calibracao": metodo, "limiar_f1": round(limiar, 4),
                               **melhores[escolhido]["params"]})
            mlflow.log_metrics(resultados[f"{escolhido}_calibrado"])
            mlflow.log_dict(metadados, "metadados_falha.json")
            for f in figs:
                mlflow.log_artifact(str(f))
                f.unlink(missing_ok=True)
            registrar(calibrado, teste[FEATURES].head(5))
    print(f"Tempo total: {time.time() - inicio:.0f} s")
    return metadados


def main() -> None:
    parser = argparse.ArgumentParser(description="Treina o modelo de falha em 14 dias")
    parser.add_argument("--rapido", action="store_true", help="poucas tentativas do Optuna, sem robustez")
    parser.add_argument("--sem-mlflow", action="store_true")
    args = parser.parse_args()
    trials = 4 if args.rapido else int(os.getenv("FALHA_TRIALS", "20"))
    treinar(n_trials=trials, usar_mlflow=not args.sem_mlflow, com_robustez=not args.rapido)


if __name__ == "__main__":
    main()
