"""Seleciona uma referência demonstrativa verificável no cadastro de postes de 2025.

O CSV bruto fica fora do Git. O recorte pequeno documenta a origem do id_ponto
sem afirmar que o ESP32 esteja instalado na luminária cadastrada.
"""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from preparar_dados import normalizar_bairro

RAIZ = Path(__file__).resolve().parents[1]
CSV = RAIZ / "data/raw/postes/iluminacao-publica-do-recife-2025.csv"
EVIDENCIA = RAIZ / "data/processed/referencia_p01.json"
RECURSO_ID = "76cb7e65-1362-4ea7-ac04-453d67e41c64"
PAGINA = f"https://dados.recife.pe.gov.br/dataset/postes-iluminacao-publica-do-recife/resource/{RECURSO_ID}"
URL_CSV = ("https://dados.recife.pe.gov.br/dataset/cb834849-e07e-43a1-a101-204b599aaebb/"
           f"resource/{RECURSO_ID}/download/iluminacao-publica-do-recife-2025.csv")


def selecionar(cadastro: pd.DataFrame, bairro: str = "BOA VIAGEM") -> dict:
    if not {"id_ponto", "bairro"} <= set(cadastro):
        raise ValueError("O cadastro deve conter id_ponto e bairro.")
    nome = normalizar_bairro(bairro)
    if not nome:
        raise ValueError("Informe um bairro válido.")
    ids = cadastro["id_ponto"].fillna("").astype(str).str.strip()
    pertence = cadastro["bairro"].map(normalizar_bairro).eq(nome)
    # Rejeitar IDs ausentes, não numéricos, zero e repetidos em qualquer bairro.
    valido = ids.str.fullmatch(r"[0-9]+") & ids.ne("")
    positivo = ids.where(valido, "0").map(int).gt(0)
    unico = ~ids.duplicated(keep=False)
    candidatos = cadastro[pertence & valido & positivo & unico].copy()
    if candidatos.empty:
        raise ValueError(f"Nenhum id_ponto positivo e único encontrado para {nome}.")
    candidatos["id_ponto"] = ids.loc[candidatos.index]
    candidatos["ordem_id"] = candidatos["id_ponto"].map(int)
    linha = candidatos.sort_values("ordem_id", kind="stable").iloc[0]
    # Apenas atributos necessários ao vínculo; sem endereço ou coordenadas.
    registro = {"id_ponto": str(linha["id_ponto"]), "bairro": str(linha["bairro"]), "bairro_normalizado": nome}
    for campo in ("rpa", "tipo_lampa", "potencia"):
        registro[campo] = None if campo not in linha or pd.isna(linha[campo]) else str(linha[campo])
    return {"registro": registro, "linhas_bairro": int(pertence.sum()),
            "candidatos_unicos": len(candidatos),
            "criterio": "Menor id_ponto numérico positivo do bairro, com ocorrência única em todo o cadastro.",
            "vinculo_cadastro": "referencia_demonstrativa"}


def gerar(csv: Path = CSV, saida: Path = EVIDENCIA, bairro: str = "BOA VIAGEM") -> dict:
    cadastro = pd.read_csv(csv, sep=";", dtype=str)
    evidencia = selecionar(cadastro, bairro)
    evidencia["fonte"] = {"titulo": "Iluminação Pública do Recife - 2025", "orgao": "EMLURB",
                          "recurso_id": RECURSO_ID, "pagina": PAGINA, "url_csv": URL_CSV,
                          "licenca": "Open Data Commons Open Database License (ODbL)",
                          "sha256_csv": hashlib.sha256(csv.read_bytes()).hexdigest(), "linhas_csv": len(cadastro)}
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(evidencia, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return evidencia


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=CSV)
    parser.add_argument("--saida", type=Path, default=EVIDENCIA)
    parser.add_argument("--bairro", default="BOA VIAGEM")
    args = parser.parse_args()
    evidencia = gerar(args.csv, args.saida, args.bairro)
    print(json.dumps(evidencia, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
