"""
Prepara a base de risco de falha por bairro/mes, cruzando o cadastro de postes
da Emlurb (2025) com os chamados de "lampada apagada" da Central 156 (2022-2025).

Entrada:  applications/ml/data/raw/postes/iluminacao-publica-do-recife-2025.csv
          applications/ml/data/raw/central156/<ano>-central-de-atendimento-de-servicos-da-emlurb-156.csv

Saida:    applications/ml/data/processed/postes_por_bairro.csv
          applications/ml/data/processed/risco_bairro_mes.csv

Decisao de cruzamento (ver applications/ml/README.md): por BAIRRO, nao por
coordenada/endereco, porque so 36% dos chamados de iluminacao tem
latitude/longitude preenchida, contra 100% de preenchimento do bairro.

O painel final tem features de defasagem (chamados_lag1/2/3, media_movel_3m) e
dois alvos: o binario teve_chamado_mes_seguinte (legado) e chamados_mes_seguinte
(contagem). O alvo principal para o treinar.py e a CONTAGEM, nao o binario -- a
EDA mostrou o binario com no maximo 0,15 de correlacao com qualquer feature
(secao 5 do README), contra ate 0,89 na contagem.
"""

import re
import unicodedata
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
DADOS_BRUTOS = RAIZ / "data" / "raw"
DADOS_PROCESSADOS = RAIZ / "data" / "processed"

ANOS_CHAMADOS = [2022, 2023, 2024, 2025]
PRIMEIRO_MES = "2022-01"
ULTIMO_MES = "2025-12"

# A Emlurb trocou a tabela de codigos de servico em 2024: o texto em
# GRUPOSERVICO_DESCRICAO/SERVICO_DESCRICAO de 2022-2023 tambem vem com os
# acentos corrompidos ("ILUMINA??O P?BLICA", "MANUTENO EM LMPADA APAGADA"),
# entao o filtro usa os codigos numericos, estaveis dentro de cada era e
# confirmados como nao reaproveitados entre elas (ver README).
CODIGOS_LAMPADA_APAGADA = [
    ("4", "55"),   # 2024 e 2025: GRUPOSERVICO "ILUMINACAO PUBLICA" / SERVICO "MANUTENCAO EM LAMPADA APAGADA"
    ("17", "25"),  # 2022 e 2023: mesmo servico, codigo antigo
]


# Erros de digitacao no cadastro de postes que a normalizacao (acento/caixa/espaco)
# nao resolve sozinha, porque sao letras diferentes, nao so formatacao. Achados
# comparando a lista de bairros do cadastro em ordem alfabetica: cada um tem poucos
# postes (1 a 8) perto de uma variante correta com centenas/milhares (ver README).
CORRECOES_BAIRRO = {
    "CIDADDE UNIVERSITARIA": "CIDADE UNIVERSITARIA",
    "IMBIRBEIRA": "IMBIRIBEIRA",
    "TEJIIPIO": "TEJIPIO",
}

# Nao e um bairro de verdade, e sim um valor de preenchimento da Central 156
# (54 chamados em 4 anos, so em 2024) para quando o atendente nao registrou o
# bairro. Fica de fora do painel por bairro em vez de virar uma categoria.
BAIRRO_DESCARTAR = "BAIRRO NAO INFORMADO"


def normalizar_bairro(texto: str) -> str:
    """Deixa o nome do bairro comparavel entre as duas bases: sem acento,
    maiusculo, sem espaco duplicado nas pontas ou no meio, com os erros de
    digitacao conhecidos corrigidos (CORRECOES_BAIRRO)."""
    if not isinstance(texto, str):
        return ""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    normalizado = re.sub(r"\s+", " ", sem_acento).strip().upper()
    return CORRECOES_BAIRRO.get(normalizado, normalizado)


def carregar_postes() -> pd.DataFrame:
    caminho = DADOS_BRUTOS / "postes" / "iluminacao-publica-do-recife-2025.csv"
    df = pd.read_csv(caminho, sep=";", dtype=str)

    # 1 linha em 111.666 vem com os campos desalinhados (a longitude aparece
    # no lugar do bairro). Nenhum bairro de verdade tem digito no nome, entao
    # isso identifica e descarta so essa linha.
    bairro_invalido = df["bairro"].str.contains(r"\d", na=True)
    if bairro_invalido.any():
        print(f"Postes descartados por bairro invalido (campos desalinhados na fonte): {bairro_invalido.sum()}")
    df = df[~bairro_invalido].copy()

    df["bairro_norm"] = df["bairro"].map(normalizar_bairro)
    df["potencia"] = pd.to_numeric(df["potencia"].str.replace(",", "."), errors="coerce")
    df["eh_led"] = df["tipo_lampa"] == "LED"
    return df


def agregar_postes_por_bairro(postes: pd.DataFrame) -> pd.DataFrame:
    # Usa o tamanho do grupo, nao a contagem de id_ponto: ~7.100 postes (LED,
    # com bairro e potencia preenchidos) ainda nao tem id_ponto no cadastro,
    # e contar so id_ponto subestimaria esses postes.
    agregado = postes.groupby("bairro_norm").agg(
        total_postes=("bairro_norm", "size"),
        postes_sem_id=("id_ponto", lambda s: s.isna().sum()),
        potencia_media_w=("potencia", "mean"),
        pct_led=("eh_led", "mean"),
        rpa=("rpa", "first"),
    )
    agregado["pct_led"] = (agregado["pct_led"] * 100).round(1)
    agregado["potencia_media_w"] = agregado["potencia_media_w"].round(1)
    return agregado.reset_index()


def carregar_chamados_lampada_apagada() -> pd.DataFrame:
    partes = []
    for ano in ANOS_CHAMADOS:
        caminho = DADOS_BRUTOS / "central156" / f"{ano}-central-de-atendimento-de-servicos-da-emlurb-156.csv"
        partes.append(pd.read_csv(caminho, sep=";", dtype=str))

    chamados = pd.concat(partes, ignore_index=True)
    antes = len(chamados)
    chamados = chamados.drop_duplicates()
    duplicados_removidos = antes - len(chamados)

    filtro = pd.Series(False, index=chamados.index)
    for codigo_grupo, codigo_servico in CODIGOS_LAMPADA_APAGADA:
        filtro |= (chamados["GRUPOSERVICO_CODIGO"] == codigo_grupo) & (
            chamados["SERVICO_CODIGO"] == codigo_servico
        )
    chamados = chamados[filtro].copy()

    chamados["data_demanda"] = pd.to_datetime(chamados["DATA_DEMANDA"], errors="coerce")
    chamados["ano_mes"] = chamados["data_demanda"].dt.to_period("M").astype(str)
    chamados = chamados[(chamados["ano_mes"] >= PRIMEIRO_MES) & (chamados["ano_mes"] <= ULTIMO_MES)]

    chamados["bairro_norm"] = chamados["BAIRRO"].map(normalizar_bairro)

    descartados = (chamados["bairro_norm"] == BAIRRO_DESCARTAR).sum()
    chamados = chamados[chamados["bairro_norm"] != BAIRRO_DESCARTAR].copy()

    print(f"Chamados brutos (4 anos): {antes}")
    print(f"  duplicados exatos entre arquivos removidos: {duplicados_removidos}")
    print(f"  'manutencao em lampada apagada' (os dois codigos) dentro do periodo {PRIMEIRO_MES} a {ULTIMO_MES}: {len(chamados) + descartados}")
    print(f"  descartados por bairro nao informado: {descartados}")

    return chamados


def montar_painel_bairro_mes(chamados: pd.DataFrame, bairros_postes: set) -> pd.DataFrame:
    contagem = (
        chamados.groupby(["bairro_norm", "ano_mes"])
        .size()
        .rename("chamados_lampada_apagada")
        .reset_index()
    )

    bairros_chamados = set(chamados["bairro_norm"].unique())
    sem_correspondencia = bairros_chamados - bairros_postes
    print(f"Bairros distintos nos chamados de lampada apagada: {len(bairros_chamados)}")
    print(f"Bairros do cadastro de postes: {len(bairros_postes)}")
    print(f"Bairros com chamado mas sem poste cadastrado (apos normalizar): {len(sem_correspondencia)}")
    if sem_correspondencia:
        print(f"  exemplos: {sorted(sem_correspondencia)[:10]}")

    todos_bairros = sorted(bairros_postes | bairros_chamados)
    todos_meses = pd.period_range(PRIMEIRO_MES, ULTIMO_MES, freq="M").astype(str)
    painel = pd.MultiIndex.from_product(
        [todos_bairros, todos_meses], names=["bairro_norm", "ano_mes"]
    ).to_frame(index=False)

    painel = painel.merge(contagem, on=["bairro_norm", "ano_mes"], how="left")
    painel["chamados_lampada_apagada"] = painel["chamados_lampada_apagada"].fillna(0).astype(int)
    return painel


def adicionar_features_defasagem(painel: pd.DataFrame) -> pd.DataFrame:
    """Features de historico por bairro: sem elas, o modelo so enxerga
    caracteristicas estaticas do cadastro (potencia, % LED, RPA), que a EDA
    mostrou terem correlacao fraca com o rotulo (ver notebook, secao 5). O
    proprio historico de chamados e o sinal mais forte disponivel."""
    painel = painel.sort_values(["bairro_norm", "ano_mes"]).reset_index(drop=True)
    por_bairro = painel.groupby("bairro_norm")["chamados_lampada_apagada"]

    painel["chamados_lag1"] = por_bairro.shift(1)
    painel["chamados_lag2"] = por_bairro.shift(2)
    painel["chamados_lag3"] = por_bairro.shift(3)
    painel["media_movel_3m"] = por_bairro.transform(lambda s: s.shift(1).rolling(3).mean())

    # As primeiras linhas de cada bairro nao tem 3 meses de historico anterior
    # (comeco da serie, 2022-01 a 2022-03) - sem lag, ficariam fora do padrao
    # do resto e tem que sair antes de treinar.
    painel = painel.dropna(subset=["chamados_lag1", "chamados_lag2", "chamados_lag3", "media_movel_3m"])
    return painel.reset_index(drop=True)


def aplicar_rotulo_e_split(painel: pd.DataFrame) -> pd.DataFrame:
    teve_chamado = painel["chamados_lampada_apagada"] > 0
    por_bairro = painel.groupby("bairro_norm")

    # Rotulo principal (classificacao, usado no MQTT/dashboard: risco 0-1) e o
    # valor bruto do mes seguinte como auxiliar, para quem quiser comparar com
    # uma abordagem de regressao/ranking (ver decisao na secao 5 do notebook).
    painel["teve_chamado_mes_seguinte"] = teve_chamado.groupby(painel["bairro_norm"]).shift(-1)
    painel["chamados_mes_seguinte"] = por_bairro["chamados_lampada_apagada"].shift(-1)

    painel = painel.dropna(subset=["teve_chamado_mes_seguinte"]).copy()
    painel["teve_chamado_mes_seguinte"] = painel["teve_chamado_mes_seguinte"].astype(int)
    painel["chamados_mes_seguinte"] = painel["chamados_mes_seguinte"].astype(int)

    painel["conjunto"] = painel["ano_mes"].map(lambda am: "treino" if am < "2025-01" else "teste")
    return painel


def main() -> None:
    DADOS_PROCESSADOS.mkdir(parents=True, exist_ok=True)

    postes = carregar_postes()
    postes_por_bairro = agregar_postes_por_bairro(postes)
    postes_por_bairro.to_csv(DADOS_PROCESSADOS / "postes_por_bairro.csv", index=False)

    chamados = carregar_chamados_lampada_apagada()
    painel = montar_painel_bairro_mes(chamados, set(postes_por_bairro["bairro_norm"]))
    painel = painel.merge(postes_por_bairro, on="bairro_norm", how="left")

    # Bairros que tem chamado mas nenhum poste cadastrado (grafia composta que
    # nao bate com o cadastro, ver README) nao tem nenhuma feature de poste -
    # ficam de fora do que vai pro modelo em vez de entrar com tudo faltando.
    orfaos = painel["total_postes"].isna()
    if orfaos.any():
        print(f"Linhas descartadas por bairro sem poste cadastrado: {orfaos.sum()} ({painel.loc[orfaos, 'bairro_norm'].nunique()} bairros)")
    painel = painel[~orfaos].copy()

    painel = adicionar_features_defasagem(painel)
    painel = aplicar_rotulo_e_split(painel)
    painel.to_csv(DADOS_PROCESSADOS / "risco_bairro_mes.csv", index=False)

    print()
    print(f"Painel final: {len(painel)} linhas (bairro x mes)")
    print(painel["conjunto"].value_counts())
    print("Proporcao de 'teve_chamado_mes_seguinte=1':")
    print(painel.groupby("conjunto")["teve_chamado_mes_seguinte"].mean().round(3))
    print()
    print("Correlacao de cada feature de defasagem com o rotulo (treino):")
    treino = painel[painel["conjunto"] == "treino"]
    print(
        treino[["chamados_lampada_apagada", "chamados_lag1", "media_movel_3m", "teve_chamado_mes_seguinte"]]
        .corr()["teve_chamado_mes_seguinte"]
        .round(3)
    )
    print()
    print(f"Salvo em {DADOS_PROCESSADOS / 'postes_por_bairro.csv'}")
    print(f"Salvo em {DADOS_PROCESSADOS / 'risco_bairro_mes.csv'}")


if __name__ == "__main__":
    main()
