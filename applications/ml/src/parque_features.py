"""
Limpeza, atributos e rótulo da telemetria do parque de luminárias (proposta, seções g.2 e g.3).

Usado pelo treino (treinar_falha.py), pelo pipeline do Airflow (pipeline_parque.py) e pela API,
para os três prepararem os dados do mesmo jeito.

Regras que evitam vazamento:
    - todo atributo da data t usa só leituras até t (janelas que olham para trás);
    - o rótulo y(t) = 1 se a luminária falhar em (t, t + 14 dias]; linhas sem os 14 dias seguintes
      observados ficam fora do treino;
    - linhas em que a luminária já está apagada (em reparo ou no dia da falha) ficam fora: não faz
      sentido prever a falha de quem já falhou.
"""

import numpy as np
import pandas as pd

JANELA_DIAS = 14

# Faixas fisicamente possíveis; fora delas a leitura é erro de medição, não defeito
FAIXAS = {
    "temp_media_c": (-10, 120), "temp_max_c": (-10, 130), "tensao_media_v": (150, 400),
    "tensao_min_v": (100, 400), "tensao_max_v": (150, 450), "corrente_media_a": (0, 5),
    "ripple_pct": (0, 100), "horas_operacao": (0, 14), "horas_acumuladas": (0, 200_000),
}

FEATURES = [
    "temp_media_c", "temp_7d", "temp_30d", "temp_tendencia", "temp_max_7d",
    "tensao_max_7d", "tensao_min_7d", "surtos_7d", "surtos_30d", "surtos_90d",
    "carga_rel", "carga_rel_7d", "carga_tendencia",
    "ripple_pct", "ripple_7d", "ripple_max_7d", "ripple_tendencia", "dias_cintilando_30d",
    "horas_acumuladas", "ciclos_acumulados", "ciclos_7d",
    "potencia_w", "mes_sin", "mes_cos",
]


def limpar_telemetria(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Remove duplicatas, troca leituras impossíveis por ausente e preenche lacunas curtas (até 2
    leituras) com a última leitura válida da mesma luminária. Devolve os dados limpos e um relatório."""
    df = df.copy()
    lidas = len(df)
    df["data"] = pd.to_datetime(df["data"])
    df = df.sort_values(["id_luminaria", "data"])
    duplicadas = int(df.duplicated(["id_luminaria", "data"], keep="last").sum())
    df = df.drop_duplicates(["id_luminaria", "data"], keep="last")

    invalidas = {}
    for coluna, (minimo, maximo) in FAIXAS.items():
        if coluna in df:
            ruim = df[coluna].notna() & ~df[coluna].between(minimo, maximo)
            invalidas[coluna] = int(ruim.sum())
            df.loc[ruim, coluna] = np.nan
    numericas = [c for c in FAIXAS if c in df]
    ausentes_antes = int(df[numericas].isna().any(axis=1).sum())
    df[numericas] = df.groupby("id_luminaria")[numericas].ffill(limit=2)
    sobrou = df[numericas].isna().any(axis=1)
    df = df[~sobrou]
    relatorio = {"lidas": lidas, "duplicadas": duplicadas, "leituras_invalidas": invalidas,
                 "linhas_com_ausente": ausentes_antes, "preenchidas": ausentes_antes - int(sobrou.sum()),
                 "descartadas": int(sobrou.sum()) + duplicadas, "validas": len(df)}
    return df.reset_index(drop=True), relatorio


def construir_features(df: pd.DataFrame, catalogo: pd.DataFrame) -> pd.DataFrame:
    """Atributos por luminária e data, só com o passado. df já limpo (limpar_telemetria)."""
    df = df.merge(catalogo[["id_luminaria", "potencia_w"]], on="id_luminaria", how="left")
    df = df.sort_values(["id_luminaria", "data"]).reset_index(drop=True)
    acesa = df["estado"] != "APAGADA"
    # quanto a luminária puxa em relação ao que deveria: sobe com o dano do driver
    esperado = df["potencia_w"] * df["pct_medio"].clip(lower=1) / 100
    df["carga_rel"] = np.where(acesa, df["corrente_media_a"] * df["tensao_media_v"] / esperado, np.nan)
    df["cintilando"] = (df["estado"] == "CINTILANDO").astype(float)

    janelas = {
        "temp_7d": ("temp_media_c", "7D", "mean"), "temp_30d": ("temp_media_c", "30D", "mean"),
        "temp_max_7d": ("temp_max_c", "7D", "max"), "tensao_max_7d": ("tensao_max_v", "7D", "max"),
        "tensao_min_7d": ("tensao_min_v", "7D", "min"), "surtos_7d": ("surtos_dia", "7D", "sum"),
        "surtos_30d": ("surtos_dia", "30D", "sum"), "surtos_90d": ("surtos_dia", "90D", "sum"),
        "carga_rel_7d": ("carga_rel", "7D", "mean"), "carga_rel_30d": ("carga_rel", "30D", "mean"),
        "ripple_7d": ("ripple_pct", "7D", "mean"), "ripple_30d": ("ripple_pct", "30D", "mean"),
        "ripple_max_7d": ("ripple_pct", "7D", "max"), "dias_cintilando_30d": ("cintilando", "30D", "sum"),
        "ciclos_7d": ("ciclos_dia", "7D", "sum"),
    }
    # uma chamada por (janela, função), com todas as colunas juntas: muito mais rápido que por luminária
    grupos: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for nome, (coluna, janela, func) in janelas.items():
        grupos.setdefault((janela, func), []).append((nome, coluna))
    for (janela, func), pares in grupos.items():
        colunas = sorted({c for _, c in pares})
        rolado = getattr(df.groupby("id_luminaria", sort=True).rolling(janela, on="data", min_periods=1)[colunas], func)()
        # o resultado vem na ordem (luminária, data), a mesma do df ordenado acima
        assert len(rolado) == len(df)
        for nome, coluna in pares:
            df[nome] = rolado[coluna].to_numpy()
    df["temp_tendencia"] = df["temp_7d"] - df["temp_30d"]
    df["carga_tendencia"] = df["carga_rel_7d"] - df["carga_rel_30d"]
    df["ripple_tendencia"] = df["ripple_7d"] - df["ripple_30d"]
    mes = df["data"].dt.month
    df["mes_sin"], df["mes_cos"] = np.sin(2 * np.pi * mes / 12), np.cos(2 * np.pi * mes / 12)
    return df


def rotular(df: pd.DataFrame, janela: int = JANELA_DIAS) -> pd.DataFrame:
    """y = 1 se a luminária falhar nos próximos `janela` dias; `rotulo_completo` diz se esses dias
    foram observados (no fim da série não foram, a não ser que a falha já tenha aparecido)."""
    df = df.sort_values(["id_luminaria", "data"]).copy()
    data_falha = df["data"].where(df["falha"] == 1)
    proxima = data_falha.groupby(df["id_luminaria"]).transform(lambda s: s.shift(-1).bfill())
    dias = (proxima - df["data"]).dt.days
    df["y"] = ((dias >= 1) & (dias <= janela)).astype(int)
    ultima = df.groupby("id_luminaria")["data"].transform("max")
    df["rotulo_completo"] = (df["y"] == 1) | (df["data"] <= ultima - pd.Timedelta(days=janela))
    return df


def linhas_para_modelo(df: pd.DataFrame) -> pd.Series:
    """Linhas em que faz sentido prever: luminária acesa e com os atributos calculados."""
    return (df["estado"] != "APAGADA") & df[FEATURES].notna().all(axis=1)
