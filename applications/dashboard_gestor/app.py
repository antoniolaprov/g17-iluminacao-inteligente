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
from html import escape

import altair as alt
import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
CENTRO_RECIFE = (-8.06, -34.91)

st.set_page_config(page_title="G17 · Gestão da iluminação pública", page_icon="💡", layout="wide")
st.html("""<style>
@media (max-width: 640px) {
    h1 { font-size: 1.75rem !important; line-height: 1.25 !important; }
}
</style>""")


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


st.title("💡 Iluminação pública · Recife")
st.caption("Parque simulado com degradação calibrada pelos chamados reais da Emlurb · "
           "manutenção preditiva (falha em 14 dias) · priorização CPTED · dimerização com piso de segurança")

dados = api("/luminarias")
if "_erro" in dados:
    st.warning("Não foi possível carregar o parque de luminárias.")
    st.info("Aguarde alguns instantes e tente novamente. Se o problema continuar, confira se a central está ligada.")
    if st.button("Tentar novamente"):
        st.cache_data.clear()
        st.rerun()
    with st.expander("Detalhes para diagnóstico"):
        st.code(str(dados["_erro"]), language=None)
    st.stop()

df = pd.DataFrame(dados["luminarias"])
if df.empty:
    st.info("Nenhuma luminária disponível. Aguarde o primeiro ciclo de processamento e atualize a página.")
    if st.button("Tentar novamente"):
        st.cache_data.clear()
        st.rerun()
    st.stop()

dim = api("/dimerizacao")
metricas = api("/falha/metricas")
limiar = metricas.get("limiar_f1", 0.1) if "_erro" not in metricas else 0.1


def limpar_filtros():
    for chave, valor in (("bairros", []), ("niveis", []), ("so_risco", 0.0)):
        st.session_state[chave] = valor


with st.sidebar:
    st.header("Filtrar luminárias")
    bairros = st.multiselect("Bairros", sorted(df["bairro"].unique()), key="bairros")
    niveis = st.multiselect("Prioridade de segurança (CPTED)", ["alta", "media", "baixa"], key="niveis",
                            help="CPTED combina vulnerabilidade noturna, fluxo de pedestres e relevância da via.")
    so_risco = st.slider("Chance mínima de falha em 14 dias", 0.0, 1.0, 0.0, 0.01, key="so_risco",
                        format="%.2f", help="0,05 equivale a 5%. Luminárias apagadas permanecem no recorte para reparo.")
    st.button("Limpar filtros", on_click=limpar_filtros, use_container_width=True)
    st.divider()
    k = st.number_input("Inspeções por quinzena", 5, 100,
                        int(metricas.get("capacidade_k", 10)) if "_erro" not in metricas else 10,
                        help="Define quantas luminárias entram na lista e aparecem maiores no mapa.")
    if st.button("Atualizar dados", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    with st.expander("Conexão e referência"):
        st.caption(f"Referência simulada: {dados['data_ref']}")
        st.code(API_URL, language=None)

filtro = df.copy()
if bairros:
    filtro = filtro[filtro["bairro"].isin(bairros)]
if niveis:
    filtro = filtro[filtro["nivel_cpted"].isin(niveis)]
if so_risco > 0:
    filtro = filtro[(filtro["prob_falha_14d"].fillna(0) >= so_risco) | (filtro["estado"] == "APAGADA")]

st.caption(f"Referência do cenário simulado: {dados['data_ref']} · "
           f"Exibindo {len(filtro)} de {len(df)} luminárias · filtros na barra lateral")
c1, c2, c3 = st.columns(3)
c1.metric("Apagadas no recorte", int((filtro["estado"] == "APAGADA").sum()), help="Precisam de reparo corretivo.")
c2.metric("Cintilando no recorte", int((filtro["estado"] == "CINTILANDO").sum()), help="Sinal de possível falha próxima.")
c3.metric("Acima do limiar no recorte", int((filtro["prob_falha_14d"].fillna(0) >= limiar).sum()),
          help=f"Chance de falha ≥ {limiar:.1%}. Limiar do modelo; as faixas de cor do mapa são fixas.")

aba_mapa, aba_lum, aba_dim, aba_modelo, aba_cpted, aba_zonas = st.tabs(
    ["Operação", "Luminária", "Dimerização", "Modelo", "CPTED", "Zonas"])

with aba_mapa:
    st.subheader("Manutenção prioritária")
    topo = filtro.sort_values("posicao").head(k)
    if filtro.empty:
        st.info("Nenhuma luminária corresponde aos filtros. Use ‘Limpar filtros’ na barra lateral para ver o parque.")
    else:
        st.caption(f"Até {k} inspeções no recorte atual. A posição # é do ranking geral do parque.")
        st.dataframe(pd.DataFrame({
            "# geral": topo["posicao"], "Luminária": topo["id_luminaria"], "Bairro": topo["bairro"], "Estado": topo["estado"],
            "Chance em 14 dias": topo["prob_falha_14d"], "Segurança CPTED": topo["nivel_cpted"], "Prioridade": topo["prioridade"],
        }), hide_index=True, use_container_width=True,
            column_config={"Chance em 14 dias": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                           "Prioridade": st.column_config.NumberColumn(format="%.3f")})
        st.caption("Prioridade combina 50% de risco relativo e 50% de segurança CPTED. "
                   "Luminárias apagadas recebem risco relativo máximo. Sem previsão aparece como —.")

    with st.expander("Alertas do recorte", expanded=False):
        alertas = api("/alertas?limite=1000")
        if "_erro" in alertas:
            st.info("Não foi possível consultar os alertas. Tente atualizar os dados.")
        else:
            ids = set(filtro["id_luminaria"])
            visiveis = [a for a in alertas["alertas"] if a["id_luminaria"] in ids]
            if not visiveis:
                st.caption("Nenhum alerta registrado para este recorte na data de referência.")
            for a in visiveis[:20]:
                icone = {"apagada": "⚫", "cintilando": "🟠", "risco_alto": "🔴"}.get(a["tipo"], "•")
                st.write(f"{icone} {a['mensagem']}")
            if len(visiveis) > 20:
                st.caption(f"Exibindo 20 de {len(visiveis)} alertas. Refine os filtros para reduzir a lista.")

    st.subheader("Mapa do recorte")
    st.markdown("**Chance de falha em 14 dias**")
    legenda = [("#2a9d8f", "Abaixo de 2%"), ("#e9c46a", "2% a menos de 5%"),
               ("#f28c28", "5% a menos de 15%"), ("#d03b3b", "15% ou mais"),
               ("#1f1f1f", "Apagada"), ("#9e9e9e", "Sem previsão")]
    itens = "".join(f'<li style="display:flex;align-items:center;gap:6px">'
                    f'<span aria-hidden="true" style="display:inline-block;width:12px;height:12px;'
                    f'border:1px solid #888;border-radius:50%;background:{cor}"></span>{texto}</li>'
                    for cor, texto in legenda)
    st.markdown(f'<ul aria-label="Legenda do mapa" style="display:flex;flex-wrap:wrap;gap:8px 18px;'
                f'list-style:none;padding:0">{itens}</ul>', unsafe_allow_html=True)
    st.caption("Borda laranja = cintilando. Pontos maiores = luminárias da lista acima. "
               "Toque em um ponto para ver os detalhes. Coordenadas aproximadas de um parque simulado.")
    if not filtro.empty:
        mapa = folium.Map(location=CENTRO_RECIFE, zoom_start=13, tiles="OpenStreetMap", scroll_wheel_zoom=False)
        destaques = set(topo["id_luminaria"])
        for _, l in filtro.iterrows():
            prob = l["prob_falha_14d"]
            score = "sem dados" if pd.isna(l["score_cpted"]) else f"{l['score_cpted']:.2f}"
            texto = (f"<b>{escape(str(l['id_luminaria']))}</b> · {escape(str(l['bairro']))}<br>"
                     f"Estado: {escape(str(l['estado']))}<br>"
                     f"Chance de falha em 14 dias: {'sem previsão' if pd.isna(prob) else f'{prob:.1%}'}<br>"
                     f"Segurança CPTED: {escape(str(l['nivel_cpted']))} ({score})<br>"
                     f"Posição geral: #{int(l['posicao'])} · {l['potencia_w']:.0f} W · via {escape(str(l['classe_via']))}")
            folium.CircleMarker(
                location=(l["lat"], l["lon"]), radius=8 if l["id_luminaria"] in destaques else 4,
                color="#f28c28" if l["estado"] == "CINTILANDO" else cor_risco(prob, l["estado"]),
                weight=3 if l["estado"] == "CINTILANDO" else 1, fill=True,
                fill_color=cor_risco(prob, l["estado"]), fill_opacity=0.85,
                popup=folium.Popup(texto, max_width=260),
                tooltip=f"{escape(str(l['id_luminaria']))} · {escape(str(l['estado']))}",
            ).add_to(mapa)
        if len(filtro) == 1:
            mapa.location = (float(filtro.iloc[0]["lat"]), float(filtro.iloc[0]["lon"]))
        else:
            mapa.fit_bounds([[filtro["lat"].min(), filtro["lon"].min()],
                             [filtro["lat"].max(), filtro["lon"].max()]], max_zoom=15, padding=(24, 24))
        st_folium(mapa, height=440, use_container_width=True, returned_objects=[])

with aba_modelo:
    st.caption("Avaliação global do modelo em dados simulados; os filtros não alteram estas métricas.")
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
    st.caption("CPTED: segurança pelo desenho do ambiente. Pesos e sensibilidade do parque completo.")
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
    st.caption("Visão do parque completo: os filtros de luminárias não alteram o plano de dimerização.")
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
            longo["série"] = longo["série"].map({"pct_medio": "Potência média", "pct_min": "Potência mínima"})
            st.altair_chart(alt.Chart(longo).mark_line(point=True).encode(
                x=alt.X("hora:N", sort=ordem), y=alt.Y("potência (%):Q", scale=alt.Scale(domain=[0, 100])),
                color="série:N"), use_container_width=True)
            st.caption("Desejada = 40% + 60% × demanda da via; final = máx(desejada; piso CPTED; piso ABNT). "
                       "Pisos CPTED: alta 100% das 18h às 22h e ≥ 80% no resto; média ≥ 70%; baixa ≥ 50%.")
        with b:
            seg, eco = dim["seguranca"], dim["economia"]
            st.subheader("Segurança da dimerização")
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


with aba_zonas:
    st.subheader("Perfis históricos dos bairros")
    st.caption("Análise complementar dos 94 bairros da base Emlurb. Os filtros do parque simulado não se aplicam aqui.")
    zonas = api("/zonas")
    if "_erro" in zonas:
        st.info("Agrupamento histórico indisponível no momento. Tente atualizar os dados.")
    else:
        zm = zonas["metadados"]
        zb = pd.DataFrame(zonas["bairros"])
        st.markdown(f"**{zm['bairros']} bairros · {zm['k']} grupos** · "
                    f"chamados observados de **{zm['periodo']['inicio']} a {zm['periodo']['fim']}** · cadastro de postes de 2025")
        st.info("Os grupos reúnem perfis semelhantes de chamados e postes; não precisam ser vizinhos. "
                "Z01 tem maior média de chamados por bairro neste recorte. Isso não mede segurança, "
                "não é probabilidade de falha e não envia comandos aos postes.")
        grupos = st.multiselect("Grupos do histórico", sorted(zb["zona"].unique()), key="zonas_historicas")
        recorte = zb[zb["zona"].isin(grupos)] if grupos else zb
        st.altair_chart(alt.Chart(recorte).mark_circle(size=80, opacity=0.8).encode(
            x=alt.X("total_postes:Q", title="Postes cadastrados (escala log)", scale=alt.Scale(type="log")),
            y=alt.Y("chamados_media_mensal:Q", title="Chamados por mês (escala symlog)", scale=alt.Scale(type="symlog")),
            color=alt.Color("zona:N", title="Grupo", scale=alt.Scale(domain=sorted(zb["zona"].unique()),
                            range=["#2E6F8E", "#C1502E", "#728C39", "#835BA7", "#D99D28", "#5A7D87"][:zm["k"]])),
            tooltip=[alt.Tooltip("bairro_norm:N", title="Bairro"), alt.Tooltip("zona:N", title="Grupo"),
                     alt.Tooltip("total_postes:Q", title="Postes", format=".0f"),
                     alt.Tooltip("chamados_media_mensal:Q", title="Chamados/mês", format=".2f"),
                     alt.Tooltip("taxa_1000_postes:Q", title="Chamados/mês por 1.000 postes", format=".2f")]
        ), use_container_width=True)
        st.caption(f"K-Means em log1p + padronização. Silhouette: {zm['silhouette']:.3f}; "
                   f"ARI mínimo com quatro sementes adicionais: {zm['estabilidade']['ari_minimo']:.3f}. "
                   "São medidas de separação/estabilidade, não de acerto de previsão.")
        st.dataframe(recorte.rename(columns={"bairro_norm": "Bairro", "zona": "Grupo", "total_postes": "Postes",
                     "chamados_total": "Chamados no período", "chamados_media_mensal": "Chamados/mês",
                     "taxa_1000_postes": "Chamados/mês por 1.000 postes"}).sort_values(["Grupo", "Chamados/mês"], ascending=[True, False]),
                     hide_index=True, use_container_width=True)
        st.download_button("Baixar bairros e grupos (CSV)", recorte.to_csv(index=False).encode("utf-8"),
                           file_name="zonas_bairros.csv", mime="text/csv")
        st.caption("Limitações: chamados dependem de notificação; o cadastro estático de 2025 é aplicado "
                   "a todo o período; bairros grandes tendem a gerar mais chamados. A taxa é apenas contexto, "
                   "não entra nas duas features de agrupamento. IDs de grupo podem mudar em novos recortes.")

with aba_lum:
    if filtro.empty:
        st.info("Sem luminárias neste recorte. Limpe ou ajuste os filtros para consultar o histórico.")
        st.stop()
    escolha = st.selectbox("Luminária do recorte", filtro.sort_values("posicao")["id_luminaria"])
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
