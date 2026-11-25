"""
Treina e compara os modelos de risco por bairro, registrando cada um no MLflow.

Entrada: data/processed/risco_bairro_mes.csv (gerado pelo preparar_dados.py)
Alvo:    chamados_mes_seguinte (contagem de chamados de lampada apagada no mes seguinte)

Como a comparacao e feita (sem olhar o teste para escolher):
1. Validacao: dentro do treino, os ultimos 12 meses de alvo (2024) viram validacao.
   Cada candidato treina no resto e e medido ali. O melhor pela MAE de validacao e o escolhido.
2. Teste: todos os candidatos sao retreinados no treino inteiro e medidos no teste (alvos
   de 2025), so para o relatorio. A escolha ja foi feita no passo 1.
3. Producao: o escolhido e retreinado com tudo (treino + teste) e preve o mes seguinte ao
   ultimo dado de cada bairro. O resultado vira models/risco_por_bairro.csv, que a API serve.

Metricas (MACHINE_LEARNING.md secao 4): MAE, RMSE e precisao no top 10% (por contagem e
por taxa por 1.000 postes). As regras simples (persistencia e media movel) entram como
"modelos" tambem, para a comparacao ficar lado a lado no MLflow.

Uso:
    python applications/ml/src/treinar.py
    (MLFLOW_TRACKING_URI: padrao sqlite em applications/ml/mlflow.db; na Docker, http://mlflow:5000)
"""

import json
import os
from datetime import datetime
from pathlib import Path

import joblib
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.ensemble import (
    GradientBoostingRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

RAIZ = Path(__file__).resolve().parent.parent
BASE = RAIZ / "data" / "processed" / "risco_bairro_mes.csv"
SAIDA = RAIZ / "models"
EXPERIMENTO = "risco_bairro"
MODELO_REGISTRADO = "risco_bairro"
ALVO = "chamados_mes_seguinte"
SEMENTE = 17

FEATURES = [
    "chamados_lampada_apagada", "chamados_lag1", "chamados_lag2", "chamados_lag3", "media_movel_3m",
    "total_postes", "postes_sem_id", "potencia_media_w", "pct_led", "rpa",
    "mes_do_ano", "taxa_1000_postes",
]

# Faixas do contrato com o poste (MACHINE_LEARNING.md secao 5.3)
def classe_de(risco: float) -> str:
    return "alto" if risco >= 0.7 else "medio" if risco >= 0.4 else "baixo"


def carregar() -> pd.DataFrame:
    df = pd.read_csv(BASE)
    df["mes_do_ano"] = df["ano_mes"].str[5:7].astype(int)
    df["taxa_1000_postes"] = df["chamados_lampada_apagada"] / df["total_postes"] * 1000
    df["rpa"] = pd.to_numeric(df["rpa"], errors="coerce")
    df["mes_do_alvo"] = (pd.PeriodIndex(df["ano_mes"], freq="M") + 1).astype(str)
    return df


# ---------------- metricas ----------------
def precisao_top(df: pd.DataFrame, previsto: np.ndarray, por_taxa: bool = False, fracao: float = 0.10) -> float:
    """Em cada mes: os k bairros com maior previsao vs. os k com maior valor real; acertos / k.
    Media entre os meses. Com por_taxa, compara previsao e real divididos pelo total de postes."""
    tabela = df[["ano_mes", "total_postes", ALVO]].copy()
    tabela["previsto"] = previsto
    if por_taxa:
        tabela["previsto"] = tabela["previsto"] / tabela["total_postes"]
        tabela[ALVO] = tabela[ALVO] / tabela["total_postes"]
    acertos = []
    for _, mes in tabela.groupby("ano_mes"):
        k = max(1, round(len(mes) * fracao))
        top_previsto = set(mes.nlargest(k, "previsto").index)
        top_real = set(mes.nlargest(k, ALVO).index)
        acertos.append(len(top_previsto & top_real) / k)
    return float(np.mean(acertos))


def medir(df: pd.DataFrame, previsto: np.ndarray, prefixo: str) -> dict:
    erro = previsto - df[ALVO].to_numpy()
    return {
        f"{prefixo}_mae": float(np.mean(np.abs(erro))),
        f"{prefixo}_rmse": float(np.sqrt(np.mean(erro ** 2))),
        f"{prefixo}_precisao_top10": precisao_top(df, previsto),
        f"{prefixo}_precisao_top10_taxa": precisao_top(df, previsto, por_taxa=True),
    }


# ---------------- candidatos ----------------
class Regra:
    """Regra simples com a mesma interface de um modelo do scikit-learn."""
    def __init__(self, coluna: str):
        self.coluna = coluna

    def fit(self, X, y):
        return self

    def predict(self, X):
        return X[self.coluna].to_numpy(dtype=float)


def candidatos() -> dict:
    return {
        "regra_persistencia": (Regra("chamados_lampada_apagada"), {"tipo": "regra", "coluna": "chamados_lampada_apagada"}),
        "regra_media_movel_3m": (Regra("media_movel_3m"), {"tipo": "regra", "coluna": "media_movel_3m"}),
        "random_forest": (
            RandomForestRegressor(n_estimators=300, min_samples_leaf=5, random_state=SEMENTE, n_jobs=-1),
            {"n_estimators": 300, "min_samples_leaf": 5},
        ),
        "gradient_boosting": (
            GradientBoostingRegressor(n_estimators=300, learning_rate=0.05, max_depth=3, random_state=SEMENTE),
            {"n_estimators": 300, "learning_rate": 0.05, "max_depth": 3},
        ),
        "hist_gb_poisson": (
            HistGradientBoostingRegressor(loss="poisson", max_iter=300, learning_rate=0.05, random_state=SEMENTE),
            {"loss": "poisson", "max_iter": 300, "learning_rate": 0.05},
        ),
        # GLM de Poisson: modelo feito para contagens. O log1p nas features deixa a relacao
        # "chamados do passado -> chamados do mes seguinte" proporcional, como e na pratica.
        "poisson_glm": (
            make_pipeline(FunctionTransformer(np.log1p), StandardScaler(), PoissonRegressor(alpha=1e-3, max_iter=3000)),
            {"transformacao": "log1p + padronizacao", "alpha": 1e-3},
        ),
    }


def registrar_modelo(modelo, exemplo: pd.DataFrame) -> None:
    """Loga o modelo no MLflow e registra no Model Registry.

    O MLflow 3 salva modelos sklearn com skops, que recusa tipos internos das arvores
    (ex.: sklearn.tree._tree.Tree) a menos que sejam declarados confiaveis. Aqui o modelo
    acabou de ser treinado neste mesmo processo, entao os tipos que ele usa sao confiaveis.
    """
    argumentos = {"input_example": exemplo, "registered_model_name": MODELO_REGISTRADO}
    try:
        import skops.io as sio
        argumentos["skops_trusted_types"] = sio.get_untrusted_types(data=sio.dumps(modelo))
    except ImportError:  # MLflow 2.x (sem skops) salva com pickle
        pass
    try:
        mlflow.sklearn.log_model(modelo, name="modelo", **argumentos)
    except TypeError:  # MLflow 2.x usa artifact_path no lugar de name e nao tem skops_trusted_types
        argumentos.pop("skops_trusted_types", None)
        mlflow.sklearn.log_model(modelo, artifact_path="modelo", **argumentos)


def preparar_mlflow() -> None:
    uri = os.getenv("MLFLOW_TRACKING_URI") or f"sqlite:///{(RAIZ / 'mlflow.db').as_posix()}"
    mlflow.set_tracking_uri(uri)
    if mlflow.get_experiment_by_name(EXPERIMENTO) is None:
        local = uri.startswith("sqlite") or uri.startswith("file")
        mlflow.create_experiment(EXPERIMENTO, artifact_location=(RAIZ / "mlruns").as_uri() if local else None)
    mlflow.set_experiment(EXPERIMENTO)
    print(f"MLflow: {uri} (experimento '{EXPERIMENTO}')")


def main() -> None:
    df = carregar()
    treino = df[df["conjunto"] == "treino"]
    teste = df[df["conjunto"] == "teste"]
    meses_alvo_treino = sorted(treino["mes_do_alvo"].unique())
    meses_validacao = meses_alvo_treino[-12:]
    ajuste = treino[~treino["mes_do_alvo"].isin(meses_validacao)]
    validacao = treino[treino["mes_do_alvo"].isin(meses_validacao)]
    print(f"Ajuste: {len(ajuste)} linhas | validacao: {len(validacao)} (alvos {meses_validacao[0]} a {meses_validacao[-1]}) "
          f"| teste: {len(teste)} (alvos {teste['mes_do_alvo'].min()} a {teste['mes_do_alvo'].max()})")

    preparar_mlflow()
    resultados = {}
    for nome, (modelo, params) in candidatos().items():
        with mlflow.start_run(run_name=nome) as run:
            mlflow.log_params({"modelo": nome, "features": ",".join(FEATURES), **params})
            modelo.fit(ajuste[FEATURES], ajuste[ALVO])
            metricas = medir(validacao, modelo.predict(validacao[FEATURES]), "val")
            modelo.fit(treino[FEATURES], treino[ALVO])
            metricas.update(medir(teste, modelo.predict(teste[FEATURES]), "teste"))
            mlflow.log_metrics(metricas)
            mlflow.set_tag("fase", "comparacao")
            resultados[nome] = {**metricas, "run_id": run.info.run_id}

    tabela = pd.DataFrame(resultados).T.drop(columns="run_id").astype(float)
    print("\nComparacao (escolha pela MAE de validacao; teste so para o relatorio):")
    print(tabela.sort_values("val_mae").round(3).to_string())

    modelos_treinaveis = [n for n in resultados if not n.startswith("regra_")]
    escolhido = min(modelos_treinaveis, key=lambda n: resultados[n]["val_mae"])
    melhor_regra = min((n for n in resultados if n.startswith("regra_")), key=lambda n: resultados[n]["val_mae"])
    venceu = resultados[escolhido]["val_mae"] < resultados[melhor_regra]["val_mae"]
    print(f"\nEscolhido: {escolhido} (val_mae {resultados[escolhido]['val_mae']:.2f}) | "
          f"melhor regra: {melhor_regra} (val_mae {resultados[melhor_regra]['val_mae']:.2f}) | "
          f"{'o modelo VENCE a regra' if venceu else 'o modelo NAO vence a regra'} na validacao")

    # Producao: retreina o escolhido com tudo e preve o mes seguinte ao ultimo dado de cada bairro
    modelo_final, params = candidatos()[escolhido]
    modelo_final.fit(df[FEATURES], df[ALVO])
    ultimo = df.sort_values("ano_mes").groupby("bairro_norm").tail(1).copy()
    ultimo["previsao_chamados"] = modelo_final.predict(ultimo[FEATURES]).clip(min=0).round(1)
    ultimo["previsao_por_1000_postes"] = (ultimo["previsao_chamados"] / ultimo["total_postes"] * 1000).round(2)
    ultimo["risco_contagem"] = ultimo["previsao_chamados"].rank(pct=True).round(3)
    ultimo["risco_taxa"] = ultimo["previsao_por_1000_postes"].rank(pct=True).round(3)
    ultimo["classe_contagem"] = ultimo["risco_contagem"].map(classe_de)
    ultimo["classe_taxa"] = ultimo["risco_taxa"].map(classe_de)
    ultimo = ultimo.rename(columns={"bairro_norm": "bairro", "mes_do_alvo": "mes_previsto"})
    colunas = ["bairro", "mes_previsto", "previsao_chamados", "total_postes", "previsao_por_1000_postes",
               "risco_contagem", "classe_contagem", "risco_taxa", "classe_taxa"]
    risco = ultimo[colunas].sort_values("risco_contagem", ascending=False)

    SAIDA.mkdir(exist_ok=True)
    risco.to_csv(SAIDA / "risco_por_bairro.csv", index=False)
    joblib.dump(modelo_final, SAIDA / "modelo_risco.joblib")
    metadados = {
        "treinado_em": datetime.now().isoformat(timespec="seconds"),
        "modelo": escolhido,
        "parametros": params,
        "features": FEATURES,
        "alvo": ALVO,
        "mes_previsto": str(risco["mes_previsto"].iloc[0]),
        "vence_regra_simples_na_validacao": bool(venceu),
        "metricas": {n: {k: round(v, 4) for k, v in r.items() if k != "run_id"} for n, r in resultados.items()},
    }
    (SAIDA / "metadados.json").write_text(json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8")

    with mlflow.start_run(run_name=f"producao_{escolhido}"):
        mlflow.log_params({"modelo": escolhido, "treinado_com": "treino+teste", **params})
        mlflow.set_tag("fase", "producao")
        mlflow.log_artifact(str(SAIDA / "risco_por_bairro.csv"))
        exemplo = df[FEATURES].head(5)
        if isinstance(modelo_final, Regra):
            mlflow.log_dict({"regra": modelo_final.coluna}, "modelo_regra.json")
        else:
            registrar_modelo(modelo_final, exemplo)

    print(f"\nRisco previsto para {metadados['mes_previsto']} salvo em {SAIDA / 'risco_por_bairro.csv'}")
    print(risco.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
