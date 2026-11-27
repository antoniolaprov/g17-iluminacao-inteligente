"""Simulador do parque (g.5) e preparação dos dados do modelo de falha (g.2/g.3), sem vazamento."""

import numpy as np
import pandas as pd

from banco_parque import COLUNAS_TELEMETRIA
from parque import Parque, carregar_premissas
from parque_features import FEATURES, JANELA_DIAS, construir_features, limpar_telemetria, linhas_para_modelo, rotular


def test_simulador_e_deterministico_com_a_semente():
    p = carregar_premissas({"luminarias": 20, "luminarias_minimo_por_bairro": 1})
    a, b = Parque(p, 10.0).simular(30), Parque(p, 10.0).simular(30)
    pd.testing.assert_frame_equal(a, b)


def test_telemetria_tem_o_contrato_do_banco(parque_pequeno):
    _, tel = parque_pequeno
    assert list(tel.columns) == COLUNAS_TELEMETRIA
    assert set(tel["estado"]) <= {"OK", "CINTILANDO", "APAGADA"}
    assert tel["falha"].sum() > 0, "o parque de teste precisa ter falhas"


def test_apagada_nao_consome_e_luminaria_volta_nova(parque_pequeno):
    _, tel = parque_pequeno
    apagadas = tel[(tel["estado"] == "APAGADA") & (tel["falha"] == 0)]
    assert (apagadas["corrente_media_a"] == 0).all()
    # depois de uma falha, as horas acumuladas recomeçam perto de zero
    lum = tel[tel["falha"] == 1]["id_luminaria"].iloc[0]
    serie = tel[tel["id_luminaria"] == lum].sort_values("data")
    assert serie["horas_acumuladas"].diff().min() < -1000


def test_limpeza_trata_leituras_impossiveis_e_duplicatas(parque_pequeno):
    _, tel = parque_pequeno
    sujo = pd.concat([tel, tel.head(5)])                       # 5 duplicatas
    sujo.iloc[10, sujo.columns.get_loc("tensao_media_v")] = 0.0  # leitura impossível
    limpo, rel = limpar_telemetria(sujo)
    assert rel["duplicadas"] >= 5
    assert rel["leituras_invalidas"]["tensao_media_v"] >= 1
    assert limpo["tensao_media_v"].between(150, 400).all()
    assert not limpo.duplicated(["id_luminaria", "data"]).any()


def test_rotulo_olha_14_dias_a_frente():
    datas = pd.date_range("2025-01-01", periods=40)
    df = pd.DataFrame({"id_luminaria": "L001", "data": datas, "falha": 0})
    df.loc[df["data"] == "2025-01-20", "falha"] = 1
    r = rotular(df).set_index("data")
    assert r.loc["2025-01-06", "y"] == 1          # falha 14 dias depois: positivo
    assert r.loc["2025-01-05", "y"] == 0          # 15 dias depois: fora da janela
    assert r.loc["2025-01-19", "y"] == 1
    assert r.loc["2025-01-20", "y"] == 0          # o próprio dia da falha não conta
    assert not r.loc["2025-02-09", "rotulo_completo"]   # sem os 14 dias seguintes observados


def test_features_nao_usam_o_futuro(parque_pequeno):
    catalogo, tel = parque_pequeno
    limpo, _ = limpar_telemetria(tel)
    corte = limpo["data"].min() + pd.Timedelta(days=120)
    completo = construir_features(limpo, catalogo)
    so_passado = construir_features(limpo[limpo["data"] <= corte], catalogo)
    a = completo[completo["data"] == corte].set_index("id_luminaria")[FEATURES]
    b = so_passado[so_passado["data"] == corte].set_index("id_luminaria")[FEATURES]
    pd.testing.assert_frame_equal(a.sort_index(), b.sort_index())


def test_linhas_do_modelo_excluem_apagadas(parque_pequeno):
    catalogo, tel = parque_pequeno
    limpo, _ = limpar_telemetria(tel)
    df = construir_features(limpo, catalogo)
    ok = linhas_para_modelo(df)
    assert not (df.loc[ok, "estado"] == "APAGADA").any()
    assert np.isfinite(df.loc[ok, FEATURES].to_numpy()).all()
    assert JANELA_DIAS == 14
