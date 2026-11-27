"""
Pipeline do parque de luminárias (proposta, itens 02, 03, 07 e 08): é o que o DAG do Airflow
g17_falha_14d roda, etapa por etapa, e o que o serviço "pipeline" do docker compose roda em laço.

    validar    lê a telemetria recente do banco, limpa (duplicatas, leituras impossíveis, lacunas)
               e registra o relatório em pipeline_execucao
    prever     calcula os atributos e a P(falha em 14 dias) calibrada de cada luminária -> previsao_falha
    priorizar  junta risco de falha e score CPTED -> prioridade, e gera os alertas -> alerta_luminaria
    dimerizar  plano de potência por hora com os pisos CPTED e ABNT, teste de segurança (0% de
               violações) e economia -> plano_dimerizacao; manda o comando da hora aos postes P01..P10
    servir     roda as etapas sempre que chega um dia novo de telemetria; treina o modelo se não
               houver um, e de novo a cada PIPELINE_RETREINO_DIAS dias novos (padrão 180 = 90 min de demo)

Uso:
    python applications/ml/src/pipeline_parque.py validar|prever|priorizar|dimerizar|tudo|servir
    (variáveis: DATABASE_URL, MQTT_HOST, MQTT_PORT, PIPELINE_S, PIPELINE_RETREINO_DIAS, PIPELINE_COMANDOS)
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
APLICACOES = RAIZ.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(APLICACOES))
from banco_parque import contar, executar, gravar, ler  # noqa: E402
from cpted import pesos_ahp, priorizar as ranking_cpted, score_cpted, nivel  # noqa: E402
from dimerizacao import comando_poste, economia, plano, teste_seguranca  # noqa: E402
from parque_features import FEATURES, construir_features, limpar_telemetria, linhas_para_modelo  # noqa: E402

MODELO = RAIZ / "models" / "modelo_falha.joblib"
METADADOS = RAIZ / "models" / "metadados_falha.json"
CONFIG = RAIZ / "config.json"
DIAS_JANELA = 100     # o atributo mais longo olha 90 dias para trás


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def registrar(etapa: str, lidas: int, validas: int, rejeitadas: int, detalhes: dict) -> None:
    gravar(pd.DataFrame([{"executado_em": agora(), "etapa": etapa, "linhas_lidas": lidas, "linhas_validas": validas,
                          "rejeitadas": rejeitadas, "detalhes": json.dumps(detalhes, ensure_ascii=False, default=str)}]),
           "pipeline_execucao")


def data_mais_recente() -> str | None:
    df = ler("SELECT MAX(data) AS d FROM telemetria_luminaria")
    return None if df.empty or df["d"].iloc[0] is None else str(df["d"].iloc[0])[:10]


def telemetria_recente() -> pd.DataFrame:
    fim = data_mais_recente()
    if fim is None:
        return pd.DataFrame()
    inicio = (pd.Timestamp(fim) - pd.Timedelta(days=DIAS_JANELA)).date().isoformat()
    return ler("SELECT * FROM telemetria_luminaria WHERE data >= :inicio", inicio=inicio)


# ---------------- etapas ----------------
def validar() -> pd.DataFrame:
    bruto = telemetria_recente()
    if bruto.empty:
        raise SystemExit("Sem telemetria no banco: rode simulador/parque.py gerar (ou suba o serviço parque).")
    limpo, rel = limpar_telemetria(bruto)
    registrar("validar", rel["lidas"], rel["validas"], rel["descartadas"], rel)
    print(f"[validar] {rel['lidas']} leituras, {rel['validas']} válidas, {rel['preenchidas']} lacunas preenchidas, "
          f"{rel['descartadas']} descartadas; inválidas por coluna: "
          f"{ {k: v for k, v in rel['leituras_invalidas'].items() if v} }")
    return limpo


def prever(limpo: pd.DataFrame | None = None) -> pd.DataFrame:
    if not MODELO.exists():
        raise SystemExit("Sem modelo de falha: rode ml/src/treinar_falha.py")
    modelo, meta = joblib.load(MODELO), json.loads(METADADOS.read_text(encoding="utf-8"))
    limpo = validar() if limpo is None else limpo
    catalogo = ler("SELECT * FROM luminaria")
    df = construir_features(limpo, catalogo)
    ultimo = df.sort_values("data").groupby("id_luminaria").tail(1).copy()
    data_ref = df["data"].max()
    ultimo = ultimo[ultimo["data"] >= data_ref - pd.Timedelta(days=2)]       # quem parou de mandar fica de fora
    pode = linhas_para_modelo(ultimo)
    ultimo["prob_falha_14d"] = float("nan")
    if pode.any():
        ultimo.loc[pode, "prob_falha_14d"] = modelo.predict_proba(ultimo.loc[pode, FEATURES])[:, 1]
    limiar = meta.get("limiar_f1", 0.5)
    previsao = pd.DataFrame({
        "data_ref": data_ref.date().isoformat(), "id_luminaria": ultimo["id_luminaria"],
        "prob_falha_14d": ultimo["prob_falha_14d"].round(5),
        "acima_limiar": (ultimo["prob_falha_14d"] >= limiar).astype(int), "modelo": meta.get("modelo"),
        "gerado_em": agora(),
    })
    executar("DELETE FROM previsao_falha WHERE data_ref = :d", d=previsao["data_ref"].iloc[0])
    gravar(previsao, "previsao_falha")
    registrar("prever", len(ultimo), int(pode.sum()), int((~pode).sum()),
              {"data_ref": previsao["data_ref"].iloc[0], "acima_limiar": int(previsao["acima_limiar"].sum()),
               "limiar": limiar})
    print(f"[prever] {previsao['data_ref'].iloc[0]}: {int(pode.sum())} luminárias pontuadas, "
          f"{int(previsao['acima_limiar'].sum())} acima do limiar {limiar:.3f}")
    return previsao.merge(ultimo[["id_luminaria", "estado"]], on="id_luminaria")


def priorizar(previsao: pd.DataFrame | None = None) -> pd.DataFrame:
    if previsao is None:
        previsao = prever()
    catalogo = ler("SELECT * FROM luminaria")
    data_ref = previsao["data_ref"].iloc[0]
    ranking = ranking_cpted(previsao[["id_luminaria", "prob_falha_14d", "estado"]], catalogo)
    saida = ranking[["id_luminaria", "prob_falha_14d", "risco_relativo", "score_cpted", "nivel_cpted", "prioridade",
                     "posicao", "estado"]].assign(data_ref=data_ref, gerado_em=agora())
    executar("DELETE FROM prioridade WHERE data_ref = :d", d=data_ref)
    gravar(saida, "prioridade")

    acima = previsao.set_index("id_luminaria")["acima_limiar"]
    alertas = []
    for _, l in ranking.iterrows():
        nome = f"{l['id_luminaria']} ({l['bairro']})"
        if l["estado"] == "APAGADA":
            alertas.append((l["id_luminaria"], "apagada", f"{nome} apagada: reparo corretivo, prioridade #{l['posicao']}"))
        elif l["estado"] == "CINTILANDO":
            alertas.append((l["id_luminaria"], "cintilando", f"{nome} cintilando: sinal de falha próxima"))
        if pd.notna(l["prob_falha_14d"]) and acima.get(l["id_luminaria"], 0):
            alertas.append((l["id_luminaria"], "risco_alto",
                            f"{nome} com {l['prob_falha_14d']:.0%} de chance de falhar em 14 dias: inspecionar"))
    tabela = pd.DataFrame([{"gerado_em": agora(), "data_ref": data_ref, "id_luminaria": i, "tipo": t, "mensagem": m}
                           for i, t, m in alertas])
    executar("DELETE FROM alerta_luminaria WHERE data_ref = :d", d=data_ref)
    gravar(tabela, "alerta_luminaria")
    contagem = tabela["tipo"].value_counts().to_dict() if not tabela.empty else {}
    registrar("priorizar", len(ranking), len(ranking), 0, {"data_ref": data_ref, "alertas": contagem,
                                                            "ahp": pesos_ahp()})
    print(f"[priorizar] {data_ref}: top 3 = {', '.join(ranking.head(3)['id_luminaria'])}; alertas {contagem}")
    return saida


def potencia_media_recife() -> float | None:
    try:
        postes = pd.read_csv(RAIZ / "data" / "processed" / "postes_por_bairro.csv")
        return float((postes["potencia_media_w"] * postes["total_postes"]).sum() / postes["total_postes"].sum())
    except Exception:
        return None


def dimerizar(publicar: bool = False) -> dict:
    catalogo = ler("SELECT * FROM luminaria")
    data_ref = data_mais_recente()
    df = plano(catalogo)
    seguranca, eco = teste_seguranca(df), economia(df, potencia_media_recife())
    colunas = ["id_luminaria", "hora", "demanda", "pct_desejado", "piso_cpted", "piso_abnt", "pct_final",
               "e_estimada_lx", "e_min_lx", "viola"]
    gravar(df[colunas].assign(data_ref=data_ref), "plano_dimerizacao", substituir=True)
    registrar("dimerizar", len(df), len(df) - seguranca["violacoes"], seguranca["violacoes"],
              {"seguranca": seguranca, "economia": eco})
    print(f"[dimerizar] {seguranca['comandos']} comandos, {seguranca['violacoes']} violações "
          f"({'APROVADO' if seguranca['aprovado'] else 'REPROVADO'}); economia {eco['economia_pct']}%")
    if publicar:
        publicar_comandos_postes(catalogo)
    return {"seguranca": seguranca, "economia": eco}


_cliente_mqtt = None
_ultimo_comando: dict[str, int] = {}


def publicar_comandos_postes(catalogo: pd.DataFrame) -> None:
    """Comando da hora para P01..P10: nível CPTED e fluxo médios das luminárias do bairro do poste.
    Só manda quando o valor muda (na prática, na troca de hora), para um comando manual dado pelo
    dashboard da maquete durante a demo não ser sobrescrito a cada minuto."""
    global _cliente_mqtt
    from comum import MQTT_HOST, MQTT_PORT, novo_cliente, topico
    if _cliente_mqtt is None:
        _cliente_mqtt = novo_cliente("dimerizacao")
        _cliente_mqtt.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        _cliente_mqtt.loop_start()
        time.sleep(1)
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    cat = catalogo.assign(score=score_cpted(catalogo))
    por_bairro = cat.groupby("bairro").agg(score=("score", "mean"), fluxo=("fluxo_pedestres", "mean"))
    hora = datetime.now().hour
    enviados = {}
    for poste_id, info in config.get("postes", {}).items():
        if info["bairro"] not in por_bairro.index:
            continue
        linha = por_bairro.loc[info["bairro"]]
        nivel_poste = nivel(pd.Series([linha["score"]])).iloc[0]
        pct = comando_poste(nivel_poste, float(linha["fluxo"]), hora)
        if _ultimo_comando.get(poste_id) == pct:
            continue
        _cliente_mqtt.publish(topico(poste_id, "comando"), json.dumps({"potencia": pct}), qos=1)
        _ultimo_comando[poste_id] = pct
        enviados[poste_id] = f"{pct}% ({nivel_poste})"
    if enviados:
        print(f"[dimerizar] {hora}h, comandos aos postes: {enviados}", flush=True)


def tudo(publicar: bool = False) -> None:
    limpo = validar()
    priorizar(prever(limpo))
    dimerizar(publicar)


def servir() -> None:
    intervalo = float(os.getenv("PIPELINE_S", "60"))
    retreino = int(os.getenv("PIPELINE_RETREINO_DIAS", "180"))
    publicar = os.getenv("PIPELINE_COMANDOS", "1") == "1"
    print(f"[pipeline] verificando dias novos a cada {intervalo:.0f} s", flush=True)
    while contar("telemetria_luminaria") == 0:
        print("[pipeline] esperando o histórico do parque no banco...", flush=True)
        time.sleep(15)
    ultimo_processado, dia_do_treino, treinando = None, None, threading.Lock()

    def treinar_agora() -> None:
        nonlocal dia_do_treino
        if not treinando.acquire(blocking=False):
            return
        try:
            from treinar_falha import treinar
            print("[pipeline] treinando o modelo de falha em 14 dias...", flush=True)
            # retreino automático mais leve (8 tentativas do Optuna por modelo) para não pesar na demo;
            # o treino completo (20 tentativas) é o do DAG semanal ou o manual
            treinar(n_trials=int(os.getenv("PIPELINE_RETREINO_TRIALS", "8")))
            dia_do_treino = data_mais_recente()
        except Exception as erro:
            print(f"[pipeline] treino falhou: {erro}", flush=True)
        finally:
            treinando.release()

    if not MODELO.exists():
        treinar_agora()
    else:
        dia_do_treino = json.loads(METADADOS.read_text(encoding="utf-8")).get("periodos", {}).get("teste", [None, None])[1]
    while True:
        try:
            data = data_mais_recente()
            if data and data != ultimo_processado and MODELO.exists():
                tudo(publicar)
                ultimo_processado = data
            elif publicar and MODELO.exists():
                publicar_comandos_postes(ler("SELECT * FROM luminaria"))
            if data and dia_do_treino and (pd.Timestamp(data) - pd.Timestamp(dia_do_treino)).days >= retreino:
                threading.Thread(target=treinar_agora, daemon=True).start()
                dia_do_treino = data           # não dispara de novo enquanto treina
        except SystemExit as aviso:
            print(f"[pipeline] {aviso}", flush=True)
        except Exception as erro:
            print(f"[pipeline] erro: {erro}", flush=True)
        sys.stdout.flush()
        time.sleep(intervalo)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline do parque de luminárias")
    parser.add_argument("etapa", choices=["validar", "prever", "priorizar", "dimerizar", "tudo", "servir"])
    parser.add_argument("--publicar", action="store_true", help="manda o comando da hora aos postes P01..P10")
    args = parser.parse_args()
    if args.etapa == "validar":
        validar()
    elif args.etapa == "prever":
        prever()
    elif args.etapa == "priorizar":
        priorizar()
    elif args.etapa == "dimerizar":
        dimerizar(args.publicar)
    elif args.etapa == "tudo":
        tudo(args.publicar)
    else:
        servir()


if __name__ == "__main__":
    main()
