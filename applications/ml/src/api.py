"""
API de inferência do risco por bairro (FastAPI).

Rotas:
    GET  /saude                 status da API e do modelo carregado (usado pelo docker compose)
    GET  /risco/{bairro}        risco previsto do bairro (aceita acento e minúsculas)
    GET  /riscos                ranking de todos os bairros (?criterio=contagem|taxa&limite=N)
    GET  /poste/{poste_id}      bairro do poste (config.json), risco e potência sugerida
    POST /prever                previsão do modelo para features enviadas no corpo (JSON)

Lê o que o treinar.py gera em applications/ml/models/ (risco_por_bairro.csv, metadados.json,
modelo_risco.joblib) e recarrega sozinha quando esses arquivos mudam (novo treino).

Uso:
    uvicorn api:app --app-dir applications/ml/src --port 8000
    Documentação interativa em http://localhost:8000/docs
"""

import json
import sys
from pathlib import Path

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from preparar_dados import normalizar_bairro  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
MODELOS = RAIZ / "models"
ARQ_RISCO = MODELOS / "risco_por_bairro.csv"
ARQ_META = MODELOS / "metadados.json"
ARQ_MODELO = MODELOS / "modelo_risco.joblib"
ARQ_CONFIG = RAIZ / "config.json"

app = FastAPI(title="G17 - Risco de lâmpada apagada por bairro", version="1.0")


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
    return {"poste": poste_id, **dados, "potencia_sugerida": int(potencias[dados["classe"]])}


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
