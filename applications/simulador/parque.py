"""
Simulador do parque de luminárias com modelo de degradação (proposta, seção g.5 e item 06).

Cada luminária simulada tem potência, classe de via (ABNT NBR 5101), coordenadas num dos 10 bairros
do config.json e critérios CPTED. A cada dia simulado ela registra o que uma telegestão mede:
temperatura do driver, tensão (com os surtos), corrente, ondulação da corrente (ripple, sinal de
cintilação), horas de operação e ciclos de acendimento.

A falha NÃO é uma regra escrita a partir desses atributos. Ela é sorteada com uma taxa que depende de
mecanismos conhecidos de degradação de LED, e de fatores que o modelo não enxerga:
    - driver como modo de falha dominante: Weibull nas horas efetivas de uso;
    - aceleração pela temperatura (Arrhenius, Ea = 0,7 eV);
    - dano acumulado por surtos de tensão (mais frequentes na época de chuva), atenuado por DPS;
    - cintilação como estado de degradação que antecede a falha (multiplica o risco);
    - fim de vida pela depreciação do fluxo (L70, metodologia LM-80/TM-21);
    - fatores latentes por luminária (qualidade do lote, DPS, dissipação) e falhas externas
      (vandalismo, cabos) que não dependem de nenhum atributo, mais ruído de medição.
A taxa total é calibrada com os chamados reais de lâmpada apagada da Emlurb (2,39% dos postes por
mês, com a sazonalidade mensal), que é o uso de dado real previsto na seção g.7 da proposta.

Parâmetros: simulador/premissas_parque.json. Explicação e fontes: docs/PREMISSAS_SIMULADOR.md.

Uso:
    python applications/simulador/parque.py gerar     # calibra, gera o histórico e grava no banco
    python applications/simulador/parque.py servir    # continua a simulação ao vivo, publicando no MQTT
    (variáveis: DATABASE_URL, MQTT_HOST, MQTT_PORT, PARQUE_DIA_S = segundos por dia simulado, padrão 30)
"""

import argparse
import copy
import json
import math
import os
import pickle
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

PASTA = Path(__file__).resolve().parent
APLICACOES = PASTA.parent
sys.path.insert(0, str(APLICACOES))
from banco_parque import PASTA_SIMULADO, contar, gravar  # noqa: E402

ARQ_PREMISSAS = PASTA / "premissas_parque.json"
ARQ_ESTADO = PASTA_SIMULADO / "estado_parque.pkl"
ARQ_CALIBRACAO = PASTA_SIMULADO / "calibracao.json"
PROCESSADOS = APLICACOES / "ml" / "data" / "processed"
K_BOLTZMANN_EV = 8.617e-5
METROS_POR_GRAU = 111_320


def carregar_premissas(alteracoes: dict | None = None) -> dict:
    """Premissas do arquivo, com alterações opcionais (usadas no teste de robustez).
    alteracoes = {"temperatura.elevacao_driver_c": 34, "surtos.taxa_dia": 0.02}"""
    premissas = json.loads(ARQ_PREMISSAS.read_text(encoding="utf-8"))
    for chave, valor in (alteracoes or {}).items():
        alvo = premissas
        *caminho, ultima = chave.split(".")
        for parte in caminho:
            alvo = alvo.get(parte) if isinstance(alvo, dict) else None
        if not isinstance(alvo, dict) or ultima not in alvo:
            raise KeyError(f"Premissa desconhecida: {chave}")
        alvo[ultima] = valor
    return premissas


def dados_reais_bairros(bairros: list[str]) -> pd.DataFrame:
    """Postes e chamados reais da Emlurb por bairro: definem quantas luminárias cada bairro recebe e a
    parte "precariedade da iluminação" da vulnerabilidade noturna (critério CPTED)."""
    postes = pd.read_csv(PROCESSADOS / "postes_por_bairro.csv").set_index("bairro_norm")
    painel = pd.read_csv(PROCESSADOS / "risco_bairro_mes.csv")
    recente = painel[painel["ano_mes"] >= "2025-01"].groupby("bairro_norm")["chamados_lampada_apagada"].mean()
    tabela = pd.DataFrame({"total_postes": postes["total_postes"].reindex(bairros),
                           "chamados_mes": recente.reindex(bairros)})
    tabela["taxa_1000"] = tabela["chamados_mes"] / tabela["total_postes"] * 1000
    return tabela


class Parque:
    def __init__(self, premissas: dict, escala_risco: dict | float = 1.0):
        self.p = premissas
        # escala do risco do driver por mês do ano (sai da calibração com a Emlurb)
        self.escala = (escala_risco if isinstance(escala_risco, dict)
                       else {str(m): float(escala_risco) for m in range(1, 13)})
        self.rng = np.random.default_rng(premissas["semente"])
        self.dia = date.fromisoformat(premissas["inicio_historico"])
        self.catalogo = self._criar_catalogo()
        n = len(self.catalogo)
        self.potencia = self.catalogo["potencia_w"].to_numpy(float)
        self.pct = np.full(n, 100.0)          # potência média aplicada no histórico (sem dimerização)
        # estado oculto (o modelo não vê): idade efetiva, dano do driver, fatores latentes
        idade = self.rng.uniform(0, premissas["idade_inicial_horas_max"], n)
        self.horas = idade.copy()
        self.horas_ef = idade * self.rng.uniform(0.8, 1.2, n)
        self.dano = self.rng.uniform(0, 0.3, n) * idade / premissas["idade_inicial_horas_max"]
        self.cintilando = np.zeros(n, bool)
        self.ciclos = np.round(idade / 12)
        self.apagada_ate = np.full(n, -1)     # ordinal do dia em que a luminária volta (após o reparo)
        self._sortear_latentes(np.ones(n, bool))
        # Aquecimento: roda um período antes do início do histórico, sem registrar, para o parque
        # começar em regime (dano, cintilação e trocas já distribuídos como num parque em operação)
        inicio = self.dia
        self.dia = inicio - timedelta(days=premissas.get("aquecimento_dias", 0))
        while self.dia < inicio:
            self.passo(registrar=False)

    # ---------------- cadastro ----------------
    def _criar_catalogo(self) -> pd.DataFrame:
        p, rng = self.p, self.rng
        bairros = list(p["bairros"])
        minimo_total = len(bairros) * p["luminarias_minimo_por_bairro"]
        if p["luminarias"] < minimo_total:
            raise ValueError(f"O parque precisa de pelo menos {minimo_total} luminárias para respeitar o mínimo por bairro")
        reais = dados_reais_bairros(bairros)
        peso = reais["total_postes"].fillna(reais["total_postes"].median())
        qtd = np.maximum(p["luminarias_minimo_por_bairro"],
                         np.floor(peso / peso.sum() * p["luminarias"])).astype(int).to_numpy()
        while qtd.sum() > p["luminarias"]:              # ajusta o total exato
            qtd[np.argmax(qtd)] -= 1
        while qtd.sum() < p["luminarias"]:
            qtd[np.argmax(peso.to_numpy() / qtd)] += 1
        taxa = reais["taxa_1000"].fillna(reais["taxa_1000"].median())
        vuln_bairro = ((taxa - taxa.min()) / (taxa.max() - taxa.min() or 1)).to_dict()

        classes = p["classe_via"]
        linhas, k = [], 0
        for bairro, q in zip(bairros, qtd):
            info = p["bairros"][bairro]
            lat0, lon0, raio = info["lat"], info["lon"], info["raio_m"]
            n_polos = rng.integers(p["cpted"]["polos_por_bairro"][0], p["cpted"]["polos_por_bairro"][1] + 1)
            polos = [self._ponto(lat0, lon0, raio) for _ in range(n_polos)]
            for _ in range(q):
                k += 1
                lat, lon = self._ponto(lat0, lon0, raio)
                dist = min(self._metros(lat, lon, a, b) for a, b in polos)
                fluxo = float(np.clip(math.exp(-dist / p["cpted"]["alcance_polo_m"]) + rng.normal(0, 0.05), 0, 1))
                classe = rng.choice(classes["classes"], p=classes["probabilidades"])
                e_min = classes["iluminancia_min_lx"][classe]
                relev = {"P1": 1.0, "P2": 0.8, "P3": 0.6, "P4": 0.4, "P5": 0.2, "P6": 0.1}[classe]
                relev = float(np.clip(relev + (0.2 if dist < p["cpted"]["alcance_polo_m"] else 0), 0, 1))
                w = p["cpted"]["peso_vulnerabilidade_bairro"]
                vuln = float(np.clip(w * vuln_bairro[bairro] + (1 - w) * rng.uniform(0, 1), 0, 1))
                linha = {
                    "id_luminaria": f"L{k:03d}", "bairro": bairro, "lat": round(lat, 6), "lon": round(lon, 6),
                    "potencia_w": float(rng.choice(p["potencia_nominal_w"]["valores"],
                                                   p=p["potencia_nominal_w"]["probabilidades"])),
                    "classe_via": str(classe),
                    "e_projeto_lx": round(e_min * rng.uniform(*classes["margem_projeto"]), 2),
                    "fluxo_pedestres": round(fluxo, 3), "vulnerabilidade": round(vuln, 3),
                    "relevancia_via": round(relev, 3),
                }
                if rng.uniform() < p["cpted"]["fracao_sem_dados"]:   # trecho sem dados: CPTED = alta
                    linha.update(fluxo_pedestres=None, vulnerabilidade=None, relevancia_via=None)
                linhas.append(linha)
        return pd.DataFrame(linhas)

    def _ponto(self, lat0: float, lon0: float, raio: float) -> tuple[float, float]:
        r, ang = raio * math.sqrt(self.rng.uniform()), self.rng.uniform(0, 2 * math.pi)
        return (lat0 + r * math.cos(ang) / METROS_POR_GRAU,
                lon0 + r * math.sin(ang) / (METROS_POR_GRAU * math.cos(math.radians(lat0))))

    @staticmethod
    def _metros(lat1, lon1, lat2, lon2) -> float:
        dy = (lat1 - lat2) * METROS_POR_GRAU
        dx = (lon1 - lon2) * METROS_POR_GRAU * math.cos(math.radians(lat1))
        return math.hypot(dx, dy)

    def _sortear_latentes(self, quais: np.ndarray) -> None:
        n, p = int(quais.sum()), self.p
        if not hasattr(self, "qualidade"):
            tam = len(quais)
            self.qualidade, self.dissipacao, self.protecao = np.ones(tam), np.ones(tam), np.zeros(tam)
        self.qualidade[quais] = self.rng.lognormal(0, p["driver"]["sigma_latente"], n)
        self.dissipacao[quais] = self.rng.lognormal(0, p["temperatura"]["dispersao_dissipacao"], n)
        tem_dps = self.rng.uniform(size=n) < p["surtos"]["fracao_com_dps"]
        self.protecao[quais] = np.where(tem_dps, p["surtos"]["protecao_dps"], 0.0)

    # ---------------- um dia ----------------
    def passo(self, registrar: bool = True) -> pd.DataFrame | dict:
        p, rng, n = self.p, self.rng, len(self.catalogo)
        hoje = self.dia.toordinal()
        doy, mes = self.dia.timetuple().tm_yday, str(self.dia.month)

        voltou = self.apagada_ate == hoje                  # reparo concluído: luminária nova
        if voltou.any():
            self.horas[voltou] = self.horas_ef[voltou] = self.dano[voltou] = self.ciclos[voltou] = 0
            self.cintilando[voltou] = False
            self.apagada_ate[voltou] = -1
            self._sortear_latentes(voltou)
        em_reparo = self.apagada_ate > hoje
        opera = ~em_reparo

        # noite mais longa em junho (inverno no hemisfério sul)
        horas_noite = 12 + 0.35 * math.cos(2 * math.pi * (doy - 172) / 365)
        horas_op = np.where(opera, horas_noite + rng.normal(0, 0.1, n), 0.0)
        t = p["temperatura"]
        t_amb = (t["ambiente_noite_c"] + t["amplitude_sazonal_c"] * math.cos(2 * math.pi * (doy - t["dia_mais_quente"]) / 365)
                 + rng.normal(0, t["ruido_ambiente_c"]) + rng.normal(0, 0.3, n))
        t_driver = t_amb + np.where(opera, t["elevacao_driver_c"] * self.dissipacao
                                    * np.sqrt(self.potencia / 100) * self.pct / 100, 0.0)
        a = p["arrhenius"]
        fator_acel = np.exp(a["ea_ev"] / K_BOLTZMANN_EV * (1 / (a["t_ref_c"] + 273.15) - 1 / (t_driver + 273.15)))

        horas_ef_antes = self.horas_ef.copy()
        self.horas += horas_op
        self.horas_ef += horas_op * fator_acel
        fluxo = np.exp(-math.log(1 / 0.7) / p["l70"]["horas_ref"] * self.horas_ef)

        s = p["surtos"]
        surtos = rng.poisson(s["taxa_dia"] * s["chuva_por_mes"][mes], n) * opera
        self.dano += surtos * rng.uniform(*s["dano"], n) * (1 - self.protecao)
        self.dano += p["dano_termico_dia"] * fator_acel * opera
        self.dano = np.clip(self.dano, 0, 1)
        c = p["cintilacao"]
        comeca = opera & ~self.cintilando & (self.dano > c["limiar_dano"]) & (rng.uniform(size=n) < c["prob_inicio_dia"])
        self.cintilando |= comeca

        d, sazonal = p["driver"], p["calibracao"]["sazonalidade_mensal"][mes]
        eta, k = d["escala_horas"], d["weibull_forma"]
        risco = (((self.horas_ef / eta) ** k - (horas_ef_antes / eta) ** k) * self.qualidade
                 * (1 + d["peso_dano"] * self.dano) * np.where(self.cintilando, d["multiplicador_cintilacao"], 1)
                 * self.escala[mes])
        p_driver = 1 - np.exp(-risco)
        p_externa = p["falha_externa_fracao"] * p["calibracao"]["taxa_falha_mensal_alvo"] / 30 * sazonal
        fim_de_vida = fluxo < 0.7
        falha = opera & ((rng.uniform(size=n) < p_driver) | (rng.uniform(size=n) < p_externa) | fim_de_vida)
        reparo = rng.integers(p["reparo_dias"][0], p["reparo_dias"][1] + 1, n)
        self.apagada_ate = np.where(falha, hoje + reparo, self.apagada_ate)

        ciclos_dia = np.where(opera, 1 + np.where(self.cintilando, rng.poisson(4, n), 0), 0)
        self.ciclos += ciclos_dia
        self.dia += timedelta(days=1)
        resumo = {"falhas": int(falha.sum()), "operando": int(opera.sum()), "mes": int(mes),
                  "por_tipo": {"fim_de_vida": int((falha & fim_de_vida).sum())}}
        if not registrar:
            return resumo

        apagada = em_reparo | falha
        tensao = 220 + rng.normal(0, 2.5, n)
        detectado = (surtos > 0) & (rng.uniform(size=n) < s["deteccao"])
        tensao_max = np.where(detectado, rng.uniform(260, 320, n), tensao + rng.uniform(3, 8, n))
        corrente = np.where(apagada, 0.0, self.potencia * self.pct / 100 / tensao * (1 + 0.04 * self.dano)
                            * (1 + rng.normal(0, 0.01, n)))
        ripple = np.where(apagada, 0.0, np.clip(3 + 30 * np.maximum(0, self.dano - 0.3)
                                                + np.where(self.cintilando, rng.uniform(10, 25, n), 0)
                                                + rng.normal(0, 1.5, n), 0.5, None))
        temp = t_driver + rng.normal(0, t["ruido_medicao_c"], n)
        df = pd.DataFrame({
            "data": (self.dia - timedelta(days=1)).isoformat(), "id_luminaria": self.catalogo["id_luminaria"],
            "temp_media_c": temp.round(2), "temp_max_c": (temp + np.where(apagada, 0.5, rng.uniform(1, 4, n))).round(2),
            "tensao_media_v": tensao.round(2), "tensao_min_v": (tensao - rng.uniform(3, 8, n)).round(2),
            "tensao_max_v": tensao_max.round(2), "corrente_media_a": corrente.round(4), "ripple_pct": ripple.round(2),
            "horas_operacao": np.where(em_reparo, 0.0, horas_op).round(2), "horas_acumuladas": self.horas.round(1),
            "ciclos_dia": ciclos_dia, "ciclos_acumulados": self.ciclos, "surtos_dia": np.where(detectado, surtos, 0),
            "pct_medio": np.where(apagada, 0.0, self.pct),
            "estado": np.where(apagada, "APAGADA", np.where(self.cintilando, "CINTILANDO", "OK")),
            "falha": falha.astype(int),
        })
        return self._falhas_de_medicao(df)

    def _falhas_de_medicao(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ruído de telegestão de verdade: leituras que não chegam e leituras impossíveis
        (o pipeline do Airflow tem que tratar)."""
        f, rng = self.p["falhas_de_medicao"], self.rng
        invalida = rng.uniform(size=len(df)) < f["fracao_leitura_invalida"]
        if invalida.any():
            colunas = rng.choice(["temp_media_c", "tensao_media_v", "corrente_media_a"], int(invalida.sum()))
            valores = {"temp_media_c": -40.0, "tensao_media_v": 0.0, "corrente_media_a": -1.0}
            for i, col in zip(np.flatnonzero(invalida), colunas):
                df.iat[i, df.columns.get_loc(col)] = valores[col]
        # nunca some a linha do dia da falha: o rótulo depende dela (a telegestão registra o evento)
        ausente = (rng.uniform(size=len(df)) < f["fracao_ausente"]) & (df["falha"].to_numpy() == 0)
        return df[~ausente].reset_index(drop=True)

    def simular(self, dias: int) -> pd.DataFrame:
        return pd.concat([self.passo() for _ in range(dias)], ignore_index=True)


# ---------------- calibração ----------------
def _medir_por_mes(premissas: dict, escala: dict) -> pd.DataFrame:
    parque = Parque(premissas, escala)
    linhas = []
    for _ in range(premissas["dias_historico"]):
        r = parque.passo(registrar=False)
        linhas.append((r["mes"], r["falhas"], r["operando"], r["por_tipo"]["fim_de_vida"]))
    return pd.DataFrame(linhas, columns=["mes", "falhas", "operando", "fim_vida"]).groupby("mes").sum()


def calibrar(premissas: dict, iteracoes: int = 6, luminarias: int = 5000) -> tuple[dict, dict]:
    """Acha, para cada mês do ano, a escala do risco do driver que faz a taxa de falha simulada bater
    com a da Emlurb naquele mês (taxa média x sazonalidade). Roda num parque maior que o gerado
    (5.000 luminárias) para o ruído do sorteio não atrapalhar, e amortece cada ajuste (expoente 0,7)
    para a calibração não ficar perseguindo o ruído."""
    grande = copy.deepcopy(premissas)
    grande["luminarias"] = luminarias
    alvo = premissas["calibracao"]["taxa_falha_mensal_alvo"]
    sazonal = {int(m): v for m, v in premissas["calibracao"]["sazonalidade_mensal"].items()}
    externa_frac = premissas["falha_externa_fracao"]
    escala = {str(m): 8.0 for m in range(1, 13)}
    for _ in range(iteracoes):
        medido = _medir_por_mes(grande, escala)
        for m, linha in medido.iterrows():
            taxa = linha["falhas"] / linha["operando"] * 30
            fim_vida = linha["fim_vida"] / linha["operando"] * 30
            externa = externa_frac * alvo * sazonal[m]
            razao = max(alvo * sazonal[m] - externa - fim_vida, 1e-6) / max(taxa - externa - fim_vida, 1e-6)
            escala[str(m)] *= razao ** 0.7
    medido = _medir_por_mes(grande, escala)            # conferência depois do último ajuste
    taxa_mes = medido["falhas"] / medido["operando"] * 30
    esperado = (taxa_mes / taxa_mes.mean()).sort_index()
    real = pd.Series(sazonal).sort_index()
    resumo = {
        "escala_risco_driver_por_mes": {m: round(float(v), 3) for m, v in escala.items()},
        "taxa_alvo_mensal": alvo,
        "taxa_obtida_mensal_calibracao": round(float(medido["falhas"].sum() / medido["operando"].sum() * 30), 5),
        "fracao_fim_de_vida": round(float(medido["fim_vida"].sum() / medido["falhas"].sum()), 3),
        "correlacao_sazonalidade_calibracao": round(float(np.corrcoef(esperado, real)[0, 1]), 3),
        "luminarias_na_calibracao": luminarias,
    }
    return escala, resumo


def gerar_dados(alteracoes: dict | None = None, dias: int | None = None,
                escala: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame, "Parque", dict]:
    """Gera cadastro + telemetria diária sem tocar no banco (usado no treino e no teste de robustez).
    Com alterações, a escala do risco é a do cenário base: o mundo muda, a calibração não."""
    base = carregar_premissas()
    if escala is None:
        escala, info = calibrar(base)
    else:
        info = {"escala_risco_driver_por_mes": escala}
    premissas = carregar_premissas(alteracoes)
    parque = Parque(premissas, escala)
    telemetria = parque.simular(dias or premissas["dias_historico"])
    return parque.catalogo, telemetria, parque, info


def resumo_coerencia(telemetria: pd.DataFrame, premissas: dict) -> dict:
    """Compara a taxa mensal e a sazonalidade simuladas com as da Emlurb (verificação da seção g.7)."""
    t = telemetria.assign(mes=pd.to_datetime(telemetria["data"]).dt.month)
    operando = t[t["estado"] != "APAGADA"].groupby("mes").size() + t[t["falha"] == 1].groupby("mes").size().reindex(range(1, 13), fill_value=0)
    taxa_mes = t.groupby("mes")["falha"].sum() / operando * 30
    sazonal = (taxa_mes / taxa_mes.mean()).round(3)
    real = pd.Series({int(k): v for k, v in premissas["calibracao"]["sazonalidade_mensal"].items()})
    return {"taxa_mensal_simulada": round(float(t["falha"].sum() / operando.sum() * 30), 5),
            "taxa_mensal_emlurb": premissas["calibracao"]["taxa_falha_mensal_alvo"],
            "sazonalidade_simulada": sazonal.to_dict(), "sazonalidade_emlurb": real.to_dict(),
            "correlacao_sazonalidade": round(float(np.corrcoef(sazonal.sort_index(), real.sort_index())[0, 1]), 3),
            "falhas": int(t["falha"].sum()), "luminarias": int(t["id_luminaria"].nunique())}


# ---------------- comandos ----------------
def gerar(gravar_banco: bool = True) -> Parque:
    premissas = carregar_premissas()
    inicio = time.time()
    catalogo, telemetria, parque, info = gerar_dados()
    coerencia = resumo_coerencia(telemetria, premissas)
    print(f"Calibração: {info}")
    print(f"Histórico: {len(telemetria)} leituras de {len(catalogo)} luminárias, "
          f"{coerencia['falhas']} falhas; taxa mensal {coerencia['taxa_mensal_simulada']:.4f} "
          f"(Emlurb {coerencia['taxa_mensal_emlurb']}); correlação da sazonalidade {coerencia['correlacao_sazonalidade']}")
    PASTA_SIMULADO.mkdir(parents=True, exist_ok=True)
    ARQ_CALIBRACAO.write_text(json.dumps({"gerado_em": datetime.now().isoformat(timespec="seconds"),
                                          **info, **coerencia}, ensure_ascii=False, indent=2), encoding="utf-8")
    if gravar_banco:
        gravar(catalogo, "luminaria", substituir=True)
        gravar(telemetria.assign(origem="historico", recebido_em=None), "telemetria_luminaria", substituir=True)
        print(f"Gravado no banco (luminaria, telemetria_luminaria) em {time.time() - inicio:.0f} s")
    salvar_estado(parque)
    return parque


def salvar_estado(parque: Parque) -> None:
    ARQ_ESTADO.parent.mkdir(parents=True, exist_ok=True)
    temporario = ARQ_ESTADO.with_suffix(".tmp")
    temporario.write_bytes(pickle.dumps(parque))
    temporario.replace(ARQ_ESTADO)


def servir() -> None:
    from comum import MQTT_HOST, MQTT_PORT, novo_cliente  # só o modo ao vivo precisa do MQTT
    if not ARQ_ESTADO.exists() or contar("telemetria_luminaria") == 0:
        print("[PARQUE] sem histórico: gerando agora (leva alguns minutos na primeira vez)...", flush=True)
        parque = gerar()
    else:
        parque = pickle.loads(ARQ_ESTADO.read_bytes())
    intervalo = float(os.getenv("PARQUE_DIA_S", "30"))
    cliente = novo_cliente("parque")
    cliente.reconnect_delay_set(min_delay=1, max_delay=10)
    cliente.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
    cliente.loop_start()
    print(f"[PARQUE] {len(parque.catalogo)} luminárias a partir de {parque.dia}; um dia simulado a cada "
          f"{intervalo:.0f} s em {MQTT_HOST}:{MQTT_PORT}", flush=True)
    while True:
        inicio = time.time()
        df = parque.passo()
        for linha in df.to_dict("records"):
            linha = {k: (v.item() if hasattr(v, "item") else v) for k, v in linha.items()}
            cliente.publish(f"g17/luminaria/{linha['id_luminaria']}/telemetria",
                            json.dumps(linha, ensure_ascii=False), qos=0)
        salvar_estado(parque)
        falhas = int(df["falha"].sum())
        print(f"[PARQUE] {df['data'].iloc[0]}: {len(df)} leituras, {falhas} falha(s), "
              f"{int((df['estado'] == 'CINTILANDO').sum())} cintilando, {int((df['estado'] == 'APAGADA').sum())} apagadas",
              flush=True)
        time.sleep(max(0.0, intervalo - (time.time() - inicio)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulador do parque de luminárias com degradação")
    sub = parser.add_subparsers(dest="modo", required=True)
    g = sub.add_parser("gerar", help="calibra com a Emlurb, gera o histórico e grava no banco")
    g.add_argument("--sem-banco", action="store_true", help="só gera e mostra o resumo")
    sub.add_parser("servir", help="continua a simulação ao vivo e publica no MQTT")
    args = parser.parse_args()
    if args.modo == "gerar":
        gerar(gravar_banco=not args.sem_banco)
    else:
        servir()


if __name__ == "__main__":
    # Roda pelo módulo importado: o estado salvo (pickle) fica como "parque.Parque", e não "__main__.Parque"
    import parque as modulo
    modulo.main()
