"""Partes da central da maquete: dados da Emlurb, simulador de postes (mesma lógica do firmware),
coletor (SQLite) e detector de anomalias."""

import json
import sqlite3
from types import SimpleNamespace

import numpy as np
import pandas as pd

from preparar_dados import normalizar_bairro


# ---------------- dados da Emlurb ----------------
def test_normalizar_bairro_tira_acento_e_corrige_grafia():
    assert normalizar_bairro("Boa  Viagem ") == "BOA VIAGEM"
    assert normalizar_bairro("Graças") == "GRACAS"
    assert normalizar_bairro("CIDADDE UNIVERSITARIA") == "CIDADE UNIVERSITARIA"
    assert normalizar_bairro("IMBIRBEIRA") == "IMBIRIBEIRA"


# ---------------- simulador de postes ----------------
def _poste(numero=3):
    import simulador
    return simulador.PosteVirtual(numero)          # cria o cliente MQTT, mas não conecta


def test_poste_segue_a_logica_do_firmware(monkeypatch):
    import simulador
    p = _poste()
    p.desgaste, p.ritmo_desgaste = 0.2, 0.0
    monkeypatch.setattr(p, "ler_luz", lambda agora: 3500)        # dia
    d = p.passo()
    assert d["estado"] == "DIA" and d["pct"] == 0
    monkeypatch.setattr(p, "ler_luz", lambda agora: 300)         # noite, rua vazia
    p.presenca_ate = 0
    monkeypatch.setattr(simulador.random, "random", lambda: 0.99)   # ninguém passa
    p.pedido = 40
    d = p.passo()
    assert d["estado"] == "DIMERIZADO" and d["pct"] == 70        # piso CPTED
    p.pedido = 90
    assert p.passo()["pct"] == 90                                # comando sobe acima do piso
    p.desgaste = 0.8
    assert p.passo()["estado"] == "FALHA"


def test_poste_aceita_comando_nos_dois_formatos():
    p = _poste()
    for texto, esperado in (('{"potencia": 85}', 85), ("75", 75)):
        p.ao_receber(None, None, SimpleNamespace(payload=texto.encode(), topic="g17/poste/P03/comando"))
        assert p.pedido == esperado
    p.ao_receber(None, None, SimpleNamespace(payload=b"lixo", topic="g17/poste/P03/comando"))
    assert p.pedido == 75


def test_defeito_do_sensor_de_luz_trava_a_leitura(monkeypatch):
    import simulador
    monkeypatch.setattr(simulador, "DEFEITO_LUZ", {"P06"})
    p = simulador.PosteVirtual(6)
    dia3 = p.inicio + 2.5 * simulador.CICLO_S
    assert p.sensor_travado(dia3) and p.ler_luz(dia3) == simulador.LUZ_TRAVADA
    assert not p.sensor_travado(p.inicio + 0.5 * simulador.CICLO_S)


# ---------------- coletor ----------------
def test_coletor_grava_e_alerta_falha_uma_vez(tmp_path, monkeypatch):
    import coletor
    monkeypatch.setattr(coletor, "DB_PATH", tmp_path / "central.db")
    monkeypatch.setattr(coletor, "TELEGRAM_TOKEN", "")
    c = coletor.Coletor()
    tele = {"id": "P05", "luz": 100, "noite": 1, "dist": 999, "presenca": 0, "desgaste": 0.8, "pct": 70,
            "estado": "FALHA", "pedido": 40, "uptime": 10}
    for _ in range(3):
        c.ao_receber(None, None, SimpleNamespace(topic="g17/poste/P05/telemetria", payload=json.dumps(tele).encode(),
                                                 retain=False))
    c.ao_receber(None, None, SimpleNamespace(topic="g17/poste/P05/anomalia", payload=b'{"anomalo":1}', retain=False))
    c.ao_receber(None, None, SimpleNamespace(topic="g17/poste/P05/telemetria", payload=b"nao e json", retain=False))
    db = sqlite3.connect(tmp_path / "central.db")
    assert db.execute("SELECT COUNT(*) FROM telemetria").fetchone()[0] == 3
    assert db.execute("SELECT COUNT(*) FROM alertas WHERE tipo = 'falha'").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM anomalia").fetchone()[0] == 1


# ---------------- detector de anomalias ----------------
def _telemetria_normal(n_postes=5, leituras=120, semente=0):
    rng = np.random.default_rng(semente)
    linhas = []
    for p in range(n_postes):
        for i in range(leituras):
            noite = int((i // 30) % 2)
            luz = int(300 + rng.normal(0, 60)) if noite else int(3200 + rng.normal(0, 60))
            presenca = int(noite and rng.uniform() < 0.15)
            pct = 0 if not noite else (100 if presenca else 70)
            linhas.append({"recebido_em": f"2026-11-26T{i // 60:02d}:{i % 60:02d}:{p:02d}", "id": f"P{p:02d}", "luz": luz,
                           "noite": noite, "dist": 3 if presenca else 999, "presenca": presenca, "pct": pct, "pedido": 40})
    return pd.DataFrame(linhas)


def test_motivo_explica_os_defeitos():
    from anomalia_telemetria import motivo
    base = {"luz": 300, "luz_std": 50, "noite": 1, "presenca": 0, "dist": 400, "pct": 70, "desvio_pct": 0,
            "incoerencia_noite": 0}
    assert "travado" in motivo(pd.Series({**base, "luz_std": 0}))
    assert "aceso de dia" in motivo(pd.Series({**base, "noite": 0, "pct": 70}))
    assert "piso" in motivo(pd.Series({**base, "pct": 0}))
    assert "ultrassônico" in motivo(pd.Series({**base, "presenca": 1}))
    # saturação do ADC com luz forte não é "sensor travado"
    assert "travado" not in motivo(pd.Series({**base, "luz": 4095, "luz_std": 0, "noite": 0, "pct": 0}))


def test_detector_treina_e_pega_sensor_travado():
    import anomalia_telemetria as A
    meta = A.treinar(_telemetria_normal(), usar_mlflow=False, salvar=False)
    assert meta["modelo"] in ("isolation_forest", "local_outlier_factor", "hibrido_isolation_forest",
                              "hibrido_local_outlier_factor")
    assert set(meta["metricas"]) >= {"regra_fixa", "isolation_forest", "local_outlier_factor"}
