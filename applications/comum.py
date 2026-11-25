"""Configuração compartilhada pelos scripts Python da central (coletor, simulador, ML).

Tudo vem de variáveis de ambiente, para o mesmo código rodar no PC, no Docker e
com o broker público ou o Mosquitto local, sem editar arquivo:

    MQTT_HOST    endereço do broker (padrão: localhost; aceita IPv6, ex.: ::1)
    MQTT_PORT    porta MQTT (padrão: 1883)
    MQTT_PREFIXO prefixo dos tópicos (padrão: g17/poste)
"""

import os
import uuid

import paho.mqtt.client as mqtt

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_PREFIXO = os.getenv("MQTT_PREFIXO", "g17/poste").rstrip("/")


def topico(poste_id: str, tipo: str) -> str:
    """Monta o tópico do contrato MQTT: g17/poste/<ID>/<tipo>."""
    return f"{MQTT_PREFIXO}/{poste_id}/{tipo}"


def novo_cliente(nome: str) -> mqtt.Client:
    """Cliente paho-mqtt (API v2) com um client id único, para dois processos
    iguais não derrubarem um ao outro no broker."""
    return mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"g17-{nome}-{uuid.uuid4().hex[:6]}",
    )
