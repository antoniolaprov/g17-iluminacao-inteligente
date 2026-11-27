"""Banco do parque de luminárias simuladas (proposta, item 01: telemetria persistida em PostgreSQL).

No Docker, DATABASE_URL aponta para o PostgreSQL do docker-compose.yml. Sem a variável (testes,
scripts rodando direto no PC), usa um arquivo SQLite em applications/ml/data/simulado/parque.db,
com as mesmas tabelas: o mesmo código roda nos dois.

Tabelas:
    luminaria             cadastro (bairro, coordenadas, potência, classe de via, critérios CPTED)
    telemetria_luminaria  uma linha por luminária por dia simulado (histórico + o que chega por MQTT)
    pipeline_execucao     o que cada etapa do pipeline leu, validou e rejeitou
    previsao_falha        P(falha em 14 dias) calibrada, por luminária e data de referência
    prioridade            ranking de manutenção (risco de falha + score CPTED)
    alerta_luminaria      alertas para a equipe (apagada, cintilando, risco alto)
    plano_dimerizacao     potência por hora de cada luminária, com os pisos CPTED e ABNT
"""

import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

APLICACOES = Path(__file__).resolve().parent
PASTA_SIMULADO = APLICACOES / "ml" / "data" / "simulado"
URL_PADRAO = f"sqlite:///{(PASTA_SIMULADO / 'parque.db').as_posix()}"

COLUNAS_TELEMETRIA = [
    "data", "id_luminaria", "temp_media_c", "temp_max_c", "tensao_media_v", "tensao_min_v", "tensao_max_v",
    "corrente_media_a", "ripple_pct", "horas_operacao", "horas_acumuladas", "ciclos_dia", "ciclos_acumulados",
    "surtos_dia", "pct_medio", "estado", "falha",
]

ESQUEMA = [
    """CREATE TABLE IF NOT EXISTS luminaria (
        id_luminaria TEXT PRIMARY KEY, bairro TEXT, lat REAL, lon REAL, potencia_w REAL, classe_via TEXT,
        e_projeto_lx REAL, fluxo_pedestres REAL, vulnerabilidade REAL, relevancia_via REAL)""",
    """CREATE TABLE IF NOT EXISTS telemetria_luminaria (
        data TEXT NOT NULL, id_luminaria TEXT NOT NULL, temp_media_c REAL, temp_max_c REAL,
        tensao_media_v REAL, tensao_min_v REAL, tensao_max_v REAL, corrente_media_a REAL, ripple_pct REAL,
        horas_operacao REAL, horas_acumuladas REAL, ciclos_dia REAL, ciclos_acumulados REAL, surtos_dia REAL,
        pct_medio REAL, estado TEXT, falha INTEGER, origem TEXT, recebido_em TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_tel_lum ON telemetria_luminaria (id_luminaria, data)",
    "CREATE INDEX IF NOT EXISTS idx_tel_data ON telemetria_luminaria (data)",
    """CREATE TABLE IF NOT EXISTS pipeline_execucao (
        executado_em TEXT, etapa TEXT, linhas_lidas INTEGER, linhas_validas INTEGER, rejeitadas INTEGER,
        detalhes TEXT)""",
    """CREATE TABLE IF NOT EXISTS previsao_falha (
        data_ref TEXT, id_luminaria TEXT, prob_falha_14d REAL, acima_limiar INTEGER, modelo TEXT, gerado_em TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_prev ON previsao_falha (data_ref, id_luminaria)",
    """CREATE TABLE IF NOT EXISTS prioridade (
        data_ref TEXT, id_luminaria TEXT, prob_falha_14d REAL, risco_relativo REAL, score_cpted REAL,
        nivel_cpted TEXT, prioridade REAL, posicao INTEGER, estado TEXT, gerado_em TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_prio ON prioridade (data_ref)",
    """CREATE TABLE IF NOT EXISTS alerta_luminaria (
        gerado_em TEXT, data_ref TEXT, id_luminaria TEXT, tipo TEXT, mensagem TEXT)""",
    """CREATE TABLE IF NOT EXISTS plano_dimerizacao (
        data_ref TEXT, id_luminaria TEXT, hora INTEGER, demanda REAL, pct_desejado REAL, piso_cpted REAL,
        piso_abnt REAL, pct_final REAL, e_estimada_lx REAL, e_min_lx REAL, viola INTEGER)""",
]

_motores: dict[str, Engine] = {}


def url_banco() -> str:
    return os.getenv("DATABASE_URL") or URL_PADRAO


def motor() -> Engine:
    """Engine do SQLAlchemy (uma por URL), com as tabelas criadas."""
    url = url_banco()
    if url not in _motores:
        if url.startswith("sqlite"):
            PASTA_SIMULADO.mkdir(parents=True, exist_ok=True)
        eng = create_engine(url, pool_pre_ping=True, future=True)
        with eng.begin() as con:
            for ddl in ESQUEMA:
                con.execute(text(ddl))
        _motores[url] = eng
    return _motores[url]


def ler(sql: str, **params) -> pd.DataFrame:
    with motor().connect() as con:
        return pd.read_sql_query(text(sql), con, params=params)


def executar(sql: str, **params) -> None:
    with motor().begin() as con:
        con.execute(text(sql), params)


def gravar(df: pd.DataFrame, tabela: str, substituir: bool = False) -> None:
    """Acrescenta (ou substitui o conteúdo de) uma tabela. Substituir apaga as linhas, mas mantém a
    tabela e os índices, para o esquema continuar o mesmo nos dois bancos."""
    if df.empty and not substituir:
        return
    with motor().begin() as con:
        if substituir:
            con.execute(text(f"DELETE FROM {tabela}"))
        if not df.empty:
            # 1000 linhas por INSERT: fica abaixo do limite de parâmetros do SQLite e do PostgreSQL
            df.to_sql(tabela, con, if_exists="append", index=False, chunksize=1000, method="multi")


def contar(tabela: str) -> int:
    try:
        return int(ler(f"SELECT COUNT(*) AS n FROM {tabela}")["n"].iloc[0])
    except Exception:
        return 0
