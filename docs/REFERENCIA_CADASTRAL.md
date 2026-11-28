# Referência cadastral do P01 — T20 / ML-07

Concluída em 27/11/2026 por Luiz Claudio. O P01 usa o `id_ponto` **264213064**, de
Boa Viagem, RPA 6, LED de 70 W, no cadastro público da EMLURB de 2025.
Esse vínculo é **demonstrativo**: a maquete com ESP32 não está instalada no poste
cadastrado. O risco publicado continua sendo o índice relativo do bairro, sem
representar probabilidade de falha dessa luminária individual.

## Fonte e seleção

- [Recurso oficial — Iluminação Pública do Recife 2025](https://dados.recife.pe.gov.br/dataset/postes-iluminacao-publica-do-recife/resource/76cb7e65-1362-4ea7-ac04-453d67e41c64).
- [CSV oficial](https://dados.recife.pe.gov.br/dataset/cb834849-e07e-43a1-a101-204b599aaebb/resource/76cb7e65-1362-4ea7-ac04-453d67e41c64/download/iluminacao-publica-do-recife-2025.csv), consultado em 27/11/2026; licença ODbL.
- SHA-256 dos bytes baixados: `68281c9f2a168155a1b16c26541a73013ca6575998b40dfd8b74530034de9abf`.
- 111.666 registros totais; 7.013 em Boa Viagem; 4.365 candidatos com ID numérico
  positivo e ocorrência única em todo o cadastro. Foi escolhido o menor ID numérico.
- Recorte verificável: `applications/ml/data/processed/referencia_p01.json`.
  Guarda origem, critério, contagens e atributos necessários, sem endereço ou coordenadas.

O CSV bruto permanece ignorado pelo Git. Para reproduzir, baixe o CSV para
`applications/ml/data/raw/postes/iluminacao-publica-do-recife-2025.csv` e execute,
na raiz do repositório:

```bash
python applications/ml/src/referencia_cadastro.py
```

O script gera novamente o recorte; não altera automaticamente a configuração. Se o
portal atualizar o recurso, confira o hash e revise a seleção antes de alterar o P01.
P02–P10 permanecem virtuais, com `id_ponto: null`.

## Contratos e validação

`GET /poste/P01` e o risco MQTT `g17/poste/P01/risco` incluem:

```json
{"id_ponto": "264213064", "vinculo_cadastro": "referencia_demonstrativa"}
```

O mesmo identificador é preservado quando `publicar_risco.py` usa o CSV de risco
como alternativa à API indisponível. Os tópicos continuam usando P01–P10; comandos
continuam contendo apenas `potencia`. O dashboard exibe o ID com a indicação de
referência demonstrativa. Nenhuma alteração de firmware é necessária.

A seleção foi reproduzida sobre o CSV oficial completo e conferida contra o recorte
e a configuração. Testes automáticos cobrem IDs inválidos e duplicados, seleção
independente da ordem, hash do CSV, API, alternativa por arquivo e publicação MQTT
com/sem comandos. Usam dados pequenos e cliente MQTT substituto, sem rede ou placa.

Validação local: **62 testes aprovados**, incluindo 10 casos novos para a T20;
JavaScript do dashboard com sintaxe validada. Nenhum teste com a placa foi executado.
