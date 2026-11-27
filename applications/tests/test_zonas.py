"""T19: entradas completas, reprodutibilidade, artefatos e contrato de zonas."""

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import zonas_prioritarias as Z


@pytest.fixture
def bases():
    # Três perfis bem separados e com mais de um bairro por grupo.
    postes = pd.DataFrame({"bairro_norm": [f"B{i:02}" for i in range(12)],
                           "total_postes": [10, 12, 15, 18, 200, 220, 240, 260, 4000, 4500, 5000, 5500]})
    linhas = [{"bairro_norm": bairro, "ano_mes": mes, "chamados_lampada_apagada": chamado}
              for mes in ["2025-01", "2025-02", "2025-03"]
              for bairro, chamado in zip(postes["bairro_norm"], [0, 1, 1, 2, 20, 22, 24, 26, 200, 220, 240, 260])]
    return pd.DataFrame(linhas), postes


def test_agrupamento_reproduzivel_sem_depender_da_ordem(bases):
    painel, postes = bases
    bairros, meta = Z.agrupar(painel, postes, meses=3)
    outro, meta2 = Z.agrupar(painel.sample(frac=1, random_state=2), postes.sample(frac=1, random_state=3), meses=3)
    pd.testing.assert_frame_equal(bairros, outro)
    assert meta == meta2
    assert bairros["bairro_norm"].nunique() == 12
    assert meta["k"] == max(meta["candidatos"], key=lambda c: (c["silhouette"], -c["k"]))["k"]
    assert sum(g["bairros"] for g in meta["grupos"]) == 12
    assert np.isfinite(bairros[Z.FEATURES + ["taxa_1000_postes"]]).all().all()
    assert meta["grupos"][0]["chamados_media_por_bairro"] >= meta["grupos"][-1]["chamados_media_por_bairro"]


def test_agregacao_usa_observacoes_da_janela_e_nao_alvo_futuro(bases):
    painel, postes = bases
    painel["chamados_mes_seguinte"] = 999999
    # Mês fora da janela pode ser diferente sem mudar o resultado.
    passado = painel[painel["ano_mes"] == "2025-01"].assign(ano_mes="2024-12", chamados_lampada_apagada=90000)
    p = pd.concat([passado, painel], ignore_index=True)
    bairros, periodo = Z.preparar(p, postes, meses=2)
    assert periodo == {"inicio": "2025-02", "fim": "2025-03", "meses": 2}
    assert bairros.loc[bairros["bairro_norm"] == "B11", "chamados_media_mensal"].iloc[0] == 260
    assert bairros.loc[bairros["bairro_norm"] == "B11", "chamados_total"].iloc[0] == 520
    assert "chamados_mes_seguinte" not in bairros


@pytest.mark.parametrize("problema", ["duplicata", "lacuna", "nulo", "negativo", "infinito", "sem_postes", "mes_invalido", "bairro_extra"])
def test_rejeita_dados_inconsistentes(bases, problema):
    painel, postes = bases
    if problema == "duplicata":
        painel = pd.concat([painel, painel.iloc[[0]]], ignore_index=True)
    elif problema == "lacuna":
        painel = painel.drop(index=0)
    elif problema in ("nulo", "negativo", "infinito"):
        painel = painel.astype({"chamados_lampada_apagada": float})
        painel.loc[0, "chamados_lampada_apagada"] = {"nulo": np.nan, "negativo": -1, "infinito": np.inf}[problema]
    elif problema == "sem_postes":
        postes.loc[0, "total_postes"] = 0
    elif problema == "mes_invalido":
        painel.loc[0, "ano_mes"] = "2025-13"
    else:
        postes.loc[0, "bairro_norm"] = "SEM CORRESPONDENCIA"
    with pytest.raises(ValueError):
        Z.agrupar(painel, postes, meses=3)


def test_perfis_identicos_e_k_invalido_falham_com_mensagem(bases):
    painel, postes = bases
    with pytest.raises(ValueError, match="k deve"):
        Z.agrupar(painel, postes, meses=3, k=99)
    painel["chamados_lampada_apagada"] = 1
    postes["total_postes"] = 10
    with pytest.raises(ValueError, match="perfis distintos"):
        Z.agrupar(painel, postes, meses=3)


def test_base_versionada_tem_94_bairros_e_artefatos_conferem():
    bairros, meta = Z.carregar()
    assert len(bairros) == bairros["bairro_norm"].nunique() == 94
    reconstruido, novo = Z.agrupar(pd.read_csv(Z.PAINEL), pd.read_csv(Z.POSTES))
    pd.testing.assert_frame_equal(bairros, reconstruido, check_dtype=False, atol=1e-7, rtol=0)
    assert novo["k"] == meta["k"]
    assert novo["silhouette"] == pytest.approx(meta["silhouette"], abs=1e-10)


def test_artefatos_inconsistentes_nao_sao_servidos(bases, tmp_path, monkeypatch):
    painel, postes = bases
    p, c = tmp_path / "painel.csv", tmp_path / "postes.csv"
    painel.to_csv(p, index=False)
    postes.to_csv(c, index=False)
    monkeypatch.setattr(Z, "PAINEL", p)
    monkeypatch.setattr(Z, "POSTES", c)
    saida = tmp_path / "saida"
    Z.gerar(saida, meses=3)
    assert len(Z.carregar(saida)[0]) == 12
    # Git pode converter quebras de linha ao clonar no Windows.
    csv = saida / "zonas_bairros.csv"
    for texto in (p, c, csv):
        texto.write_bytes(texto.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert len(Z.carregar(saida)[0]) == 12
    p.write_text(p.read_text() + "\n")
    with pytest.raises(ValueError, match="base processada mudou"):
        Z.carregar(saida)
    Z.gerar(saida, meses=3)
    csv = saida / "zonas_bairros.csv"
    csv.write_text(csv.read_text() + "\n")
    with pytest.raises(ValueError, match="inconsistentes"):
        Z.carregar(saida)


def test_api_zonas_independe_do_banco_do_parque(monkeypatch):
    import api
    monkeypatch.setattr(api, "_parque", lambda: pytest.fail("Zonas não deve acessar o parque simulado"))
    cliente = TestClient(api.app)
    resposta = cliente.get("/zonas")
    assert resposta.status_code == 200
    assert len(resposta.json()["bairros"]) == 94
    assert resposta.json()["metadados"]["k"] >= 2
    monkeypatch.setattr(Z, "carregar", lambda: (_ for _ in ()).throw(FileNotFoundError("sem artefato")))
    assert cliente.get("/zonas").status_code == 503
