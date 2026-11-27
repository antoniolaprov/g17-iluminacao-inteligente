"""Teste automático de segurança da dimerização (proposta, g.6): para todos os comandos gerados,
nenhuma luminária pode ficar abaixo do limite aplicável. Critério de aceite: 0% de violações."""

import pandas as pd

from dimerizacao import HORAS_NOITE, HORAS_PICO, ILUMINANCIA_MIN, PISOS_CPTED, comando_poste, economia, piso_abnt, plano, teste_seguranca


def test_nenhuma_violacao_no_parque_simulado(parque_pequeno):
    catalogo, _ = parque_pequeno
    df = plano(catalogo)
    resultado = teste_seguranca(df)
    assert resultado["comandos"] == len(catalogo) * len(HORAS_NOITE)
    assert resultado["violacoes"] == 0, df[df["viola"] == 1].head()


def test_pisos_cpted_e_abnt_respeitados(parque_pequeno):
    catalogo, _ = parque_pequeno
    df = plano(catalogo)
    assert (df["pct_final"] >= df["piso_cpted"]).all()
    assert (df["e_estimada_lx"] >= df["e_min_lx"] - 1e-9).all()
    alta_no_pico = df[(df["nivel_cpted"] == "alta") & df["hora"].isin(HORAS_PICO)]
    assert (alta_no_pico["pct_final"] == 100).all(), "prioridade alta não é dimerizada no pico noturno"
    assert (df.loc[df["nivel_cpted"] == "alta", "pct_final"] >= PISOS_CPTED["alta"]).all()
    assert (df.loc[df["nivel_cpted"] == "media", "pct_final"] >= PISOS_CPTED["media"]).all()
    assert (df.loc[df["nivel_cpted"] == "baixa", "pct_final"] >= PISOS_CPTED["baixa"]).all()


def test_trecho_sem_dados_e_tratado_como_prioridade_alta(parque_pequeno):
    catalogo, _ = parque_pequeno
    sem_dados = catalogo.copy()
    sem_dados[["fluxo_pedestres", "vulnerabilidade", "relevancia_via"]] = None
    df = plano(sem_dados)
    assert (df["nivel_cpted"] == "alta").all()
    assert teste_seguranca(df)["violacoes"] == 0


def test_fail_safe_sem_comunicacao_vai_a_100(parque_pequeno):
    catalogo, _ = parque_pequeno
    sem_rede = pd.Series(False, index=catalogo["id_luminaria"])
    df = plano(catalogo, comunicacao_ok=sem_rede)
    assert (df["pct_final"] == 100).all()


def test_piso_abnt_cobre_projeto_com_pouca_margem():
    # projeto só 10% acima do mínimo: dimerizar para 50% deixaria a via abaixo da norma
    e_min = ILUMINANCIA_MIN["P3"]
    assert piso_abnt(e_min * 1.10, e_min) == 91
    assert piso_abnt(e_min * 2.0, e_min) == 50


def test_economia_positiva_e_menor_que_100(parque_pequeno):
    catalogo, _ = parque_pequeno
    eco = economia(plano(catalogo), potencia_media_recife_w=120)
    assert 0 < eco["economia_pct"] < 60
    assert eco["recife_mwh_ano_economizados"] > 0


def test_comando_dos_postes_nunca_abaixo_do_piso():
    for hora in HORAS_NOITE:
        for nivel_cpted in ("alta", "media", "baixa"):
            for fluxo in (0.0, 0.5, 1.0):
                pct = comando_poste(nivel_cpted, fluxo, hora)
                assert pct >= PISOS_CPTED[nivel_cpted]
                assert pct <= 100
    assert comando_poste("alta", 0.0, 19) == 100
