"""Referência cadastral e propagação API/MQTT, sem rede ou hardware."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
import publicar_risco as publicar
from referencia_cadastro import gerar, selecionar

ML = Path(__file__).resolve().parents[1] / "ml"


def test_selecao_reproduzivel_e_ids_invalidos():
    cadastro = pd.DataFrame({"id_ponto": [None, "0", "x", "1", "1", "20", "003", "9"],
                             "bairro": ["Boa Viagem"] * 4 + ["Recife"] + [" BOA VIAGEM "] * 3})
    resultado = selecionar(cadastro)
    assert resultado["registro"]["id_ponto"] == "003"
    assert resultado["candidatos_unicos"] == 3
    assert selecionar(cadastro.sample(frac=1, random_state=7)) == resultado


@pytest.mark.parametrize("cadastro,bairro", [
    (pd.DataFrame({"id_ponto": ["1"]}), "Boa Viagem"),
    (pd.DataFrame({"id_ponto": [None, "0", "a"], "bairro": ["Boa Viagem"] * 3}), "Boa Viagem"),
    (pd.DataFrame({"id_ponto": ["1"], "bairro": ["Boa Viagem"]}), ""),
])
def test_rejeita_cadastro_sem_referencia(cadastro, bairro):
    with pytest.raises(ValueError):
        selecionar(cadastro, bairro)


def test_evidencia_reproduz_csv_sem_endereco(tmp_path):
    csv = tmp_path / "postes.csv"
    csv.write_text("id_ponto;bairro;endereco;latitude\n2;Boa Viagem;Rua A;-8\n", encoding="utf-8")
    saida = tmp_path / "recorte.json"
    evidencia = gerar(csv, saida)
    assert evidencia == json.loads(saida.read_text(encoding="utf-8"))
    assert evidencia["fonte"]["sha256_csv"] == hashlib.sha256(csv.read_bytes()).hexdigest()
    assert evidencia["fonte"]["linhas_csv"] == 1
    assert set(evidencia["registro"]) == {"id_ponto", "bairro", "bairro_normalizado", "rpa", "tipo_lampa", "potencia"}


def test_config_api_e_fallback_preservam_referencia():
    evidencia = json.loads((ML / "data/processed/referencia_p01.json").read_text(encoding="utf-8"))
    config = json.loads((ML / "config.json").read_text(encoding="utf-8"))
    cliente = TestClient(api.app)
    resposta = cliente.get("/poste/P01")
    assert resposta.status_code == 200
    for dados in (config["postes"]["P01"], resposta.json(), publicar.risco_pelo_arquivo("P01")):
        assert dados["id_ponto"] == evidencia["registro"]["id_ponto"]
        assert isinstance(dados["id_ponto"], str)
        assert dados["vinculo_cadastro"] == "referencia_demonstrativa"
    assert resposta.json()["bairro"] == evidencia["registro"]["bairro_normalizado"]
    assert cliente.get("/poste/P02").json()["id_ponto"] is None
    assert cliente.get("/poste/INEXISTENTE").status_code == 404
    legado = publicar.risco_pelo_arquivo("P01")
    legado.pop("id_ponto")
    legado.pop("vinculo_cadastro")
    assert publicar.payload_risco(legado)["id_ponto"] is None


@pytest.mark.parametrize("modo_api", ["disponivel", "indisponivel", "queda", "json_invalido"])
@pytest.mark.parametrize("sem_comando", [True, False])
def test_publicacao_preserva_topicos_e_comandos(monkeypatch, modo_api, sem_comando):
    cliente_api = TestClient(api.app)
    def buscar(poste):
        if modo_api == "indisponivel" or (modo_api == "queda" and poste == "P02"):
            raise URLError("indisponível no teste")
        if modo_api == "json_invalido" and poste == "P02":
            raise json.JSONDecodeError("JSON inválido", "", 0)
        dados = cliente_api.get(f"/poste/{poste}").json()
        dados["risco"] = 0.123456
        return dados
    mensagens = []
    class Cliente:
        def connect(self, *args, **kwargs): pass
        def loop_start(self): pass
        def loop_stop(self): pass
        def disconnect(self): pass
        def publish(self, topico, payload, qos, retain=False):
            mensagens.append((topico, json.loads(payload), qos, retain))
            return SimpleNamespace(wait_for_publish=lambda **kwargs: None)
    monkeypatch.setattr(publicar, "risco_pela_api", buscar)
    monkeypatch.setattr(publicar, "novo_cliente", lambda _: Cliente())
    monkeypatch.setattr("sys.argv", ["publicar_risco.py"] + (["--sem-comando"] if sem_comando else []))
    publicar.main()
    riscos = [m for m in mensagens if m[0].endswith("/risco")]
    comandos = [m for m in mensagens if m[0].endswith("/comando")]
    assert len(riscos) == len(publicar.CONFIG["postes"])
    for topico, payload, qos, retido in riscos:
        poste = topico.split("/")[2]
        assert topico == f"g17/poste/{poste}/risco"
        assert qos == 1 and retido
        assert payload["id_ponto"] == publicar.CONFIG["postes"][poste]["id_ponto"]
        assert payload["vinculo_cadastro"] == publicar.CONFIG["postes"][poste].get("vinculo_cadastro")
        risco_esperado = (0.123456 if modo_api == "disponivel"
                          else publicar.risco_pelo_arquivo(poste)["risco"])
        assert payload["risco"] == risco_esperado
    assert len(comandos) == (0 if sem_comando else len(riscos))
    for _, payload, qos, retido in comandos:
        assert set(payload) == {"potencia"}
        assert payload["potencia"] in (70, 80, 90)
        assert qos == 1 and not retido
