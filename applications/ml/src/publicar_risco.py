"""
Publica no MQTT o risco previsto para cada poste do config.json e o comando de potência.

Para cada poste (P01 = maquete, P02+ = simulador):
- g17/poste/<ID>/risco   (retido) {"risco", "classe", "bairro", "previsao_chamados", ...}
- g17/poste/<ID>/comando {"potencia": 90 | 80 | 70}, conforme a classe do risco

O firmware aplica max(pedido, 70) à noite, então o comando só sobe o brilho acima do
piso de segurança; de dia a luz continua apagada e pedestre continua indo a 100%.

O risco vem da API (API_URL, padrão http://127.0.0.1:8000). Se a API estiver fora do ar,
lê direto o models/risco_por_bairro.csv, para a demonstração não depender de um serviço.

Uso:
    python applications/ml/src/publicar_risco.py              # risco + comando
    python applications/ml/src/publicar_risco.py --sem-comando  # só o risco
    (variáveis: MQTT_HOST, MQTT_PORT, API_URL)
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ.parent))           # applications/ (comum.py)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import MQTT_HOST, MQTT_PORT, novo_cliente, topico  # noqa: E402
from preparar_dados import normalizar_bairro  # noqa: E402

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
CONFIG = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
POTENCIAS = CONFIG.get("potencia_por_classe", {"alto": 90, "medio": 80, "baixo": 70})


def risco_pela_api(poste_id: str) -> dict:
    with urllib.request.urlopen(f"{API_URL}/poste/{poste_id}", timeout=5) as resposta:
        return json.load(resposta)


def risco_pelo_arquivo(poste_id: str) -> dict:
    criterio = CONFIG.get("criterio_risco", "contagem")
    tabela = pd.read_csv(RAIZ / "models" / "risco_por_bairro.csv").set_index("bairro")
    bairro = normalizar_bairro(CONFIG["postes"][poste_id]["bairro"])
    linha = tabela.loc[bairro]
    classe = str(linha[f"classe_{criterio}"])
    return {
        "poste": poste_id, "bairro": bairro, "criterio": criterio,
        "id_ponto": CONFIG["postes"][poste_id].get("id_ponto"),
        "vinculo_cadastro": CONFIG["postes"][poste_id].get("vinculo_cadastro"),
        "risco": float(linha[f"risco_{criterio}"]), "classe": classe,
        "previsao_chamados": float(linha["previsao_chamados"]),
        "mes_previsto": str(linha["mes_previsto"]), "potencia_sugerida": int(POTENCIAS[classe]),
    }


def payload_risco(dados: dict) -> dict:
    """Contrato de risco com identificação cadastral opcional; comandos seguem só com potência."""
    payload = {k: dados[k] for k in ("risco", "classe", "bairro", "criterio", "previsao_chamados", "mes_previsto")}
    payload.update(modelo=dados.get("modelo"), id_ponto=dados.get("id_ponto"),
                   vinculo_cadastro=dados.get("vinculo_cadastro"))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sem-comando", action="store_true", help="publica só o risco, sem mudar a potência")
    args = parser.parse_args()

    origem = "API"
    try:
        riscos = {poste_id: risco_pela_api(poste_id) for poste_id in CONFIG["postes"]}
    except (OSError, json.JSONDecodeError) as erro:
        origem = "arquivo"
        print(f"API em {API_URL} indisponível ({erro}); usando models/risco_por_bairro.csv")
        riscos = {poste_id: risco_pelo_arquivo(poste_id) for poste_id in CONFIG["postes"]}

    cliente = novo_cliente("publicar-risco")
    cliente.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    cliente.loop_start()
    envios = []
    for poste_id, dados in riscos.items():
        payload = payload_risco(dados)
        envios.append(cliente.publish(topico(poste_id, "risco"), json.dumps(payload, ensure_ascii=False), qos=1, retain=True))
        texto = f"{poste_id} {dados['bairro']:<14} risco {dados['risco']:.2f} ({dados['classe']})"
        if not args.sem_comando:
            envios.append(cliente.publish(topico(poste_id, "comando"),
                                          json.dumps({"potencia": dados["potencia_sugerida"]}), qos=1))
            texto += f" -> potência {dados['potencia_sugerida']}%"
        print(texto)
    for envio in envios:
        envio.wait_for_publish(timeout=5)
    cliente.loop_stop()
    cliente.disconnect()
    print(f"Publicado em {MQTT_HOST}:{MQTT_PORT} ({origem})")


if __name__ == "__main__":
    main()
