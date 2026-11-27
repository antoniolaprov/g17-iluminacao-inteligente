"""Score CPTED (proposta, g.4): pesos AHP consistentes e priorização com as regras combinadas."""

import numpy as np
import pandas as pd

from cpted import CRITERIOS, LIMITES, nivel, pesos_ahp, priorizar, score_cpted, sensibilidade


def test_pesos_ahp_somam_1_e_sao_consistentes():
    r = pesos_ahp()
    assert abs(sum(r["pesos"].values()) - 1) < 1e-6
    assert r["cr"] < 0.10 and r["consistente"]
    assert r["pesos"]["vulnerabilidade"] > r["pesos"]["fluxo_pedestres"] > r["pesos"]["relevancia_via"]


def test_matriz_inconsistente_e_detectada():
    ruim = np.array([[1, 9, 1 / 9], [1 / 9, 1, 9], [9, 1 / 9, 1]])
    assert not pesos_ahp(ruim)["consistente"]


def test_niveis_e_trecho_sem_dados():
    s = pd.Series([0.9, LIMITES["alta"], 0.5, LIMITES["media"], 0.1, np.nan])
    assert nivel(s).tolist() == ["alta", "alta", "media", "media", "baixa", "alta"]


def test_score_entre_0_e_1(parque_pequeno):
    catalogo, _ = parque_pequeno
    s = score_cpted(catalogo).dropna()
    assert s.between(0, 1).all()


def _previsoes(catalogo, rng):
    estado = np.where(rng.uniform(size=len(catalogo)) < 0.05, "APAGADA", "OK")
    return pd.DataFrame({"id_luminaria": catalogo["id_luminaria"], "prob_falha_14d": rng.uniform(0, 0.2, len(catalogo)),
                         "estado": estado})


def test_apagadas_tem_risco_maximo_e_ranking_completo(parque_pequeno):
    catalogo, _ = parque_pequeno
    prev = _previsoes(catalogo, np.random.default_rng(1))
    r = priorizar(prev, catalogo)
    assert len(r) == len(catalogo)
    assert (r.loc[r["estado"] == "APAGADA", "risco_relativo"] == 1).all()
    assert r["posicao"].tolist() == list(range(1, len(r) + 1))
    assert r["prioridade"].is_monotonic_decreasing


def test_sensibilidade_tem_todos_os_cenarios(parque_pequeno):
    catalogo, _ = parque_pequeno
    s = sensibilidade(_previsoes(catalogo, np.random.default_rng(2)), catalogo, k=10)
    assert len(s["cenarios"]) == 2 * len(CRITERIOS) + 2 + 1
    assert -1 <= s["spearman_minimo"] <= 1
