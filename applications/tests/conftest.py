"""Configuração comum dos testes: deixa os módulos da central importáveis e isola os bancos.

Rodar (no container, que já tem tudo instalado):
    docker compose run --rm --no-deps api python -m pytest tests -q
ou no PC, com as dependências de applications/requirements-central.txt:
    python -m pytest applications/tests -q
"""

import sys
from pathlib import Path

import pytest

APLICACOES = Path(__file__).resolve().parents[1]
for pasta in (APLICACOES, APLICACOES / "ml" / "src", APLICACOES / "simulador", APLICACOES / "backend"):
    sys.path.insert(0, str(pasta))


@pytest.fixture
def banco_parque_temporario(tmp_path, monkeypatch):
    """Banco do parque num SQLite temporário (nada toca o PostgreSQL nem o banco de verdade)."""
    import banco_parque
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'parque.db').as_posix()}")
    banco_parque._motores.clear()
    yield banco_parque
    banco_parque._motores.clear()


@pytest.fixture(scope="session")
def parque_pequeno():
    """Parque de 60 luminárias por 240 dias, gerado uma vez para todos os testes."""
    from parque import Parque, carregar_premissas
    premissas = carregar_premissas({"luminarias": 60, "luminarias_minimo_por_bairro": 3, "dias_historico": 240})
    parque = Parque(premissas, escala_risco=40.0)       # escala alta: mais falhas num parque pequeno
    telemetria = parque.simular(240)
    return parque.catalogo, telemetria
