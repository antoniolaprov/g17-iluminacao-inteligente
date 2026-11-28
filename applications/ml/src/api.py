"""
API de inferência do risco por bairro (FastAPI).

Rotas:
    GET  /saude                 status da API e do modelo carregado (usado pelo docker compose)
    GET  /risco/{bairro}        risco previsto do bairro (aceita acento e minúsculas)
    GET  /riscos                ranking de todos os bairros (?criterio=contagem|taxa&limite=N)
    GET  /poste/{poste_id}      bairro do poste (config.json), risco e potência sugerida
    POST /prever                previsão do modelo para features enviadas no corpo (JSON)
    GET  /rota?dist_s1=4.2      cascata em Y: braço provável do pedestre que passou pelo S1
    GET  /rota/metricas         treino do modelo de rota e acurácia ao vivo
    GET  /anomalias             última análise do detector de anomalias de cada poste (telemetria ao vivo)

Parque de luminárias (proposta: manutenção preditiva, CPTED e dimerização; banco PostgreSQL):
    GET  /luminarias            estado, P(falha em 14 dias), score CPTED e prioridade de cada luminária
    GET  /luminarias/{id}       cadastro, telemetria dos últimos dias e histórico de previsões
    GET  /previsoes             luminárias com maior P(falha em 14 dias) na data mais recente
    GET  /prioridades           lista de manutenção priorizada (risco de falha + CPTED)
    GET  /alertas               alertas para a equipe (apagada, cintilando, risco alto)
    GET  /falha/metricas        protocolo e métricas do modelo de falha (PR-AUC, recall@k, Brier...)
    GET  /cpted                 pesos AHP, consistência e análise de sensibilidade do ranking
    GET  /dimerizacao           plano por hora, teste de segurança (0% de violações) e economia
    GET  /pipeline              últimas execuções de cada etapa do pipeline

Lê o que o treinar.py gera em applications/ml/models/ (risco_por_bairro.csv, metadados.json,
modelo_risco.joblib) e recarrega sozinha quando esses arquivos mudam (novo treino).

Uso:
    uvicorn api:app --app-dir applications/ml/src --port 8000
    Documentação interativa em http://localhost:8000/docs
"""

import json
import math
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))     # applications/ (banco_parque)
from preparar_dados import normalizar_bairro  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
MODELOS = RAIZ / "models"
ARQ_RISCO = MODELOS / "risco_por_bairro.csv"
ARQ_META = MODELOS / "metadados.json"
ARQ_MODELO = MODELOS / "modelo_risco.joblib"
ARQ_CONFIG = RAIZ / "config.json"

app = FastAPI(title="G17 - Risco de lâmpada apagada por bairro", version="1.0")


@app.get("/maquete", include_in_schema=False)
def painel_maquete() -> FileResponse:
    return FileResponse(RAIZ.parent / "dashboard" / "index.html", media_type="text/html")


class Estado:
    """Cache dos arquivos do modelo, recarregado quando algum muda no disco."""
    marca = None
    risco = None
    meta = {}
    config = {}
    modelo = None


def _marca() -> tuple:
    return tuple(p.stat().st_mtime if p.exists() else 0 for p in (ARQ_RISCO, ARQ_META, ARQ_MODELO, ARQ_CONFIG))


def carregar() -> Estado:
    marca = _marca()
    if marca != Estado.marca:
        if not ARQ_RISCO.exists():
            raise HTTPException(503, "Modelo ainda não treinado: rode applications/ml/src/treinar.py")
        Estado.risco = pd.read_csv(ARQ_RISCO).set_index("bairro")
        Estado.meta = json.loads(ARQ_META.read_text(encoding="utf-8")) if ARQ_META.exists() else {}
        Estado.config = json.loads(ARQ_CONFIG.read_text(encoding="utf-8")) if ARQ_CONFIG.exists() else {}
        Estado.modelo = joblib.load(ARQ_MODELO) if ARQ_MODELO.exists() else None
        Estado.marca = marca
    return Estado


def resposta_bairro(estado: Estado, bairro: str, criterio: str) -> dict:
    nome = normalizar_bairro(bairro)
    if nome not in estado.risco.index:
        raise HTTPException(404, f"Bairro '{bairro}' não encontrado (normalizado: '{nome}'). Veja GET /riscos.")
    linha = estado.risco.loc[nome]
    return {
        "bairro": nome,
        "criterio": criterio,
        "risco": float(linha[f"risco_{criterio}"]),
        "classe": str(linha[f"classe_{criterio}"]),
        "previsao_chamados": float(linha["previsao_chamados"]),
        "previsao_por_1000_postes": float(linha["previsao_por_1000_postes"]),
        "mes_previsto": str(linha["mes_previsto"]),
        "modelo": estado.meta.get("modelo"),
    }


def criterio_padrao(estado: Estado, criterio: str | None) -> str:
    criterio = criterio or estado.config.get("criterio_risco", "contagem")
    if criterio not in ("contagem", "taxa"):
        raise HTTPException(400, "criterio deve ser 'contagem' ou 'taxa'")
    return criterio


@app.get("/saude")
def saude():
    estado = carregar()
    return {
        "status": "ok",
        "modelo": estado.meta.get("modelo"),
        "treinado_em": estado.meta.get("treinado_em"),
        "mes_previsto": estado.meta.get("mes_previsto"),
        "bairros": int(len(estado.risco)),
        "modelo_carregado": estado.modelo is not None,
    }


@app.get("/risco/{bairro}")
def risco_bairro(bairro: str, criterio: str | None = Query(None, description="contagem ou taxa")):
    estado = carregar()
    return resposta_bairro(estado, bairro, criterio_padrao(estado, criterio))


@app.get("/riscos")
def riscos(criterio: str | None = Query(None), limite: int = Query(100, ge=1, le=200)):
    estado = carregar()
    criterio = criterio_padrao(estado, criterio)
    ordenado = estado.risco.sort_values(f"risco_{criterio}", ascending=False).head(limite)
    return [resposta_bairro(estado, nome, criterio) for nome in ordenado.index]


@app.get("/poste/{poste_id}")
def poste(poste_id: str):
    estado = carregar()
    postes = estado.config.get("postes", {})
    if poste_id not in postes:
        raise HTTPException(404, f"Poste '{poste_id}' não está no config.json")
    dados = resposta_bairro(estado, postes[poste_id]["bairro"], criterio_padrao(estado, None))
    potencias = estado.config.get("potencia_por_classe", {"alto": 90, "medio": 80, "baixo": 70})
    return {"poste": poste_id, **dados, "potencia_sugerida": int(potencias[dados["classe"]]),
            "id_ponto": postes[poste_id].get("id_ponto"),
            "vinculo_cadastro": postes[poste_id].get("vinculo_cadastro")}


class Features(BaseModel):
    chamados_lampada_apagada: float = Field(..., ge=0, description="chamados do bairro no mês atual")
    chamados_lag1: float = Field(..., ge=0)
    chamados_lag2: float = Field(..., ge=0)
    chamados_lag3: float = Field(..., ge=0)
    media_movel_3m: float = Field(..., ge=0)
    total_postes: float = Field(..., gt=0)
    postes_sem_id: float = Field(0, ge=0)
    potencia_media_w: float = Field(..., gt=0)
    pct_led: float = Field(..., ge=0, le=100)
    rpa: float = Field(..., ge=1, le=6)
    mes_do_ano: int = Field(..., ge=1, le=12)


@app.post("/prever")
def prever(features: Features):
    estado = carregar()
    if estado.modelo is None:
        raise HTTPException(503, "modelo_risco.joblib não encontrado: rode o treinar.py")
    linha = features.model_dump()
    linha["taxa_1000_postes"] = linha["chamados_lampada_apagada"] / linha["total_postes"] * 1000
    colunas = estado.meta.get("features") or list(linha)
    previsto = float(estado.modelo.predict(pd.DataFrame([linha])[colunas])[0])
    return {"previsao_chamados_mes_seguinte": round(max(previsto, 0.0), 1), "modelo": estado.meta.get("modelo")}


# =============================================================
#  Rota do pedestre na cascata em Y (modelo do prever_rota.py)
# =============================================================
ARQ_MODELO_ROTA = MODELOS / "modelo_rota.joblib"
ARQ_META_ROTA = MODELOS / "metadados_rota.json"
DB_PATH = Path(os.getenv("DB_PATH", RAIZ.parent / "backend" / "dados" / "central.db"))


class EstadoRota:
    marca = None
    modelo = None
    meta = {}


def carregar_rota() -> EstadoRota:
    if not ARQ_MODELO_ROTA.exists():
        raise HTTPException(503, "Modelo de rota ainda não treinado: rode prever_rota.py treinar")
    marca = (ARQ_MODELO_ROTA.stat().st_mtime, ARQ_META_ROTA.stat().st_mtime if ARQ_META_ROTA.exists() else 0)
    if marca != EstadoRota.marca:
        EstadoRota.modelo = joblib.load(ARQ_MODELO_ROTA)
        EstadoRota.meta = json.loads(ARQ_META_ROTA.read_text(encoding="utf-8")) if ARQ_META_ROTA.exists() else {}
        EstadoRota.marca = marca
    return EstadoRota


@app.get("/rota")
def rota(dist_s1: float = Query(..., gt=0, le=400, description="distância medida pelo S1 na entrada, em cm"),
         hora: float | None = Query(None, ge=0, lt=24, description="hora do dia (padrão: agora)")):
    """Para onde vai o pedestre que passou pelo S1 a esta distância: esquerda ou direita."""
    estado = carregar_rota()
    if hora is None:
        agora = datetime.now()
        hora = agora.hour + agora.minute / 60
    entrada = pd.DataFrame([{"dist_s1": dist_s1, "hora_sin": math.sin(2 * math.pi * hora / 24),
                             "hora_cos": math.cos(2 * math.pi * hora / 24)}])
    colunas = estado.meta.get("features") or list(entrada)
    proba = estado.modelo.predict_proba(entrada[colunas])[0]
    classes = [str(c) for c in estado.modelo.classes_]
    i = int(proba.argmax())
    return {"direcao_provavel": classes[i], "confianca": round(float(proba[i]), 3),
            "probabilidades": {c: round(float(p), 3) for c, p in zip(classes, proba)},
            "modelo": estado.meta.get("modelo")}


@app.get("/rota/metricas")
def rota_metricas():
    """Como o modelo de rota foi treinado e quanto ele acerta ao vivo (travessias com fonte "modelo")."""
    estado = carregar_rota()
    resposta = {k: estado.meta.get(k) for k in ("modelo", "treinado_em", "linhas", "origens", "metricas")}
    if DB_PATH.exists():
        try:
            with sqlite3.connect(DB_PATH) as db:
                linhas = db.execute("SELECT acertou FROM travessia WHERE fonte = 'modelo' AND acertou >= 0").fetchall()
            resposta["ao_vivo"] = {"previsoes": len(linhas), "acertos": sum(a for (a,) in linhas),
                                   "acuracia": round(sum(a for (a,) in linhas) / len(linhas), 3) if linhas else None}
        except sqlite3.Error:
            resposta["ao_vivo"] = None
    return resposta


# =============================================================
#  Anomalias na telemetria ao vivo (anomalia_telemetria.py)
# =============================================================
ARQ_META_ANOMALIA = MODELOS / "metadados_anomalia.json"


@app.get("/anomalias")
def anomalias(poste_id: str | None = Query(None, description="só este poste (ex.: P06)")):
    """O que o detector de anomalias disse por último sobre cada poste, mais o resumo do treino.
    Os resultados vêm da tabela "anomalia" que o coletor grava a partir do MQTT."""
    meta = json.loads(ARQ_META_ANOMALIA.read_text(encoding="utf-8")) if ARQ_META_ANOMALIA.exists() else {}
    escolhido = meta.get("modelo")
    resposta = {
        "modelo": escolhido, "treinado_em": meta.get("treinado_em"), "linhas_treino": meta.get("linhas"),
        "metricas_teste": {k: v for k, v in meta.get("metricas", {}).get(escolhido, {}).items() if k.startswith("teste")},
        "postes": {},
    }
    if not DB_PATH.exists():
        return resposta
    try:
        with sqlite3.connect(DB_PATH) as db:
            linhas = db.execute(
                "SELECT a.id, a.recebido_em, a.payload FROM anomalia a "
                "JOIN (SELECT id, MAX(rowid) AS r FROM anomalia GROUP BY id) u ON a.rowid = u.r "
                + ("WHERE a.id = ? " if poste_id else "") + "ORDER BY a.id",
                (poste_id,) if poste_id else ()).fetchall()
            contagem = dict(db.execute(
                "SELECT id, COUNT(*) FROM anomalia WHERE json_extract(payload, '$.anomalias') > 0 GROUP BY id"
            ).fetchall())
    except sqlite3.Error:   # banco antigo, sem a tabela anomalia
        return resposta
    for pid, recebido_em, payload in linhas:
        try:
            dados = json.loads(payload)
        except ValueError:
            continue
        resposta["postes"][pid] = {**dados, "recebido_em": recebido_em, "ciclos_com_anomalia": contagem.get(pid, 0)}
    if poste_id and poste_id not in resposta["postes"]:
        raise HTTPException(404, f"Nenhuma análise de anomalia para o poste '{poste_id}' ainda")
    return resposta


# =============================================================
#  Parque de luminárias: falha em 14 dias, CPTED e dimerização
# =============================================================
ARQ_META_FALHA = MODELOS / "metadados_falha.json"


def _registros(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", force_ascii=False))


def _parque():
    """Funções do banco do parque, importadas só quando uma rota do parque é chamada."""
    try:
        import banco_parque
        return banco_parque
    except ImportError as erro:   # dependência do banco faltando no ambiente
        raise HTTPException(503, f"Banco do parque indisponível: {erro}")


def _data_ref(tabela: str) -> str:
    bp = _parque()
    df = bp.ler(f"SELECT MAX(data_ref) AS d FROM {tabela}")
    if df.empty or df["d"].iloc[0] is None:
        raise HTTPException(503, "O pipeline do parque ainda não rodou (serviço 'pipeline' ou DAG g17_falha_14d)")
    return str(df["d"].iloc[0])


@app.get("/luminarias")
def luminarias(bairro: str | None = Query(None), nivel_cpted: str | None = Query(None, description="alta, media ou baixa")):
    bp = _parque()
    data_ref = _data_ref("prioridade")
    df = bp.ler("SELECT p.*, l.bairro, l.lat, l.lon, l.potencia_w, l.classe_via FROM prioridade p "
                "JOIN luminaria l ON l.id_luminaria = p.id_luminaria WHERE p.data_ref = :d ORDER BY p.posicao", d=data_ref)
    if bairro:
        df = df[df["bairro"] == normalizar_bairro(bairro)]
    if nivel_cpted:
        df = df[df["nivel_cpted"] == nivel_cpted]
    return {"data_ref": data_ref, "total": len(df), "luminarias": _registros(df)}


@app.get("/luminarias/{id_luminaria}")
def luminaria(id_luminaria: str, dias: int = Query(60, ge=1, le=900)):
    bp = _parque()
    cad = bp.ler("SELECT * FROM luminaria WHERE id_luminaria = :i", i=id_luminaria)
    if cad.empty:
        raise HTTPException(404, f"Luminária '{id_luminaria}' não existe")
    tel = bp.ler("SELECT * FROM telemetria_luminaria WHERE id_luminaria = :i ORDER BY data DESC LIMIT :n",
                 i=id_luminaria, n=dias)
    prev = bp.ler("SELECT data_ref, prob_falha_14d, acima_limiar FROM previsao_falha WHERE id_luminaria = :i "
                  "ORDER BY data_ref DESC LIMIT 60", i=id_luminaria)
    return {"cadastro": _registros(cad)[0], "telemetria": _registros(tel.sort_values("data")),
            "previsoes": _registros(prev.sort_values("data_ref"))}


@app.get("/previsoes")
def previsoes(limite: int = Query(20, ge=1, le=500)):
    bp = _parque()
    data_ref = _data_ref("previsao_falha")
    df = bp.ler("SELECT f.*, l.bairro FROM previsao_falha f JOIN luminaria l ON l.id_luminaria = f.id_luminaria "
                "WHERE f.data_ref = :d AND f.prob_falha_14d IS NOT NULL ORDER BY f.prob_falha_14d DESC LIMIT :n",
                d=data_ref, n=limite)
    return {"data_ref": data_ref, "previsoes": _registros(df)}


@app.get("/prioridades")
def prioridades(limite: int = Query(20, ge=1, le=500)):
    bp = _parque()
    data_ref = _data_ref("prioridade")
    df = bp.ler("SELECT p.*, l.bairro FROM prioridade p JOIN luminaria l ON l.id_luminaria = p.id_luminaria "
                "WHERE p.data_ref = :d ORDER BY p.posicao LIMIT :n", d=data_ref, n=limite)
    return {"data_ref": data_ref, "alfa": 0.5, "prioridades": _registros(df)}


@app.get("/alertas")
def alertas(limite: int = Query(50, ge=1, le=1000), tipo: str | None = Query(None)):
    bp = _parque()
    data_ref = _data_ref("alerta_luminaria")
    df = bp.ler("SELECT * FROM alerta_luminaria WHERE data_ref = :d", d=data_ref)
    if tipo:
        df = df[df["tipo"] == tipo]
    return {"data_ref": data_ref, "contagem": df["tipo"].value_counts().to_dict(), "alertas": _registros(df.head(limite))}


@app.get("/falha/metricas")
def falha_metricas():
    if not ARQ_META_FALHA.exists():
        raise HTTPException(503, "Modelo de falha ainda não treinado: rode ml/src/treinar_falha.py")
    meta = json.loads(ARQ_META_FALHA.read_text(encoding="utf-8"))
    return {k: meta.get(k) for k in ("modelo", "calibracao", "treinado_em", "origem_dados", "janela_dias", "limiar_f1",
                                     "capacidade_k", "vence_baselines", "melhor_baseline", "periodos", "metricas",
                                     "robustez", "importancia_features", "limpeza")}


@app.get("/cpted")
def cpted_info():
    import cpted as C
    bp = _parque()
    resposta = {**C.pesos_ahp(), "alfa": C.ALFA, "limites_nivel": C.LIMITES,
                "justificativas": {f"{a} x {b}": t for (a, b), t in C.JUSTIFICATIVAS.items()}}
    try:
        data_ref = _data_ref("previsao_falha")
    except HTTPException:
        return resposta
    prev = bp.ler("SELECT id_luminaria, prob_falha_14d FROM previsao_falha WHERE data_ref = :d", d=data_ref)
    estado = bp.ler("SELECT id_luminaria, estado FROM prioridade WHERE data_ref = :d", d=data_ref)
    resposta["sensibilidade"] = C.sensibilidade(prev.merge(estado, on="id_luminaria"), bp.ler("SELECT * FROM luminaria"))
    resposta["data_ref"] = data_ref
    return resposta


@app.get("/dimerizacao")
def dimerizacao_info():
    bp = _parque()
    execucao = bp.ler("SELECT executado_em, detalhes FROM pipeline_execucao WHERE etapa = 'dimerizar' "
                      "ORDER BY executado_em DESC LIMIT 1")
    if execucao.empty:
        raise HTTPException(503, "O pipeline ainda não planejou a dimerização")
    por_hora = bp.ler("SELECT hora, AVG(pct_final) AS pct_medio, MIN(pct_final) AS pct_min, SUM(viola) AS violacoes "
                      "FROM plano_dimerizacao GROUP BY hora")
    ordem = {h: i for i, h in enumerate([18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5])}
    por_hora = por_hora.assign(o=por_hora["hora"].map(ordem)).sort_values("o").drop(columns="o")
    return {"executado_em": execucao["executado_em"].iloc[0], **json.loads(execucao["detalhes"].iloc[0]),
            "por_hora": _registros(por_hora.round(1))}


@app.get("/pipeline")
def pipeline_info(limite: int = Query(20, ge=1, le=200)):
    bp = _parque()
    df = bp.ler("SELECT * FROM pipeline_execucao ORDER BY executado_em DESC LIMIT :n", n=limite)
    df["detalhes"] = df["detalhes"].map(lambda t: json.loads(t) if t else None)
    return _registros(df)


@app.get("/zonas")
def zonas_historicas():
    """K-Means descritivo dos bairros; independente do parque simulado e de comandos."""
    from zonas_prioritarias import carregar
    try:
        bairros, metadados = carregar()
    except (OSError, ValueError, KeyError) as erro:
        raise HTTPException(503, "Zonas históricas indisponíveis. Rode ml/src/zonas_prioritarias.py. " + str(erro)) from erro
    return {"metadados": metadados, "bairros": _registros(bairros)}
