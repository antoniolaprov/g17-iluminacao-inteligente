"""T19: perfis históricos dos bairros por chamados e postes (K-Means).

Análise descritiva dos CSVs processados da Emlurb. Grupos não são regiões
geográficas contíguas, probabilidade de falha ou classificação de segurança.
Uso: python applications/ml/src/zonas_prioritarias.py
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

RAIZ = Path(__file__).resolve().parents[1]
PAINEL = RAIZ / "data/processed/risco_bairro_mes.csv"
POSTES = RAIZ / "data/processed/postes_por_bairro.csv"
SAIDA = RAIZ / "models"
FEATURES = ["chamados_media_mensal", "total_postes"]
SEMENTE = 17
N_INIT = 20


def preparar(painel: pd.DataFrame, postes: pd.DataFrame, meses: int = 12) -> tuple[pd.DataFrame, dict]:
    """Exige janela mensal completa para todos os bairros, sem imputar ausências como zero."""
    if isinstance(meses, bool) or not isinstance(meses, int) or meses < 1:
        raise ValueError("A janela deve ter um número inteiro positivo de meses.")
    exigidas = {"bairro_norm", "ano_mes", "chamados_lampada_apagada"}
    if not exigidas <= set(painel) or not {"bairro_norm", "total_postes"} <= set(postes):
        raise ValueError("Colunas de bairro, mês, chamados e postes são obrigatórias.")
    p = painel[list(sorted(exigidas))].copy()
    cat = postes[["bairro_norm", "total_postes"]].copy()
    if p.empty or cat.empty:
        raise ValueError("As bases de chamados e postes não podem estar vazias.")
    for base in (p, cat):
        if base["bairro_norm"].isna().any() or not base["bairro_norm"].map(lambda x: isinstance(x, str) and bool(x.strip())).all():
            raise ValueError("Bairro ausente ou vazio.")
    if cat["bairro_norm"].duplicated().any() or p.duplicated(["bairro_norm", "ano_mes"]).any():
        raise ValueError("Duplicatas no cadastro ou no par bairro/mês.")
    if not p["ano_mes"].astype(str).str.fullmatch(r"\d{4}-(0[1-9]|1[0-2])").all():
        raise ValueError("Mês inválido: use AAAA-MM.")
    p["periodo"] = pd.PeriodIndex(p["ano_mes"], freq="M")
    fim = p["periodo"].max()
    janela = pd.period_range(end=fim, periods=meses, freq="M")
    recente = p[p["periodo"].isin(janela)].copy()
    if set(recente["bairro_norm"]) != set(cat["bairro_norm"]):
        raise ValueError("Os bairros dos chamados e do cadastro não correspondem na janela.")
    if not recente.groupby("bairro_norm").size().eq(meses).all():
        raise ValueError("Janela incompleta por bairro; ausência de registro não equivale a zero chamado.")
    for base, coluna, positivo in ((recente, "chamados_lampada_apagada", False), (cat, "total_postes", True)):
        base[coluna] = pd.to_numeric(base[coluna], errors="coerce")
        valores = base[coluna].to_numpy(float)
        if not np.isfinite(valores).all() or (valores < 0).any() or (positivo and (valores == 0).any()):
            raise ValueError(f"Valores inválidos em {coluna}.")
        if not np.equal(valores, np.floor(valores)).all():
            raise ValueError(f"{coluna} deve conter contagens inteiras.")
    resumo = recente.groupby("bairro_norm")["chamados_lampada_apagada"].agg(
        chamados_total="sum", chamados_media_mensal="mean").reset_index()
    resumo = resumo.merge(cat, on="bairro_norm", validate="one_to_one").sort_values("bairro_norm").reset_index(drop=True)
    resumo["taxa_1000_postes"] = resumo["chamados_media_mensal"] / resumo["total_postes"] * 1000
    return resumo, {"inicio": str(janela[0]), "fim": str(fim), "meses": meses}


def agrupar(painel: pd.DataFrame, postes: pd.DataFrame, meses: int = 12, k: int | None = None) -> tuple[pd.DataFrame, dict]:
    bairros, periodo = preparar(painel, postes, meses)
    # log reduz assimetria; escala impede que a unidade "postes" domine a distância.
    scaler = StandardScaler()
    X = scaler.fit_transform(np.log1p(bairros[FEATURES]))
    distintos = len(np.unique(X, axis=0))
    limite = min(6, len(bairros) - 1, distintos)
    if limite < 2:
        raise ValueError("São necessários ao menos três bairros e dois perfis distintos.")
    if k is not None and (isinstance(k, bool) or not isinstance(k, int) or not 2 <= k <= limite):
        raise ValueError(f"k deve ser inteiro entre 2 e {limite}.")
    candidatos, ajustados = [], {}
    for n in range(2, limite + 1):
        modelo = KMeans(n_clusters=n, n_init=N_INIT, random_state=SEMENTE).fit(X)
        score = float(silhouette_score(X, modelo.labels_))
        candidatos.append({"k": n, "silhouette": score, "inercia": float(modelo.inertia_)})
        ajustados[n] = modelo
    escolhido = k if k is not None else max(candidatos, key=lambda c: (c["silhouette"], -c["k"]))["k"]
    modelo = ajustados[escolhido]
    bairros["rotulo"] = modelo.labels_
    # Rótulos canônicos por média de chamados decrescente, com desempate por postes.
    # Identificam este snapshot; não são uma identidade persistente entre novos treinos.
    ordem = bairros.groupby("rotulo")[FEATURES].mean().sort_values(FEATURES, ascending=False).index
    nomes = {int(rotulo): f"Z{i:02d}" for i, rotulo in enumerate(ordem, start=1)}
    bairros["zona"] = bairros["rotulo"].map(nomes)
    grupos = []
    centros = np.expm1(scaler.inverse_transform(modelo.cluster_centers_))
    for rotulo in ordem:
        grupo = bairros[bairros["rotulo"] == rotulo]
        grupos.append({"zona": nomes[int(rotulo)], "bairros": len(grupo),
                       "chamados_media_por_bairro": float(grupo["chamados_media_mensal"].mean()),
                       "postes_media_por_bairro": float(grupo["total_postes"].mean()),
                       "chamados_total": int(grupo["chamados_total"].sum()),
                       "postes_total": int(grupo["total_postes"].sum()),
                       "taxa_1000_postes": float(grupo["chamados_media_mensal"].sum() / grupo["total_postes"].sum() * 1000),
                       "centro_chamados": float(centros[rotulo, 0]), "centro_postes": float(centros[rotulo, 1])})
    aris = [float(adjusted_rand_score(modelo.labels_, KMeans(n_clusters=escolhido, n_init=N_INIT,
                random_state=semente).fit_predict(X))) for semente in (27, 37, 47, 57)]
    meta = {"algoritmo": "KMeans", "sklearn": sklearn.__version__, "semente": SEMENTE, "n_init": N_INIT,
            "features": FEATURES, "transformacao": "log1p + StandardScaler", "periodo": periodo,
            "bairros": len(bairros), "k": escolhido,
            "criterio_k": "manual" if k is not None else "maior silhouette entre k=2..6 (limitado pela amostra)",
            "silhouette": next(c["silhouette"] for c in candidatos if c["k"] == escolhido),
            "candidatos": candidatos, "estabilidade": {"sementes": [27, 37, 47, 57], "ari": aris, "ari_minimo": min(aris)},
            "grupos": grupos, "natureza": "Perfis descritivos de demanda histórica; não são regiões contíguas nem risco de falha.",
            "efeito_operacional": "Nenhum comando MQTT ou alteração de prioridade CPTED/dimerização."}
    return bairros.drop(columns="rotulo"), meta


def sha256(caminho: Path) -> str:
    # CSVs no Git podem usar CRLF no Windows e LF no Linux; conteúdo lógico é o mesmo.
    return hashlib.sha256(caminho.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def gerar(saida: Path = SAIDA, meses: int = 12, k: int | None = None) -> tuple[pd.DataFrame, dict]:
    bairros, meta = agrupar(pd.read_csv(PAINEL), pd.read_csv(POSTES), meses, k)
    meta["fontes"] = {"risco_bairro_mes.csv": sha256(PAINEL), "postes_por_bairro.csv": sha256(POSTES)}
    saida.mkdir(parents=True, exist_ok=True)
    csv = saida / "zonas_bairros.csv"
    temporario = csv.with_suffix(".csv.tmp")
    bairros.to_csv(temporario, index=False, float_format="%.8f", lineterminator="\n")
    meta["csv_sha256"] = sha256(temporario)
    temporario.replace(csv)
    arq_meta = saida / "metadados_zonas.json"
    temp_meta = arq_meta.with_suffix(".json.tmp")
    temp_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp_meta.replace(arq_meta)
    return bairros, meta


def carregar(saida: Path = SAIDA) -> tuple[pd.DataFrame, dict]:
    meta = json.loads((saida / "metadados_zonas.json").read_text(encoding="utf-8"))
    csv = saida / "zonas_bairros.csv"
    if sha256(csv) != meta["csv_sha256"]:
        raise ValueError("CSV e metadados das zonas estão inconsistentes; gere novamente.")
    if meta["fontes"] != {"risco_bairro_mes.csv": sha256(PAINEL), "postes_por_bairro.csv": sha256(POSTES)}:
        raise ValueError("A base processada mudou; gere as zonas novamente.")
    return pd.read_csv(csv), meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meses", type=int, default=12)
    parser.add_argument("--k", type=int, default=None)
    parser.add_argument("--saida", type=Path, default=SAIDA)
    args = parser.parse_args()
    bairros, meta = gerar(args.saida, args.meses, args.k)
    print(f"{len(bairros)} bairros | {meta['periodo']} | k={meta['k']} | silhouette={meta['silhouette']:.4f}")
    print(pd.DataFrame(meta["grupos"]).to_string(index=False))


if __name__ == "__main__":
    main()
