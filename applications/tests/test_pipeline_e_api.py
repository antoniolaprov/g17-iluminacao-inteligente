"""Pipeline do parque ponta a ponta (validar -> prever -> priorizar -> dimerizar) num banco
temporário, e as rotas da API (risco por bairro, rota, anomalias e parque)."""

import json

import joblib
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from xgboost import XGBClassifier

from parque_features import FEATURES, construir_features, limpar_telemetria, linhas_para_modelo, rotular


@pytest.fixture
def pipeline_rodado(banco_parque_temporario, parque_pequeno, tmp_path, monkeypatch):
    import pipeline_parque as P
    catalogo, tel = parque_pequeno
    banco_parque_temporario.gravar(catalogo, "luminaria", substituir=True)
    banco_parque_temporario.gravar(tel.assign(origem="historico", recebido_em=None), "telemetria_luminaria", substituir=True)
    # modelo pequeno só para o teste (o de verdade sai do treinar_falha.py)
    limpo, _ = limpar_telemetria(tel)
    df = rotular(construir_features(limpo, catalogo))
    df = df[linhas_para_modelo(df)]
    modelo = XGBClassifier(n_estimators=30, max_depth=3).fit(df[FEATURES], df["y"])
    monkeypatch.setattr(P, "MODELO", tmp_path / "modelo_falha.joblib")
    monkeypatch.setattr(P, "METADADOS", tmp_path / "metadados_falha.json")
    joblib.dump(modelo, P.MODELO)
    P.METADADOS.write_text(json.dumps({"modelo": "xgboost_teste", "limiar_f1": 0.2}), encoding="utf-8")
    P.tudo(publicar=False)
    return banco_parque_temporario


def test_pipeline_grava_todas_as_tabelas(pipeline_rodado, parque_pequeno):
    bp = pipeline_rodado
    catalogo, _ = parque_pequeno
    assert bp.contar("previsao_falha") > 0
    assert bp.contar("prioridade") == len(catalogo)
    assert bp.contar("plano_dimerizacao") == len(catalogo) * 12
    etapas = set(bp.ler("SELECT etapa FROM pipeline_execucao")["etapa"])
    assert etapas == {"validar", "prever", "priorizar", "dimerizar"}
    dim = bp.ler("SELECT rejeitadas FROM pipeline_execucao WHERE etapa = 'dimerizar'")
    assert int(dim["rejeitadas"].iloc[0]) == 0, "teste de segurança da dimerização reprovado"
    prev = bp.ler("SELECT prob_falha_14d FROM previsao_falha").dropna()
    assert prev["prob_falha_14d"].between(0, 1).all()


@pytest.fixture
def cliente():
    import api
    return TestClient(api.app)


def test_api_abre_dashboard_da_maquete_no_broker_local(cliente):
    resposta = cliente.get("/maquete?broker=ws://localhost:9001")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")
    assert "new URLSearchParams(location.search).get('broker')" in resposta.text
    assert "mqtt.connect(cfg.url" in resposta.text


def test_api_parque(pipeline_rodado, cliente):
    r = cliente.get("/luminarias")
    assert r.status_code == 200 and r.json()["total"] > 0
    primeira = r.json()["luminarias"][0]
    assert {"lat", "lon", "prob_falha_14d", "score_cpted", "nivel_cpted", "prioridade"} <= set(primeira)
    assert cliente.get(f"/luminarias/{primeira['id_luminaria']}").status_code == 200
    assert cliente.get("/luminarias/NAO_EXISTE").status_code == 404
    assert cliente.get("/prioridades?limite=5").json()["prioridades"][0]["posicao"] == 1
    assert cliente.get("/previsoes?limite=5").status_code == 200
    assert cliente.get("/alertas").status_code == 200
    dim = cliente.get("/dimerizacao").json()
    assert dim["seguranca"]["aprovado"] and len(dim["por_hora"]) == 12
    cp = cliente.get("/cpted").json()
    assert cp["consistente"] and "sensibilidade" in cp


def test_api_parque_sem_dados_responde_503(banco_parque_temporario, cliente):
    assert cliente.get("/luminarias").status_code == 503


def test_api_risco_por_bairro(cliente):
    saude = cliente.get("/saude").json()
    assert saude["status"] == "ok" and saude["bairros"] > 0
    r = cliente.get("/risco/boa viagem")
    assert r.status_code == 200 and r.json()["bairro"] == "BOA VIAGEM"
    assert 0 <= r.json()["risco"] <= 1
    assert cliente.get("/risco/bairro inventado").status_code == 404
    assert cliente.get("/poste/P01").json()["bairro"] == "BOA VIAGEM"
    assert len(cliente.get("/riscos?limite=5").json()) == 5


def test_api_rota(cliente):
    r = cliente.get("/rota?dist_s1=3&hora=21").json()
    assert r["direcao_provavel"] in ("esquerda", "direita")
    assert abs(sum(r["probabilidades"].values()) - 1) < 1e-3
