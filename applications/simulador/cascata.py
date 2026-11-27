"""
Cascata em Y simulada: o poste P01 da maquete, com a mesma lógica do firmware v3.0.

Calibrado com o que a placa mediu em 26/11 (docs/CONTEXTO_PARA_IA.md, seção 8):
- pedestre a menos de 10 cm do sensor; parado, o S1 vê algo a ~52-63 cm (ou nada, 999) e o
  S2 vê um objeto a ~16-18 cm;
- travessia para a esquerda: o S2 confirma 1,3 a 3,1 s depois da entrada;
- travessia para a direita: confirmada por exclusão, aos 4 s (janela do firmware).

O sinal que o modelo de rota pode aprender é o LADO DA RUA em que o pedestre passa pelo S1:
perto do sensor (2-5 cm) ele tende a seguir para a direita, longe (5,5-10 cm) para a esquerda.
SIM_CONSISTENCIA (padrão 0,85) é a chance de o pedestre seguir esse padrão; com 0,5 o caminho é
aleatório e nenhum modelo consegue prever (bom para mostrar o limite do ML).

Também é usado pelo prever_rota.py para gerar travessias sintéticas no mesmo formato.
"""

import json
import os
import random
import threading
import time

PRE_PCT = 85            # braços pré-acesos enquanto o caminho não é conhecido
JANELA_ROTA_S = 4.0     # sem S2 nessa janela = direita
TEMPO_BRACO_S = 2.5     # braço confirmado fica a 100%
PISO_PCT = 70
CONSISTENCIA = float(os.getenv("SIM_CONSISTENCIA", "0.85"))
INTERVALO_PEDESTRE_S = float(os.getenv("SIM_PEDESTRE_S", "12"))   # média entre pedestres


def sortear_pedestre(rng: random.Random, consistencia: float = CONSISTENCIA) -> dict:
    """Um pedestre: em que lado da rua passa pelo S1, para onde vai e quando chega ao S2."""
    perto = rng.random() < 0.5
    dist_s1 = round(rng.uniform(2.3, 4.8) if perto else rng.uniform(5.5, 9.8), 1)
    lado_do_padrao = "direita" if perto else "esquerda"
    if rng.random() < consistencia:
        real = lado_do_padrao
    else:
        real = "esquerda" if lado_do_padrao == "direita" else "direita"
    return {"dist_s1": dist_s1, "real": real, "t_s2": rng.uniform(1.3, 3.1)}


class CascataY:
    """Estado da cascata do P01. O simulador chama tick() várias vezes por segundo."""

    def __init__(self, poste_id: str, publicar, rng: random.Random | None = None):
        self.id = poste_id
        self.publicar = publicar          # publicar(tipo, dicionario)
        self.rng = rng or random.Random()
        self.inicio = time.time()
        self.trava = threading.Lock()
        self.travessia = None
        self.proximo = time.time() + self.rng.expovariate(1 / INTERVALO_PEDESTRE_S)
        self.s1_ate = 0.0
        self.s2_ate = 0.0
        self.dist_s1_atual = 999.0

    def uptime(self) -> int:
        return int(time.time() - self.inicio)

    def receber_rota(self, texto: str) -> None:
        """Previsão do modelo ({"direcao": ..., "confianca": ...}), igual ao firmware."""
        try:
            dados = json.loads(texto)
            lado, confianca = dados.get("direcao"), float(dados.get("confianca", 1))
        except (ValueError, AttributeError, TypeError):
            return
        if lado not in ("esquerda", "direita") or confianca < 0.5:
            return
        with self.trava:
            t = self.travessia
            if t and not t["confirmada"]:
                t["previsto"], t["fonte"] = lado, "modelo"

    def tick(self) -> None:
        agora = time.time()
        with self.trava:
            t = self.travessia
            if t is None or t["confirmada"]:
                if agora >= self.proximo:
                    self._nova_entrada(agora)
                    t = self.travessia
            if t and not t["confirmada"]:
                passou = agora - t["inicio"]
                if t["real"] == "esquerda" and passou >= t["t_s2"]:
                    self.s2_ate = agora + self.rng.uniform(0.6, 1.0)
                    self._confirmar(agora, "esquerda")
                elif passou >= JANELA_ROTA_S:
                    self._confirmar(agora, "direita")
            if t and t["confirmada"] and agora - t["confirmada_em"] > TEMPO_BRACO_S:
                self.travessia = None

    def _nova_entrada(self, agora: float) -> None:
        p = sortear_pedestre(self.rng)
        self.travessia = {"inicio": agora, "previsto": "nenhuma", "fonte": "sem_previsao",
                          "confirmada": False, "confirmada_em": 0.0, **p}
        self.s1_ate = agora + self.rng.uniform(0.6, 1.2)
        self.dist_s1_atual = p["dist_s1"]
        self.proximo = agora + self.rng.expovariate(1 / INTERVALO_PEDESTRE_S) + JANELA_ROTA_S + TEMPO_BRACO_S
        self.publicar("evento", {"id": self.id, "tipo": "entrada", "dist_s1": p["dist_s1"],
                                 "uptime": self.uptime(), "origem": "simulador"})

    def _confirmar(self, agora: float, real: str) -> None:
        t = self.travessia
        t["confirmada"], t["confirmada_em"], t["real_confirmado"] = True, agora, real
        acertou = -1 if t["previsto"] == "nenhuma" else int(t["previsto"] == real)
        self.publicar("travessia", {
            "id": self.id, "dist_s1": t["dist_s1"], "previsto": t["previsto"], "fonte": t["fonte"],
            "real": real, "acertou": acertou, "duracao_ms": int((agora - t["inicio"]) * 1000),
            "uptime": self.uptime(), "origem": "simulador",
        })

    def estado(self, noite: bool, piso: int) -> dict:
        """Campos da cascata para a telemetria, com a mesma regra de brilho do firmware."""
        agora = time.time()
        with self.trava:
            presenca1 = agora < self.s1_ate
            presenca2 = agora < self.s2_ate
            t = self.travessia
            braco, fonte, pre = "nenhuma", "", False
            if t:
                if t["confirmada"]:
                    braco, fonte = t["real_confirmado"], "confirmada"
                elif t["previsto"] != "nenhuma":
                    braco, fonte = t["previsto"], t["fonte"]
                else:
                    pre, fonte = True, "aguardando"
        if not noite:
            base = esq = dir_ = 0
        else:
            p = max(PRE_PCT, piso)
            base = 100 if presenca1 else piso
            esq = 100 if (braco == "esquerda" or presenca2) else (p if pre else piso)
            dir_ = 100 if braco == "direita" else (p if pre else piso)
        return {
            "dist": self.dist_s1_atual if presenca1 else self.rng.choice([999, round(self.rng.uniform(52, 63))]),
            "presenca": int(presenca1),
            "dist_s2": round(self.rng.uniform(2, 6)) if presenca2 else round(self.rng.uniform(16, 18)),
            "presenca_s2": int(presenca2),
            "pct_base": base, "pct_esq": esq, "pct_dir": dir_,
            "rota": braco, "rota_fonte": fonte,
            "pedestre": presenca1 or presenca2 or t is not None,
        }
