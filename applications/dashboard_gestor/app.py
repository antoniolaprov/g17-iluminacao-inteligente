"""
Painel do gestor da iluminação (proposta, funcionalidade 3: dashboard geoespacial em Streamlit
consumindo a API REST em FastAPI).

Mostra o parque de luminárias no mapa do Recife, colorido pelo estado e pelo risco de falha em
14 dias, a lista de manutenção priorizada (risco de falha + score CPTED), os alertas, as métricas
do modelo, os pesos CPTED e o plano de dimerização com o teste de segurança.

O painel em HTML (applications/dashboard/) continua sendo o da maquete em tempo real; este é o da
gestão do parque.

Uso:
    streamlit run applications/dashboard_gestor/app.py        (abre em http://localhost:8501)
    (variável: API_URL, padrão http://localhost:8000)
"""

import os

import altair as alt
import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
CENTRO_RECIFE = (-8.06, -34.91)

st.set_page_config(page_title="G17 · Gestão da iluminação pública", page_icon="💡", layout="wide")


@st.cache_data(ttl=20, show_spinner=False)
def api(caminho: str):
    try:
        r = requests.get(f"{API_URL}{caminho}", timeout=15)
        if r.status_code != 200:
            return {"_erro": r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text}
        return r.json()
    except requests.RequestException as erro:
        return {"_erro": f"API fora do ar ({API_URL}): {erro}"}


def cor_risco(prob: float | None, estado: str) -> str:
    if estado == "APAGADA":
        return "#1f1f1f"
    if prob is None or pd.isna(prob):
        return "#9e9e9e"
    if prob >= 0.15:
        return "#d03b3b"
    if prob >= 0.05:
        return "#f28c28"
    if prob >= 0.02:
        return "#e9c46a"
    return "#2a9d8f"


st.title("💡 Gestão inteligente da iluminação pública: Recife")
st.caption("Parque simulado com degradação calibrada pelos chamados reais da Emlurb · "
           "manutenção preditiva (falha em 14 dias) · priorização CPTED · dimerização com piso de segurança")

dados = api("/luminarias")
if "_erro" in dados:
    st.warning(f"Ainda sem dados do parque: {dados['_erro']}")
    st.info("Suba o docker compose (serviços parque, ingestor e pipeline) e aguarde o primeiro ciclo do pipeline.")
    st.stop()

df = pd.DataFrame(dados["luminarias"])
dim = api("/dimerizacao")
metricas = api("/falha/metricas")

with st.sidebar:
    st.header("Filtros")
    bairros = st.multiselect("Bairro", sorted(df["bairro"].unique()))
    niveis = st.multiselect("Nível CPTED", ["alta", "media", "baixa"])
    so_risco = st.slider("P(falha em 14 dias) mínima", 0.0, 0.5, 0.0, 0.01)
    k = st.number_input("Capacidade da equipe (inspeções por quinzena)", 5, 100,
                        int(metricas.get("capacidade_k", 10)) if "_erro" not in metricas else 10)
    if st.button("Atualizar agora"):
        st.cache_data.clear()
    st.caption(f"Data de referência: **{dados['data_ref']}** · API: {API_URL}")

filtro = df.copy()
if bairros:
    filtro = filtro[filtro["bairro"].isin(bairros)]
if niveis:
    filtro = filtro[filtro["nivel_cpted"].isin(niveis)]
if so_risco > 0:
    filtro = filtro[(filtro["prob_falha_14d"].fillna(0) >= so_risco) | (filtro["estado"] == "APAGADA")]

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Luminárias", len(df))
c2.metric("Apagadas (reparo)", int((df["estado"] == "APAGADA").sum()))
c3.metric("Cintilando", int((df["estado"] == "CINTILANDO").sum()))
limiar = metricas.get("limiar_f1", 0.1) if "_erro" not in metricas else 0.1
c4.metric("Risco alto (14 dias)", int((df["prob_falha_14d"].fillna(0) >= limiar).sum()), help=f"P ≥ limiar {limiar:.2f}")
if "_erro" not in dim:
    c5.metric("Economia da dimerização", f"{dim['economia']['economia_pct']:.1f}%", help="vs. tudo a 100% à noite")
    c6.metric("Violações de segurança", f"{'✅' if dim['seguranca']['aprovado'] else '❌'} {dim['seguranca']['violacoes']}",
              help=f"Teste automático da dimerização: {dim['seguranca']['comandos']} comandos conferidos contra os pisos "
                   "CPTED e ABNT; critério de aceite = 0 violações")

aba_mapa, aba_modelo, aba_cpted, aba_dim, aba_lum = st.tabs(
    ["🗺️ Mapa e prioridades", "📈 Modelo de falha", "🛡️ Score CPTED", "🌙 Dimerização", "🔎 Luminária"])

with aba_mapa:
    esq, dir_ = st.columns([3, 2])
    with esq:
        mapa = folium.Map(location=CENTRO_RECIFE, zoom_start=13, tiles="OpenStreetMap")
        for _, l in filtro.iterrows():
            prob = l["prob_falha_14d"]
            texto = (f"<b>{l['id_luminaria']}</b> · {l['bairro']}<br>estado: {l['estado']}<br>"
                     f"P(falha 14d): {'—' if pd.isna(prob) else f'{prob:.1%}'}<br>"
                     f"CPTED: {l['nivel_cpted']} ({'sem dados' if pd.isna(l['score_cpted']) else f'{l['score_cpted']:.2f}'})<br>"
                     f"prioridade: #{l['posicao']} · {l['potencia_w']:.0f} W · via {l['classe_via']}")
            folium.CircleMarker(
                location=(l["lat"], l["lon"]), radius=7 if l["posicao"] <= k else 4,
                color="#f28c28" if l["estado"] == "CINTILANDO" else cor_risco(prob, l["estado"]),
                weight=3 if l["estado"] == "CINTILANDO" else 1, fill=True,
                fill_color=cor_risco(prob, l["estado"]), fill_opacity=0.85,
                popup=folium.Popup(texto, max_width=260), tooltip=l["id_luminaria"],
            ).add_to(mapa)
        st_folium(mapa, height=560, use_container_width=True, returned_objects=[])
        st.caption("Cor = risco de falha em 14 dias (verde < 2%, amarelo < 5%, laranja < 15%, vermelho ≥ 15%; "
                   "preto = apagada). Borda laranja = cintilando. Pontos maiores = top-k da lista de manutenção. "
                   "Coordenadas aproximadas (parque simulado).")
    with dir_:
        st.subheader(f"Lista de manutenção (top {k})")
        topo = filtro.sort_values("posicao").head(k)
        st.dataframe(pd.DataFrame({
            "#": topo["posicao"], "luminária": topo["id_luminaria"], "bairro": topo["bairro"], "estado": topo["estado"],
            "P(falha 14d)": topo["prob_falha_14d"], "CPTED": topo["nivel_cpted"], "prioridade": topo["prioridade"],
        }), hide_index=True, use_container_width=True,
            column_config={"P(falha 14d)": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                           "prioridade": st.column_config.NumberColumn(format="%.3f")})
        st.caption("prioridade = 0,5 × risco relativo de falha + 0,5 × score CPTED (apagadas primeiro: reparo corretivo)")
        alertas = api("/alertas?limite=200")
        if "_erro" not in alertas:
            st.subheader("Alertas")
            st.write({k_: v for k_, v in alertas["contagem"].items()})
            for a in alertas["alertas"][:12]:
                icone = {"apagada": "⚫", "cintilando": "🟠", "risco_alto": "🔴"}.get(a["tipo"], "•")
                st.write(f"{icone} {a['mensagem']}")

with aba_modelo:
    if "_erro" in metricas:
        st.info(metricas["_erro"])
    else:
        st.markdown(f"**Modelo em produção:** `{metricas['modelo']}` com calibração **{metricas['calibracao']}** · "
                    f"treinado em {metricas['treinado_em']} · limiar F1 {metricas['limiar_f1']:.3f} · "
                    f"{'✅ vence' if metricas['vence_baselines'] else '❌ não vence'} os baselines "
                    f"(melhor baseline: {metricas['melhor_baseline']})")
        tabela = pd.DataFrame(metricas["metricas"]).T
        colunas = [c for c in ["val_pr_auc", "teste_pr_auc", "teste_roc_auc", "teste_precision_at_k", "teste_recall_at_k",
                               "teste_brier", "teste_f1"] if c in tabela]
        st.subheader("Comparação dos modelos (PR-AUC é a métrica principal)")
        st.dataframe(tabela[colunas].sort_values("val_pr_auc", ascending=False).round(4), use_container_width=True)
        a, b = st.columns(2)
        with a:
            st.subheader("Períodos (divisão temporal com intervalo de 14 dias)")
            st.dataframe(pd.DataFrame(metricas["periodos"], index=["início", "fim", "linhas", "positivas"]).T,
                         use_container_width=True)
            if metricas.get("robustez"):
                st.subheader("Teste de robustez (premissas alteradas)")
                st.dataframe(pd.DataFrame(metricas["robustez"]).T[["pr_auc", "roc_auc", "brier", "taxa_positivos"]].round(4),
                             use_container_width=True)
        with b:
            st.subheader("Importância dos atributos")
            imp = (pd.Series(metricas["importancia_features"]).sort_values(ascending=False).head(12)
                   .rename_axis("atributo").reset_index(name="importância"))
            st.altair_chart(alt.Chart(imp).mark_bar().encode(
                x="importância:Q", y=alt.Y("atributo:N", sort="-x", title=None)), use_container_width=True)
        st.caption("Resultados sobre dados SIMULADOS (proposta, g.5): não equivalem ao comportamento real das "
                   "luminárias do Recife.")

with aba_cpted:
    cp = api("/cpted")
    if "_erro" in cp:
        st.info(cp["_erro"])
    else:
        a, b = st.columns(2)
        with a:
            st.subheader("Pesos (AHP)")
            st.dataframe(pd.Series(cp["pesos"], name="peso").to_frame(), use_container_width=True)
            st.markdown(f"Razão de consistência **CR = {cp['cr']:.3f}** "
                        f"({'consistente, < 0,10' if cp['consistente'] else 'INCONSISTENTE, revisar a matriz'})")
            for par, texto in cp["justificativas"].items():
                st.caption(f"**{par}**: {texto}")
        with b:
            if "sensibilidade" in cp:
                s = cp["sensibilidade"]
                st.subheader("Sensibilidade do ranking (±20%)")
                st.markdown(f"Spearman mínimo **{s['spearman_minimo']:.3f}** · sobreposição mínima do top-{s['k']} "
                            f"**{s['sobreposicao_minima']:.0%}** · {'estável' if s['estavel'] else 'sensível: reportar como limitação'}")
                st.dataframe(pd.DataFrame(s["cenarios"]).T, use_container_width=True)

with aba_dim:
    if "_erro" in dim:
        st.info(dim["_erro"])
    else:
        a, b = st.columns([3, 2])
        with a:
            st.subheader("Potência média e mínima por hora da noite")
            ph = pd.DataFrame(dim["por_hora"])
            ph["hora"] = ph["hora"].map(lambda h: f"{int(h):02d}h")
            ordem = ph["hora"].tolist()               # a API já devolve na ordem da noite (18h -> 05h)
            longo = ph.melt(id_vars="hora", value_vars=["pct_medio", "pct_min"], var_name="série", value_name="potência (%)")
            st.altair_chart(alt.Chart(longo).mark_line(point=True).encode(
                x=alt.X("hora:N", sort=ordem), y=alt.Y("potência (%):Q", scale=alt.Scale(domain=[0, 100])),
                color="série:N"), use_container_width=True)
            st.caption("Desejada = 40% + 60% × demanda da via; final = máx(desejada; piso CPTED; piso ABNT). "
                       "Pisos CPTED: alta 100% das 18h às 22h e ≥ 80% no resto; média ≥ 70%; baixa ≥ 50%.")
        with b:
            seg, eco = dim["seguranca"], dim["economia"]
            st.subheader("Teste automático de segurança")
            st.markdown(f"{'✅' if seg['aprovado'] else '❌'} **{seg['violacoes']} violações** em {seg['comandos']} "
                        f"comandos ({seg['pct_violacoes']}%). Critério de aceite: 0%.")
            st.subheader("Economia de energia")
            st.markdown(f"- Parque simulado: **{eco['economia_pct']}%** por noite "
                        f"({eco['kwh_ano_economizados_parque']:,.0f} kWh/ano)")
            if "recife_mwh_ano_economizados" in eco:
                st.markdown(f"- Extrapolado para os 111.665 postes do Recife (potência média real da Emlurb): "
                            f"**{eco['recife_mwh_ano_economizados']:,.0f} MWh/ano** de {eco['recife_mwh_ano_sem']:,.0f} "
                            f"(meta da Prefeitura: até {eco['meta_prefeitura_pct']}%)")
            st.caption("Iluminância estimada de forma linear pela potência (proposta, g.6); validação com luxímetro "
                       "é trabalho futuro.")

with aba_lum:
    escolha = st.selectbox("Luminária", df.sort_values("posicao")["id_luminaria"])
    det = api(f"/luminarias/{escolha}?dias=120")
    if "_erro" in det:
        st.info(det["_erro"])
    else:
        cad = det["cadastro"]
        st.markdown(f"**{cad['id_luminaria']}** · {cad['bairro']} · {cad['potencia_w']:.0f} W · via {cad['classe_via']} · "
                    f"projeto {cad['e_projeto_lx']} lx")
        tel = pd.DataFrame(det["telemetria"])
        if not tel.empty:
            tel["data"] = pd.to_datetime(tel["data"])
            a, b = st.columns(2)
            a.caption("Temperatura do driver (°C)")
            a.line_chart(tel.set_index("data")[["temp_media_c"]], height=220)
            b.caption("Ondulação da corrente, ripple (%): sobe quando a luminária cintila")
            b.line_chart(tel.set_index("data")[["ripple_pct"]], height=220)
            falhas = tel[tel["falha"] == 1]["data"].dt.date.astype(str).tolist()
            if falhas:
                st.caption(f"Falhas registradas no período: {', '.join(falhas)}")
        prev = pd.DataFrame(det["previsoes"])
        if not prev.empty:
            st.caption("P(falha nos próximos 14 dias) calculada pelo pipeline em cada dia")
            st.line_chart(prev.set_index("data_ref")[["prob_falha_14d"]], height=200)
