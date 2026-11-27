"""Regressões de UX: recorte coerente, recuperação dos filtros e ausência de dados."""

from pathlib import Path
from unittest.mock import Mock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest


@pytest.fixture
def painel(monkeypatch):
    linhas = [
        {"id_luminaria": "L001", "bairro": "BAIRRO A", "estado": "APAGADA", "prob_falha_14d": None,
         "nivel_cpted": "alta", "score_cpted": 0.8, "prioridade": 0.9, "posicao": 1},
        {"id_luminaria": "L002", "bairro": "BAIRRO A", "estado": "CINTILANDO", "prob_falha_14d": 0.2,
         "nivel_cpted": "media", "score_cpted": 0.5, "prioridade": 0.6, "posicao": 2},
        {"id_luminaria": "L003", "bairro": "BAIRRO B", "estado": "OK", "prob_falha_14d": 0.01,
         "nivel_cpted": "baixa", "score_cpted": 0.1, "prioridade": 0.2, "posicao": 3},
    ]
    for i, linha in enumerate(linhas):
        linha.update(lat=-8.06 + i * 0.001, lon=-34.91, potencia_w=100, classe_via="P3")
    respostas = {
        "/luminarias": {"data_ref": "2026-11-27", "luminarias": linhas},
        "/alertas?limite=1000": {"alertas": [
            {"id_luminaria": "L001", "tipo": "apagada", "mensagem": "Alerta do bairro A"},
            {"id_luminaria": "L003", "tipo": "risco_alto", "mensagem": "Alerta do bairro B"},
        ]},
    }

    def get(url, **kwargs):
        caminho = "/" + url.split("/", 3)[3]
        if caminho in respostas:
            return Mock(status_code=200, json=lambda: respostas[caminho])
        return Mock(status_code=503, headers={"content-type": "application/json"},
                    json=lambda: {"detail": "Indisponível neste cenário de teste"})

    monkeypatch.setattr("requests.get", get)
    monkeypatch.setattr("streamlit_folium.st_folium", lambda *args, **kwargs: {})
    st.cache_data.clear()
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard_gestor/app.py"))
    yield app, respostas
    st.cache_data.clear()


def test_indicadores_lista_e_alertas_seguem_o_recorte(painel):
    app, _ = painel
    app.run(timeout=30)
    app.multiselect(key="bairros").set_value(["BAIRRO A"]).run()
    assert not app.exception
    assert [m.value for m in app.metric] == ["1", "1", "1"]
    assert set(app.dataframe[0].value["Luminária"]) == {"L001", "L002"}
    textos = " ".join(m.value for m in app.markdown)
    assert "Alerta do bairro A" in textos and "Alerta do bairro B" not in textos
    app.slider(key="so_risco").set_value(0.8).run()
    assert not app.exception
    assert list(app.dataframe[0].value["Luminária"]) == ["L001"]  # apagadas continuam para reparo
    assert app.selectbox[0].options == ["L001"]


def test_recorte_vazio_permite_limpar_filtros(painel):
    app, _ = painel
    app.run(timeout=30)
    app.multiselect(key="bairros").set_value(["BAIRRO B"])
    app.multiselect(key="niveis").set_value(["alta"]).run()
    assert not app.exception
    assert any("Nenhuma luminária corresponde" in i.value for i in app.info)
    next(b for b in app.button if b.label == "Limpar filtros").click().run()
    assert not app.exception
    assert app.multiselect(key="bairros").value == []
    assert app.multiselect(key="niveis").value == []
    assert len(app.dataframe[0].value) == 3


def test_api_sem_luminarias_mostra_recuperacao(painel):
    app, respostas = painel
    respostas["/luminarias"]["luminarias"] = []
    app.run(timeout=30)
    assert not app.exception
    assert any("Nenhuma luminária disponível" in i.value for i in app.info)
    assert any(b.label == "Tentar novamente" for b in app.button)


def test_atualizar_dados_renova_os_indicadores_na_mesma_interacao(painel):
    app, respostas = painel
    app.run(timeout=30)
    assert app.metric[1].value == "1"
    respostas["/luminarias"]["luminarias"][1]["estado"] = "OK"
    next(b for b in app.button if b.label == "Atualizar dados").click().run()
    assert not app.exception
    assert app.metric[1].value == "0"


def test_api_indisponivel_oferece_tentativa_sem_excecao(painel, monkeypatch):
    import requests
    app, _ = painel
    monkeypatch.setattr("requests.get", Mock(side_effect=requests.ConnectionError("conexão recusada")))
    app.run(timeout=30)
    assert not app.exception
    assert any("Não foi possível carregar" in w.value for w in app.warning)
    assert any(b.label == "Tentar novamente" for b in app.button)


def test_zonas_historicas_filtram_grupos_sem_depender_do_recorte_do_parque(painel):
    from zonas_prioritarias import carregar
    app, respostas = painel
    bairros, meta = carregar()
    respostas["/zonas"] = {"metadados": meta, "bairros": bairros.to_dict(orient="records")}
    app.run(timeout=30)
    assert not app.exception
    app.multiselect(key="zonas_historicas").set_value(["Z01"]).run()
    assert not app.exception
    tabela = app.dataframe[-1].value
    assert set(tabela["Grupo"]) == {"Z01"}
    assert len(tabela) == meta["grupos"][0]["bairros"]
    app.multiselect(key="bairros").set_value(["BAIRRO B"]).run()
    assert not app.exception
    assert len(app.dataframe[-1].value) == len(tabela)
