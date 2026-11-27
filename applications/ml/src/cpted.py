"""
Score CPTED e priorização da manutenção (proposta, seção g.4; item 07 do backlog).

Critérios, normalizados de 0 a 1 (vêm do cadastro de luminárias, ver docs/PREMISSAS_SIMULADOR.md):
    fluxo_pedestres  proximidade de polos de circulação (paradas, escolas, comércio noturno);
    vulnerabilidade  vulnerabilidade noturna; parte vem da precariedade real da iluminação no
                     bairro (chamados da Emlurb por 1.000 postes), parte do entorno do trecho;
    relevancia_via   importância do trecho para quem anda a pé (classe de via ABNT e acesso a polos).

Pesos pelo AHP (Saaty, 1980): comparação par a par na escala 1-9, pesos = autovetor principal,
consistência aceita se CR < 0,10. As justificativas de cada comparação estão em JUSTIFICATIVAS e
devem ser revisadas pelo grupo (a proposta pede que cada comparação seja documentada).

Prioridade (g.4): prioridade = alfa x risco de falha + (1 - alfa) x score CPTED, com alfa = 0,5.
O risco de falha entra como RISCO RELATIVO (posição da probabilidade calibrada no parque, de 0 a 1):
a probabilidade bruta em 14 dias fica quase toda abaixo de 0,1, e somada assim ao score CPTED
(0 a 1) o CPTED decidiria sozinho. A análise de sensibilidade mostra o efeito dessa escolha
(cenário "probabilidade_bruta"). Luminária já apagada tem risco relativo 1 (falha certa: reparo).

Níveis (usados pela dimerização, g.1): alta >= 0,60; média >= 0,35; baixa < 0,35; trecho sem dados = alta.
"""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

CRITERIOS = ["fluxo_pedestres", "vulnerabilidade", "relevancia_via"]
# MATRIZ_AHP[i][j] = quanto o critério i é mais importante que o j (escala de Saaty)
MATRIZ_AHP = np.array([
    [1,   1 / 2, 2],
    [2,   1,     3],
    [1 / 2, 1 / 3, 1],
])
JUSTIFICATIVAS = {
    ("vulnerabilidade", "fluxo_pedestres"): "2 (um pouco mais importante): a proposta prioriza periferias e "
        "áreas vulneráveis; a pesquisa de campo apontou 'priorizar áreas mais precárias' (9 de 12) e 5 de 12 "
        "disseram que os problemas são mais comuns em bairros periféricos.",
    ("fluxo_pedestres", "relevancia_via"): "2 (um pouco mais importante): vigilância natural depende de haver "
        "gente circulando (Bertuzzi, 2021); a classe da via já entra no limite da ABNT.",
    ("vulnerabilidade", "relevancia_via"): "3 (moderadamente mais importante): vulnerabilidade noturna é o "
        "centro do argumento CPTED; relevância da via é um critério de apoio.",
}
INDICE_ALEATORIO = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12}   # Saaty
ALFA = 0.5
LIMITES = {"alta": 0.60, "media": 0.35}
K_TOPO = 20


def pesos_ahp(matriz: np.ndarray = MATRIZ_AHP) -> dict:
    valores, vetores = np.linalg.eig(matriz)
    i = int(np.argmax(valores.real))
    pesos = np.abs(vetores[:, i].real)
    pesos = pesos / pesos.sum()
    n = len(matriz)
    lambda_max = float(valores.real[i])
    ci = (lambda_max - n) / (n - 1)
    cr = ci / INDICE_ALEATORIO[n] if INDICE_ALEATORIO[n] else 0.0
    return {"pesos": dict(zip(CRITERIOS, pesos.round(4).tolist())), "lambda_max": round(lambda_max, 4),
            "ci": round(ci, 4), "cr": round(cr, 4), "consistente": cr < 0.10}


def score_cpted(catalogo: pd.DataFrame, pesos: dict | None = None) -> pd.Series:
    """Soma ponderada dos critérios; NaN quando falta algum critério (trecho sem dados)."""
    pesos = pesos or pesos_ahp()["pesos"]
    return sum(catalogo[c] * w for c, w in pesos.items())


def nivel(score: pd.Series) -> pd.Series:
    return pd.Series(np.select([score.isna(), score >= LIMITES["alta"], score >= LIMITES["media"]],
                               ["alta", "alta", "media"], "baixa"), index=score.index)


def priorizar(previsoes: pd.DataFrame, catalogo: pd.DataFrame, pesos: dict | None = None,
              alfa: float = ALFA, risco_bruto: bool = False) -> pd.DataFrame:
    """previsoes: id_luminaria, prob_falha_14d (NaN se apagada), estado. Devolve o ranking."""
    df = catalogo.merge(previsoes, on="id_luminaria", how="inner")
    df["score_cpted"] = score_cpted(df, pesos)
    df["nivel_cpted"] = nivel(df["score_cpted"])
    apagada = df["estado"] == "APAGADA"
    prob = df["prob_falha_14d"].where(~apagada, 1.0).fillna(0.0)
    df["risco_relativo"] = prob if risco_bruto else prob.rank(pct=True, method="average")
    df.loc[apagada, "risco_relativo"] = 1.0
    cpted = df["score_cpted"].fillna(1.0)          # sem dados: conservador, prioridade máxima no critério
    df["prioridade"] = alfa * df["risco_relativo"] + (1 - alfa) * cpted
    df = df.sort_values("prioridade", ascending=False).reset_index(drop=True)
    df["posicao"] = np.arange(1, len(df) + 1)
    return df


def sensibilidade(previsoes: pd.DataFrame, catalogo: pd.DataFrame, variacao: float = 0.20, k: int = K_TOPO) -> dict:
    """Varia cada peso e o alfa em ±20% e mede se o ranking muda: correlação de Spearman com o
    ranking base e sobreposição do top-k (g.4)."""
    base_pesos = pesos_ahp()["pesos"]
    base = priorizar(previsoes, catalogo, base_pesos)
    ordem_base = base.set_index("id_luminaria")["posicao"]
    topo_base = set(base.head(k)["id_luminaria"])
    cenarios = {}

    def comparar(nome: str, ranking: pd.DataFrame) -> None:
        ordem = ranking.set_index("id_luminaria")["posicao"].reindex(ordem_base.index)
        rho = spearmanr(ordem_base, ordem).statistic
        cenarios[nome] = {"spearman": round(float(rho), 4),
                          "sobreposicao_top_k": round(len(topo_base & set(ranking.head(k)["id_luminaria"])) / k, 3)}

    for criterio in CRITERIOS:
        for sinal in (+1, -1):
            pesos = dict(base_pesos)
            pesos[criterio] *= 1 + sinal * variacao
            total = sum(pesos.values())
            pesos = {c: w / total for c, w in pesos.items()}
            comparar(f"peso_{criterio}_{'+' if sinal > 0 else '-'}{int(variacao * 100)}%",
                     priorizar(previsoes, catalogo, pesos))
    for sinal in (+1, -1):
        comparar(f"alfa_{'+' if sinal > 0 else '-'}{int(variacao * 100)}%",
                 priorizar(previsoes, catalogo, base_pesos, ALFA * (1 + sinal * variacao)))
    comparar("probabilidade_bruta", priorizar(previsoes, catalogo, base_pesos, risco_bruto=True))
    variacoes = {n: c for n, c in cenarios.items() if n != "probabilidade_bruta"}
    return {"k": k, "cenarios": cenarios,
            "spearman_minimo": min(c["spearman"] for c in variacoes.values()),
            "sobreposicao_minima": min(c["sobreposicao_top_k"] for c in variacoes.values()),
            "estavel": min(c["spearman"] for c in variacoes.values()) >= 0.9}
