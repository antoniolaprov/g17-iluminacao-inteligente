"""
Dimerização adaptativa com piso de segurança (proposta, seções g.1 e g.6; item 08 do backlog).

Para cada luminária e hora da noite:
    potência desejada = 40% + 60% x demanda da via naquela hora (horário x fluxo de pedestres do trecho)
    potência final    = máximo(desejada; piso CPTED; piso ABNT)
    sem comunicação (ou comando inválido) = 100% (fail-safe)

Pisos (vale sempre o mais restritivo, g.6):
    CPTED (relativo à potência nominal): alta = 100% no período noturno de maior uso (18h às 22h) e
        no mínimo 80% no resto; média >= 70%; baixa >= 50%; trecho sem dados = alta.
    ABNT NBR 5101:2024 (absoluto): iluminância média >= mínimo da classe P da via
        (P1 20 lx, P2 15, P3 10, P4 7,5, P5 5, P6 3). Sem luxímetro, a iluminância é estimada
        de forma linear a partir da potência: E = E_projeto x potência / 100 (aproximação da g.6).
        Daí o piso ABNT de cada luminária = 100 x E_min / E_projeto.

Teste automático de segurança (g.6): para todos os comandos gerados, nenhuma luminária pode ficar
abaixo do limite aplicável; critério de aceite = 0% de violações. A economia de energia em relação
à operação sem dimerização é sempre apresentada junto com esse resultado.

Os postes da maquete e do simulador (P01..P10) também recebem o comando da hora, pelo MQTT
(g17/poste/<ID>/comando). O firmware só deixa um comando subir acima de 70%, então os pisos de
prioridade alta (80% e 100%) são aplicados, e o de prioridade baixa (50%) fica coberto pelo piso
de 70% do firmware, que é mais restritivo.
"""

import math

import numpy as np
import pandas as pd

from cpted import nivel, score_cpted

PISOS_CPTED = {"alta": 80, "media": 70, "baixa": 50}
HORAS_PICO = {18, 19, 20, 21}                  # período noturno de maior uso: 18h às 22h
HORAS_NOITE = [18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5]
# Fração da circulação máxima de pedestres em cada hora da noite (perfil típico de via urbana:
# pico na volta para casa, quase nada de madrugada, retomada às 5h). Premissa documentada.
DEMANDA_HORA = {18: 0.90, 19: 1.00, 20: 0.90, 21: 0.70, 22: 0.50, 23: 0.35,
                0: 0.25, 1: 0.15, 2: 0.10, 3: 0.10, 4: 0.15, 5: 0.35}
PCT_MINIMO_DESEJADO = 40
ILUMINANCIA_MIN = {"P1": 20, "P2": 15, "P3": 10, "P4": 7.5, "P5": 5, "P6": 3}
POSTES_RECIFE = 111_665                         # cadastro de postes da Emlurb (2025)


def piso_cpted(nivel_cpted: str, hora: int) -> int:
    if nivel_cpted == "alta" and hora in HORAS_PICO:
        return 100
    return PISOS_CPTED.get(nivel_cpted, PISOS_CPTED["alta"])


def piso_abnt(e_projeto_lx: float, e_min_lx: float) -> int:
    return int(min(100, math.ceil(100 * e_min_lx / e_projeto_lx)))


def plano(catalogo: pd.DataFrame, comunicacao_ok: pd.Series | None = None) -> pd.DataFrame:
    """Potência de cada luminária em cada hora da noite. comunicacao_ok (por id_luminaria, opcional)
    simula a perda de comunicação: quem está sem comunicação vai a 100%."""
    cat = catalogo.copy()
    cat["nivel_cpted"] = nivel(score_cpted(cat))
    fluxo = cat["fluxo_pedestres"].fillna(1.0)               # sem dados: supõe circulação alta
    linhas = []
    for hora in HORAS_NOITE:
        demanda = np.clip(DEMANDA_HORA[hora] * (0.4 + 0.6 * fluxo), 0, 1)
        desejado = PCT_MINIMO_DESEJADO + (100 - PCT_MINIMO_DESEJADO) * demanda
        p_cpted = cat["nivel_cpted"].map(lambda n, h=hora: piso_cpted(n, h))
        e_min = cat["classe_via"].map(ILUMINANCIA_MIN)
        p_abnt = [piso_abnt(e, m) for e, m in zip(cat["e_projeto_lx"], e_min)]
        final = np.maximum.reduce([desejado.round(), p_cpted, p_abnt]).astype(float)
        if comunicacao_ok is not None:
            final = np.where(cat["id_luminaria"].map(comunicacao_ok).fillna(True), final, 100.0)
        linhas.append(pd.DataFrame({
            "id_luminaria": cat["id_luminaria"], "hora": hora, "demanda": demanda.round(3),
            "pct_desejado": desejado.round(1), "piso_cpted": p_cpted, "piso_abnt": p_abnt, "pct_final": final,
            "e_estimada_lx": (cat["e_projeto_lx"] * final / 100).round(2), "e_min_lx": e_min,
            "nivel_cpted": cat["nivel_cpted"], "potencia_w": cat["potencia_w"],
        }))
    df = pd.concat(linhas, ignore_index=True)
    df["viola"] = ((df["e_estimada_lx"] < df["e_min_lx"] - 1e-9) | (df["pct_final"] < df["piso_cpted"])).astype(int)
    return df


def teste_seguranca(plano_df: pd.DataFrame) -> dict:
    violacoes = int(plano_df["viola"].sum())
    return {"comandos": int(len(plano_df)), "violacoes": violacoes,
            "pct_violacoes": round(100 * violacoes / max(len(plano_df), 1), 4), "aprovado": violacoes == 0,
            "por_nivel": plano_df.groupby("nivel_cpted")["pct_final"].agg(["min", "mean"]).round(1).to_dict("index")}


def economia(plano_df: pd.DataFrame, potencia_media_recife_w: float | None = None) -> dict:
    """Energia por noite com o plano x tudo a 100% (potência do driver ~ proporcional ao comando)."""
    com = float((plano_df["potencia_w"] * plano_df["pct_final"] / 100).sum()) / 1000      # kWh por noite
    sem = float(plano_df["potencia_w"].sum()) / 1000
    fracao = 1 - com / sem
    resposta = {"kwh_noite_sem_dimerizacao": round(sem, 2), "kwh_noite_com_dimerizacao": round(com, 2),
                "economia_pct": round(100 * fracao, 2), "kwh_ano_economizados_parque": round((sem - com) * 365, 1)}
    if potencia_media_recife_w:
        total_recife = POSTES_RECIFE * potencia_media_recife_w * len(HORAS_NOITE) * 365 / 1e6   # MWh/ano
        resposta["recife_mwh_ano_sem"] = round(total_recife, 1)
        resposta["recife_mwh_ano_economizados"] = round(total_recife * fracao, 1)
        resposta["meta_prefeitura_pct"] = 35
    return resposta


def comando_poste(nivel_cpted: str, fluxo: float, hora: int) -> int:
    """Potência para um poste da maquete/simulador agora (sem classe ABNT: só demanda e piso CPTED)."""
    demanda = DEMANDA_HORA.get(hora, 0.0) * (0.4 + 0.6 * fluxo)
    desejado = PCT_MINIMO_DESEJADO + (100 - PCT_MINIMO_DESEJADO) * min(demanda, 1.0)
    return int(max(round(desejado), piso_cpted(nivel_cpted, hora)))
