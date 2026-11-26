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
import sys
from datetime import datetime
from pathlib import Path

import joblib
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    GradientBoostingRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import r2_score
from sklearn.model_selection import ParameterGrid, TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
from preparar_dados import codificar_mes_ciclico, nomes_mes_ciclico  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
BASE = RAIZ / "data" / "processed" / "risco_bairro_mes.csv"
SAIDA = RAIZ / "models"
EXPERIMENTO = "risco_bairro"
MODELO_REGISTRADO = "risco_bairro"
ALVO = "chamados_mes_seguinte"
SEMENTE = 17

FEATURES_CONTINUAS = [
    "chamados_lampada_apagada", "chamados_lag1", "chamados_lag2", "chamados_lag3", "media_movel_3m",
    "total_postes", "postes_sem_id", "potencia_media_w", "pct_led", "taxa_1000_postes",
]
FEATURE_CATEGORICA = ["rpa"]
FEATURE_CICLICA = ["mes_do_ano"]
FEATURES = [*FEATURES_CONTINUAS, *FEATURE_CATEGORICA, *FEATURE_CICLICA]

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
    """Calcula MAE, RMSE, R2 e precisao no top 10% (contagem e taxa)."""
    real = df[ALVO].to_numpy()
    erro = previsto - real
    return {
        f"{prefixo}_mae": float(np.mean(np.abs(erro))),
        f"{prefixo}_rmse": float(np.sqrt(np.mean(erro ** 2))),
        f"{prefixo}_r2": float(r2_score(real, previsto)),
        f"{prefixo}_precisao_top10": precisao_top(df, previsto),
        f"{prefixo}_precisao_top10_taxa": precisao_top(df, previsto, por_taxa=True),
    }


def avaliar_cv_temporal(modelo_base, treino: pd.DataFrame, n_splits: int = 5) -> tuple[dict, list[dict]]:
    """Executa TimeSeriesSplit agrupado por mes_do_alvo medindo treino, validacao e estabilidade."""
    meses = np.array(sorted(treino["mes_do_alvo"].unique()))
    tscv = TimeSeriesSplit(n_splits=n_splits)
    folds = []
    for indice, (idx_tr, idx_va) in enumerate(tscv.split(meses), start=1):
        tr = treino[treino["mes_do_alvo"].isin(meses[idx_tr])]
        va = treino[treino["mes_do_alvo"].isin(meses[idx_va])]
        modelo = clone(modelo_base)
        modelo.fit(tr[FEATURES], tr[ALVO])
        aj_fold = medir(tr, modelo.predict(tr[FEATURES]), "cv_ajuste")
        va_fold = medir(va, modelo.predict(va[FEATURES]), "cv")
        folds.append({
            "fold": indice,
            "val_inicio": str(meses[idx_va][0]),
            "val_fim": str(meses[idx_va][-1]),
            "cv_ajuste_mae": aj_fold["cv_ajuste_mae"],
            "cv_gap_mae": va_fold["cv_mae"] - aj_fold["cv_ajuste_mae"],
            **va_fold,
        })

    resumo = {}
    for metrica in ("cv_ajuste_mae", "cv_mae", "cv_gap_mae", "cv_rmse", "cv_r2", "cv_precisao_top10"):
        valores = [f[metrica] for f in folds]
        resumo[f"{metrica}_mean"] = float(np.mean(valores))
        resumo[f"{metrica}_std"] = float(np.std(valores, ddof=1))
    return resumo, folds


def limpar_parametros(params: dict) -> dict:
    """Remove prefixos de etapa do Pipeline para legibilidade no MLflow e metadados."""
    return {chave.split("__", 1)[-1]: valor for chave, valor in params.items()}


def otimizar_hiperparametros(
    nome: str, modelo_base, grade: dict, treino: pd.DataFrame, n_splits: int = 5
) -> tuple[dict, dict, list[dict], int]:
    """Busca a melhor combinacao via TimeSeriesSplit, registrando cada teste como nested run no MLflow."""
    combinacoes = list(ParameterGrid(grade))
    melhor = None
    for idx, params in enumerate(combinacoes, start=1):
        candidato = clone(modelo_base).set_params(**params)
        resumo, folds = avaliar_cv_temporal(candidato, treino, n_splits=n_splits)
        params_limpos = limpar_parametros(params)
        with mlflow.start_run(run_name=f"{nome}_tuning_{idx}", nested=True):
            mlflow.set_tag("fase", "tuning")
            mlflow.set_tag("modelo", nome)
            mlflow.log_params(params_limpos)
            mlflow.log_metrics({
                "cv_mae_mean": resumo["cv_mae_mean"],
                "cv_mae_std": resumo["cv_mae_std"],
                "cv_ajuste_mae_mean": resumo["cv_ajuste_mae_mean"],
                "cv_gap_mae_mean": resumo["cv_gap_mae_mean"],
                "cv_r2_mean": resumo["cv_r2_mean"],
            })
        if melhor is None or resumo["cv_mae_mean"] < melhor[1]["cv_mae_mean"]:
            melhor = (params, resumo, folds)
    return (*melhor, len(combinacoes))


# ---------------- candidatos ----------------
class Regra:
    """Regra simples com a mesma interface de um modelo do scikit-learn."""
    def __init__(self, coluna: str):
        self.coluna = coluna

    def fit(self, X, y):
        return self

    def predict(self, X):
        return X[self.coluna].to_numpy(dtype=float)

    def get_params(self, deep: bool = True) -> dict:
        return {"coluna": self.coluna}

    def set_params(self, **params):
        for chave, valor in params.items():
            setattr(self, chave, valor)
        return self


def criar_preprocessador(escalar_continuas: bool) -> ColumnTransformer:
    """Preprocessa continuas (log1p + escala opcional), rpa (One-Hot) e mes_do_ano (sin/cos)."""
    cont = (
        make_pipeline(FunctionTransformer(np.log1p, feature_names_out="one-to-one"), StandardScaler())
        if escalar_continuas
        else "passthrough"
    )
    mes = FunctionTransformer(codificar_mes_ciclico, feature_names_out=nomes_mes_ciclico)
    if escalar_continuas:
        mes = make_pipeline(mes, StandardScaler())
    return ColumnTransformer([
        ("cont", cont, FEATURES_CONTINUAS),
        ("rpa", OneHotEncoder(handle_unknown="ignore", sparse_output=False), FEATURE_CATEGORICA),
        ("mes", mes, FEATURE_CICLICA),
    ])


def candidatos() -> dict:
    return {
        "regra_persistencia": (Regra("chamados_lampada_apagada"), {"tipo": "regra", "coluna": "chamados_lampada_apagada"}),
        "regra_media_movel_3m": (Regra("media_movel_3m"), {"tipo": "regra", "coluna": "media_movel_3m"}),
        "random_forest": (
            make_pipeline(
                criar_preprocessador(escalar_continuas=False),
                RandomForestRegressor(n_estimators=300, min_samples_leaf=5, random_state=SEMENTE, n_jobs=-1),
            ),
            {"encoding": "one-hot (rpa) + sin/cos (mes)", "n_estimators": 300, "min_samples_leaf": 5},
        ),
        "gradient_boosting": (
            make_pipeline(
                criar_preprocessador(escalar_continuas=False),
                GradientBoostingRegressor(n_estimators=300, learning_rate=0.05, max_depth=3, random_state=SEMENTE),
            ),
            {"encoding": "one-hot (rpa) + sin/cos (mes)", "n_estimators": 300, "learning_rate": 0.05, "max_depth": 3},
        ),
        "hist_gb_poisson": (
            make_pipeline(
                criar_preprocessador(escalar_continuas=False),
                HistGradientBoostingRegressor(loss="poisson", max_iter=300, learning_rate=0.05, random_state=SEMENTE),
            ),
            {"encoding": "one-hot (rpa) + sin/cos (mes)", "loss": "poisson", "max_iter": 300, "learning_rate": 0.05},
        ),
        # GLM de Poisson: modelo feito para contagens. O log1p apenas nas continuas deixa a relacao
        # "chamados do passado -> chamados do mes seguinte" proporcional, com rpa em One-Hot e mes ciclico.
        "poisson_glm": (
            make_pipeline(criar_preprocessador(escalar_continuas=True), PoissonRegressor(alpha=1e-3, max_iter=3000)),
            {"transformacao": "log1p+padronizacao (continuas) | one-hot (rpa) | sin/cos (mes)", "alpha": 1e-3},
        ),
    }


def espacos_tuning() -> dict:
    """Grade de hiperparametros avaliada por TimeSeriesSplit para cada modelo treinavel."""
    return {
        "random_forest": {
            "randomforestregressor__n_estimators": [250],
            "randomforestregressor__max_depth": [5, 8, None],
            "randomforestregressor__min_samples_leaf": [3, 5, 10],
        },
        "gradient_boosting": {
            "gradientboostingregressor__n_estimators": [150, 300],
            "gradientboostingregressor__learning_rate": [0.03, 0.05],
            "gradientboostingregressor__max_depth": [2, 3],
        },
        "hist_gb_poisson": {
            "histgradientboostingregressor__max_iter": [150, 300],
            "histgradientboostingregressor__learning_rate": [0.03, 0.05],
            "histgradientboostingregressor__max_depth": [3, 5],
            "histgradientboostingregressor__min_samples_leaf": [10],
        },
        "poisson_glm": {
            "poissonregressor__alpha": [0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 3.0, 5.0],
        },
    }


def construir_modelo(nome: str, params_limpos: dict | None = None):
    """Instancia um candidato aplicando parametros otimizados (se fornecidos)."""
    modelo, _ = candidatos()[nome]
    if not params_limpos:
        return modelo
    ultimo_passo = list(modelo.named_steps)[-1] if hasattr(modelo, "named_steps") else None
    todos = modelo.get_params()
    validos = {}
    for k, v in params_limpos.items():
        chave = f"{ultimo_passo}__{k}" if ultimo_passo else k
        if chave in todos:
            validos[chave] = v
    return modelo.set_params(**validos) if validos else modelo


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
    n_splits_cv = 5
    grades = espacos_tuning()
    resultados = {}
    folds_por_modelo = {}
    params_por_modelo = {}

    for nome, (modelo_base, params_meta) in candidatos().items():
        with mlflow.start_run(run_name=nome) as run:
            if nome in grades:
                melhores_pipeline_params, metricas, folds, total_combos = otimizar_hiperparametros(
                    nome, modelo_base, grades[nome], treino, n_splits=n_splits_cv
                )
                modelo = clone(modelo_base).set_params(**melhores_pipeline_params)
                params_otimos = limpar_parametros(melhores_pipeline_params)
            else:
                modelo = clone(modelo_base)
                metricas, folds = avaliar_cv_temporal(modelo, treino, n_splits=n_splits_cv)
                params_otimos = {}
                total_combos = 1

            params_run = {**params_meta, **params_otimos}
            mlflow.log_params({
                "modelo": nome,
                "features": ",".join(FEATURES),
                "cv_splits": n_splits_cv,
                "tuning_combinacoes": total_combos,
                **params_run,
            })

            modelo.fit(ajuste[FEATURES], ajuste[ALVO])
            metricas.update(medir(ajuste, modelo.predict(ajuste[FEATURES]), "ajuste"))
            metricas.update(medir(validacao, modelo.predict(validacao[FEATURES]), "val"))
            metricas["gap_val_ajuste_mae"] = metricas["val_mae"] - metricas["ajuste_mae"]
            modelo.fit(treino[FEATURES], treino[ALVO])
            metricas.update(medir(teste, modelo.predict(teste[FEATURES]), "teste"))
            mlflow.log_metrics(metricas)
            mlflow.set_tag("fase", "comparacao")

            resultados[nome] = {**metricas, "run_id": run.info.run_id}
            folds_por_modelo[nome] = folds
            params_por_modelo[nome] = params_run

    tabela = pd.DataFrame(resultados).T.drop(columns="run_id").astype(float)
    colunas_resumo = [
        "ajuste_mae", "val_mae", "gap_val_ajuste_mae",
        "cv_ajuste_mae_mean", "cv_mae_mean", "cv_mae_std", "cv_gap_mae_mean",
        "val_r2", "teste_mae", "teste_rmse", "teste_r2", "teste_precisao_top10",
    ]
    print("\nComparacao (tuning por TimeSeriesSplit; escolha pela MAE na validacao recente de 2024):")
    print(tabela[colunas_resumo].sort_values("val_mae").round(3).to_string())

    modelos_treinaveis = [n for n in resultados if not n.startswith("regra_")]
    escolhido = min(modelos_treinaveis, key=lambda n: resultados[n]["val_mae"])
    melhor_regra = min((n for n in resultados if n.startswith("regra_")), key=lambda n: resultados[n]["val_mae"])
    venceu = resultados[escolhido]["val_mae"] < resultados[melhor_regra]["val_mae"]
    print(f"\nEscolhido: {escolhido} (val_mae {resultados[escolhido]['val_mae']:.2f}, "
          f"cv_gap {resultados[escolhido]['cv_gap_mae_mean']:+.2f}, params {params_por_modelo[escolhido]}) | "
          f"melhor regra: {melhor_regra} (val_mae {resultados[melhor_regra]['val_mae']:.2f}) | "
          f"{'o modelo VENCE a regra' if venceu else 'o modelo NAO vence a regra'} na validacao")

    # Producao: retreina o escolhido com os hiperparametros otimizados em toda a base
    modelo_final = construir_modelo(escolhido, params_por_modelo[escolhido])
    params = params_por_modelo[escolhido]
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
        "parametros_por_modelo": params_por_modelo,
        "features": FEATURES,
        "alvo": ALVO,
        "cv_estrategia": f"TimeSeriesSplit(n_splits={n_splits_cv}) por mes_do_alvo no conjunto de treino",
        "criterio_selecao": "menor val_mae (alvos 2024) apos tuning via TimeSeriesSplit",
        "mes_previsto": str(risco["mes_previsto"].iloc[0]),
        "vence_regra_simples_na_validacao": bool(venceu),
        "metricas": {n: {k: round(v, 4) for k, v in r.items() if k != "run_id"} for n, r in resultados.items()},
        "cv_folds": {
            n: [{k: round(v, 4) if isinstance(v, float) else v for k, v in f.items()} for f in fl]
            for n, fl in folds_por_modelo.items()
        },
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
