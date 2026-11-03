# Esquemáticos

- O circuito simulado está em [`esp32-esp8266/poste_g17/diagram.json`](../esp32-esp8266/poste_g17/diagram.json) e pode ser aberto no Wokwi.
- O mapa de pinos está no [README principal](../README.md#mapa-de-pinos-esp32-devkit).
- Fotos da montagem física e o esquemático serão adicionados aqui.

Na placa física (DevKit V1, 30 pinos), siga os **números dos GPIOs**, não a posição dos fios do Wokwi (DevKit C).
### Sensor de luz: simulação × placa física

O Wokwi só oferece o **módulo de 4 pinos** (`wokwi-photoresistor-sensor`). Por dentro, ele é um LDR em
série com um resistor de 10 kΩ, ou seja, o mesmo circuito montado na placa física:

```
3V3 ──── [ sensor de luz, 2 pernas ] ────┬──── [ 10 kΩ ] ──── GND
                                          │
                                       GPIO34
```

No físico, mais luz = número maior (`LDR_INVERTIDO = false`). No módulo do Wokwi, mais luz = número
menor (`LDR_INVERTIDO = true`). O firmware escolhe o sentido certo pela chave `SIMULACAO`.
