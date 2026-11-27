"""
Simulador de postes virtuais (P02 em diante), no mesmo contrato MQTT do poste físico P01.

Cada poste virtual:
- publica telemetria a cada 5 s em g17/poste/<ID>/telemetria, com os mesmos campos do ESP32;
- publica "online" (retido) ao conectar e deixa "offline" como LWT;
- obedece g17/poste/<ID>/comando ({"potencia": N} ou só N), como o firmware;
- segue a mesma lógica do firmware: dia = 0%, pedestre = 100%, senão max(pedido, 70)%,
  e FALHA quando o desgaste passa de 0,70.

O dia é acelerado: um ciclo dia/noite inteiro dura SIM_CICLO_MIN minutos (padrão 6),
para a demonstração mostrar o anoitecer em poucos minutos. O poste P02 tem o desgaste
acelerado e entra em FALHA em poucos minutos, para mostrar o alerta.

O poste P06 (SIM_DEFEITO_LUZ) tem um defeito que as regras do firmware não pegam: em 1 de cada 3
dias simulados, o sensor de luz trava numa leitura baixa. O poste acha que é noite o dia inteiro e
fica aceso de dia, sem mudar de estado. Quem percebe é o detector de anomalias
(applications/ml/src/anomalia_telemetria.py).

Sem a maquete por perto (trabalhando de casa), SIM_INCLUIR_P01=1 simula também o P01, para o
dashboard e o ML terem o poste da maquete. O P01 simulado tem a cascata em Y do firmware v3.0
(3 postes, S1, S2, eventos de entrada, travessias e obediência ao tópico .../rota do modelo),
ver cascata.py. Não use com a placa ligada no mesmo broker: os dois publicariam como P01.

Uso:
    python applications/simulador/simulador.py
    (variáveis: MQTT_HOST, MQTT_PORT, SIM_POSTES (padrão 9 -> P02..P10), SIM_CICLO_MIN,
     SIM_INCLUIR_P01 (padrão 0), SIM_CONSISTENCIA (padrão 0.85), SIM_PEDESTRE_S (padrão 12),
     SIM_DEFEITO_LUZ (padrão P06; vazio = nenhum poste com o sensor de luz travando))
"""

import json
import math
import os
import random
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cascata import CascataY  # noqa: E402
from comum import MQTT_HOST, MQTT_PORT, novo_cliente, topico  # noqa: E402

QTD_POSTES = int(os.getenv("SIM_POSTES", "9"))
INCLUIR_P01 = os.getenv("SIM_INCLUIR_P01", "0") == "1"
CICLO_S = float(os.getenv("SIM_CICLO_MIN", "6")) * 60
INTERVALO_S = 5
DEFEITO_LUZ = {p.strip() for p in os.getenv("SIM_DEFEITO_LUZ", "P06").split(",") if p.strip()}
LUZ_TRAVADA = 180   # leitura em que o sensor defeituoso trava (parece noite)

# Mesmos parâmetros do firmware (placa física), ver docs/CONTEXTO_PARA_IA.md seção 8
LIMIAR_NOITE = 2500
LIMIAR_DIA = 2700
PISO_PCT = 70
LIMIAR_DESGASTE = 0.70
PEDIDO_INICIAL = 40


class PosteVirtual:
    def __init__(self, numero: int):
        self.id = f"P{numero:02d}"
        self.inicio = time.time()
        self.fase = random.uniform(-0.03, 0.03)       # postes não anoitecem no mesmo segundo
        self.base_luz = random.uniform(3000, 3500)    # quanto de luz o sensor vê de dia
        self.noite = False
        self.pedido = PEDIDO_INICIAL
        self.desgaste = random.uniform(0.05, 0.45)
        # P02 envelhece rápido para a demo mostrar a FALHA e o alerta em poucos minutos
        self.ritmo_desgaste = 0.008 if numero == 2 else random.uniform(0.0002, 0.001)
        self.presenca_ate = 0.0

        self.cliente = novo_cliente(f"sim-{self.id}")
        self.cliente.will_set(topico(self.id, "status"), "offline", qos=1, retain=True)
        self.cliente.on_connect = self.ao_conectar
        self.cliente.on_message = self.ao_receber
        self.cliente.reconnect_delay_set(min_delay=1, max_delay=10)

    def conectar(self) -> None:
        self.cliente.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        self.cliente.loop_start()

    def ao_conectar(self, cliente, _userdata, _flags, codigo, _props):
        if codigo.is_failure:
            return
        cliente.publish(topico(self.id, "status"), "online", qos=1, retain=True)
        cliente.subscribe(topico(self.id, "comando"), qos=1)

    def ao_receber(self, _cliente, _userdata, msg):
        texto = msg.payload.decode("utf-8", "replace").strip()
        try:
            valor = json.loads(texto)
            valor = valor["potencia"] if isinstance(valor, dict) else valor
            valor = int(valor)
        except (ValueError, KeyError, TypeError):
            print(f"[{self.id}] comando ignorado: {texto}", flush=True)
            return
        if 0 <= valor <= 100:
            self.pedido = valor
            print(f"[{self.id}] comando recebido: potência {valor}%", flush=True)

    def sensor_travado(self, agora: float) -> bool:
        """Defeito do SIM_DEFEITO_LUZ: o sensor trava no 3º de cada 3 dias simulados."""
        return self.id in DEFEITO_LUZ and int((agora - self.inicio) / CICLO_S) % 3 == 2

    def ler_luz(self, agora: float) -> int:
        if self.sensor_travado(agora):
            return LUZ_TRAVADA
        # Senoide do dia simulado: meio-dia = máximo, meia-noite = mínimo
        fracao = ((agora - self.inicio) / CICLO_S + 0.25 + self.fase) % 1.0
        sol = max(0.0, math.sin(2 * math.pi * (fracao - 0.25) + math.pi / 2))
        luz = 300 + (self.base_luz - 300) * sol + random.gauss(0, 60)
        return int(min(4095, max(0, luz)))

    def passo(self) -> dict:
        agora = time.time()
        luz = self.ler_luz(agora)
        # Histerese igual à do firmware
        if self.noite and luz > LIMIAR_DIA:
            self.noite = False
        elif not self.noite and luz < LIMIAR_NOITE:
            self.noite = True

        if self.noite and random.random() < 0.15:
            self.presenca_ate = agora + random.uniform(2, 6)
        presenca = agora < self.presenca_ate
        dist = round(random.uniform(2, 4.5), 0) if presenca else 999

        self.desgaste = min(1.0, self.desgaste + self.ritmo_desgaste * random.uniform(0.5, 1.5))
        if self.desgaste >= 0.98:
            self.desgaste = random.uniform(0.05, 0.15)  # a equipe trocou a lâmpada

        if not self.noite:
            pct, estado = 0, "DIA"
        elif presenca:
            pct, estado = 100, "PEDESTRE"
        else:
            pct = max(self.pedido, PISO_PCT)
            estado = "DIMERIZADO" if pct < 100 else "NOITE"
        if self.desgaste > LIMIAR_DESGASTE:
            estado = "FALHA"

        return {
            "id": self.id, "luz": luz, "noite": int(self.noite), "dist": dist,
            "presenca": int(presenca), "desgaste": round(self.desgaste, 2), "pct": pct,
            "estado": estado, "pedido": self.pedido, "uptime": int(agora - self.inicio),
        }

    def publicar(self) -> dict:
        dados = self.passo()
        self.cliente.publish(topico(self.id, "telemetria"), json.dumps(dados, separators=(",", ":")), qos=0)
        return dados

    def desligar(self) -> None:
        self.cliente.publish(topico(self.id, "status"), "offline", qos=1, retain=True).wait_for_publish(2)
        self.cliente.loop_stop()
        self.cliente.disconnect()


class PosteMaquete(PosteVirtual):
    """O P01 da maquete: poste simples + cascata em Y (3 postes, S1, S2), como o firmware v3.0."""

    def __init__(self, numero: int):
        super().__init__(numero)
        self.ritmo_desgaste = 0.0005            # a maquete não deve cair em FALHA durante a coleta
        self.desgaste = 0.31                    # valor medido no potenciômetro em 26/11
        self.cascata = CascataY(self.id, self.publicar_cascata)
        threading.Thread(target=self.rodar_cascata, daemon=True).start()

    def publicar_cascata(self, tipo: str, dados: dict) -> None:
        self.cliente.publish(topico(self.id, tipo), json.dumps(dados, separators=(",", ":")), qos=1)
        if tipo == "travessia":
            print(f"[{self.id}] travessia: {dados['real']:<8} (dist_s1 {dados['dist_s1']} cm, "
                  f"previsto {dados['previsto']}, fonte {dados['fonte']})", flush=True)

    def rodar_cascata(self) -> None:
        while True:
            self.cascata.tick()
            time.sleep(0.05)

    def ao_conectar(self, cliente, userdata, flags, codigo, props):
        super().ao_conectar(cliente, userdata, flags, codigo, props)
        if not codigo.is_failure:
            cliente.subscribe(topico(self.id, "rota"), qos=1)

    def ao_receber(self, cliente, userdata, msg):
        if msg.topic.endswith("/rota"):
            self.cascata.receber_rota(msg.payload.decode("utf-8", "replace"))
        else:
            super().ao_receber(cliente, userdata, msg)

    def passo(self) -> dict:
        dados = super().passo()
        piso = max(self.pedido, PISO_PCT)
        c = self.cascata.estado(bool(dados["noite"]), piso)
        dados.update({k: c[k] for k in ("dist", "presenca")})
        dados["pct"] = c["pct_base"]
        if dados["noite"] and dados["estado"] != "FALHA":
            dados["estado"] = "PEDESTRE" if c["pedestre"] else ("DIMERIZADO" if piso < 100 else "NOITE")
        dados.update({k: c[k] for k in ("dist_s2", "presenca_s2", "pct_base", "pct_esq", "pct_dir",
                                       "rota", "rota_fonte")})
        return dados


def main() -> None:
    postes = ([PosteMaquete(1)] if INCLUIR_P01 else []) + [PosteVirtual(n) for n in range(2, 2 + QTD_POSTES)]
    print(f"Simulando {len(postes)} postes ({postes[0].id} a {postes[-1].id}) em {MQTT_HOST}:{MQTT_PORT}; "
          f"um dia simulado = {CICLO_S / 60:.0f} min", flush=True)
    for p in postes:
        p.conectar()
    try:
        while True:
            inicio = time.time()
            resumo = [p.publicar() for p in postes]
            contagem = {}
            for d in resumo:
                contagem[d["estado"]] = contagem.get(d["estado"], 0) + 1
            print(f"[{time.strftime('%H:%M:%S')}] " + "  ".join(f"{k}={v}" for k, v in sorted(contagem.items())), flush=True)
            time.sleep(max(0.0, INTERVALO_S - (time.time() - inicio)))
    except KeyboardInterrupt:
        print("\nDesligando os postes virtuais...")
        for p in postes:
            p.desligar()


if __name__ == "__main__":
    main()
