# Premissas do simulador do parque de luminárias

> Documento exigido pela proposta (seção g.5 e item 06 do backlog). Descreve **cada regra e cada
> parâmetro** do simulador de telemetria e falha, com a origem de cada escolha. Os valores ficam em
> [`applications/simulador/premissas_parque.json`](../applications/simulador/premissas_parque.json)
> (versionado no Git) e o código em [`applications/simulador/parque.py`](../applications/simulador/parque.py).
>
> **Aviso que deve ir para o relatório:** o modelo de falha é treinado e avaliado sobre dados
> **simulados**. O desempenho medido não equivale ao comportamento real de degradação das luminárias
> do Recife; validar com dados reais é trabalho futuro (proposta, g.5 e g.7).

---

## 1. Por que simular, e qual o risco

O grupo não tem acesso a telemetria elétrica real das luminárias do Recife. A proposta decidiu
(g.7) treinar o modelo inteiramente com dados de um simulador. O risco é o modelo só "aprender de
volta" as regras escritas pelo grupo. Para controlar esse risco:

1. a falha **não é uma regra** sobre os atributos medidos: é **sorteada** com uma taxa que depende de
   mecanismos físicos de degradação;
2. a taxa depende também de **fatores latentes que o modelo não vê** (qualidade do lote, presença de
   DPS, dissipação de calor) e de **falhas externas** (vandalismo, cabos) que não dependem de nada;
3. toda medição tem **ruído**, e existem leituras ausentes e leituras impossíveis;
4. o modelo é avaliado em **cenários com premissas alteradas** (teste de robustez, seção 6).

## 2. O parque

| Premissa | Valor | Origem |
|---|---|---|
| Luminárias | 500, nos 10 bairros do `config.json` | Escolha do grupo (tamanho que treina em minutos) |
| Luminárias por bairro | Proporcional ao total real de postes de cada bairro, mínimo 15 | Cadastro de postes da Emlurb, 2025 (`postes_por_bairro.csv`) |
| Coordenadas | Pontos sorteados num raio em volta de um centro **aproximado** de cada bairro | Aproximação do grupo; os brutos com lat/long não estão no Git |
| Potência nominal | 60 W (40%), 100 W (40%), 150 W (20%) | Faixa típica de luminárias LED viárias; premissa |
| Classe de via (ABNT NBR 5101:2024, classes P) | P1 5%, P2 10%, P3 25%, P4 30%, P5 20%, P6 10% | Premissa (predomínio de vias locais) |
| Iluminância mínima por classe | P1 20, P2 15, P3 10, P4 7,5, P5 5, P6 3 lx | ABNT NBR 5101:2024, citada na proposta (g.6) |
| Iluminância de projeto | mínimo da classe × fator sorteado entre 1,15 e 2,0 | Premissa: projetos têm margem acima do mínimo |
| Histórico | 900 dias a partir de 01/01/2024 | Escolha do grupo (dá ~360 falhas para treinar e avaliar) |
| Aquecimento | 3 anos simulados antes do histórico, sem registrar | Para o parque começar em regime: sem isso, todas as luminárias começariam com pouco dano e a cintilação iria de 0% a 10% durante o histórico, criando uma diferença artificial entre treino e teste |

## 3. Telemetria diária (o que o modelo vê)

| Campo | Como é gerado |
|---|---|
| `temp_media_c`, `temp_max_c` | Temperatura do driver = temperatura noturna do Recife (25,5 °C, ±1,8 °C ao longo do ano, mais quente em fevereiro) + elevação de 28 °C × fator de dissipação da luminária (latente) × √(potência/100) × potência aplicada; ruído de medição de 1,5 °C |
| `tensao_media_v`, `tensao_min_v`, `tensao_max_v` | Rede de 220 V com ruído de 2,5 V; num dia com surto detectado, a máxima vai a 260-320 V |
| `surtos_dia` | Surtos detectados (90% dos surtos são detectados) |
| `corrente_media_a` | Potência aplicada ÷ tensão × (1 + 4% × dano do driver) + ruído de 1%; zero se apagada |
| `ripple_pct` | Ondulação da corrente: 3% + 30 × (dano − 0,3, se positivo) + 10 a 25 pontos se estiver cintilando + ruído |
| `horas_operacao`, `horas_acumuladas` | Duração da noite (12 h ± 0,35 h, noite mais longa em junho) |
| `ciclos_dia`, `ciclos_acumulados` | 1 acendimento por noite; cintilando, mais religamentos (Poisson, média 4) |
| `estado` | `OK`, `CINTILANDO` ou `APAGADA` |
| `falha` | 1 no dia em que a luminária falhou |

**Falhas de medição:** 0,5% das leituras não chegam (nunca a do dia da falha) e 0,2% chegam com um
valor impossível (temperatura −40 °C, tensão 0 V ou corrente negativa). O pipeline do Airflow
(`validar_dados`) trata esses casos.

## 4. Como a falha acontece (o que o modelo NÃO vê)

| Mecanismo | Regra | Origem |
|---|---|---|
| **Driver como modo de falha dominante** | Risco diário pela distribuição de **Weibull** (forma 2, desgaste) nas horas **efetivas** de uso | Premissa da proposta (g.5): falha do driver é o modo dominante |
| **Aceleração pela temperatura** | Horas efetivas = horas × fator de **Arrhenius**, com Ea = 0,7 eV e referência de 55 °C | Modelo do tipo Arrhenius pedido na g.5; 0,7 eV é um valor típico de confiabilidade de eletrônica (premissa) |
| **Surtos de tensão** | Surtos por dia ~ Poisson(0,01 × fator de chuva do mês: 0,5 a 1,7, mais em abril-julho); cada surto soma 0,03 a 0,20 de dano ao driver, 70% menos se a luminária tiver DPS (metade tem) | Efeito de surtos citado na g.5; época de chuva do Recife; premissa |
| **Dano e cintilação** | O dano também cresce com o calor (0,00008 × fator de Arrhenius por noite). Acima de 0,85 de dano, a luminária pode começar a **cintilar** (10% de chance por dia), e cintilando o risco de falha do driver fica **10 vezes** maior. Resultado: cerca de 10% do parque cintila num dia qualquer e quase metade das falhas vem depois de cintilação. (Uma primeira versão, com limiar de 0,55 e risco 3×, deixava metade do parque cintilando; foi corrigida em 26/11.) | g.5: cintilação como estado que antecede a falha; problema mais relatado na pesquisa (10 de 12) |
| **Fim de vida (L70)** | Fluxo = exp(−α × horas efetivas), com L70 = 50.000 h: abaixo de 70% do fluxo, a luminária é trocada | IES LM-80 / TM-21 (citados na proposta); 50.000 h é um valor comum de L70 para LED viário |
| **Fatores latentes** | Qualidade do lote (log-normal, σ = 0,6), dissipação (σ = 0,15) e DPS, sorteados por luminária e de novo a cada troca | g.5: fatores latentes não observados |
| **Falhas externas** | 15% da taxa total, iguais para todas as luminárias | Vandalismo, furto de cabo, acidente; premissa |
| **Reparo** | Após a falha, a luminária fica apagada de 2 a 10 dias e volta nova (idade, dano e latentes zerados) | Premissa |

## 5. Calibração com os dados reais da Emlurb (seção g.7)

A proposta prevê usar dados reais só para conferir se o simulador é coerente (taxa de falha e
sazonalidade). Os chamados de lâmpada apagada da Central 156 (2022-2025) dão:

- **taxa média: 2,39% dos postes por mês** (chamados do mês ÷ 111.665 postes do cadastro);
- **sazonalidade:** pico em julho (+18%) e agosto (+15%), baixa em novembro (−15%) e dezembro (−19%).

`parque.py` ajusta, para cada mês do ano, a escala do risco do driver até a taxa simulada bater com
a da Emlurb naquele mês. A calibração roda num parque de 5.000 luminárias, com 6 rodadas de ajuste amortecido, para o ruído
do sorteio não atrapalhar. O resultado fica em `applications/ml/data/simulado/calibracao.json`:

| Conferência | Resultado (geração de 26/11) |
|---|---|
| Taxa mensal simulada (histórico de 500 luminárias) | 2,46% (Emlurb: 2,39%) |
| Correlação da sazonalidade simulada com a da Emlurb, no parque de calibração (5.000 luminárias) | 0,74 |
| A mesma correlação no histórico de 500 luminárias | 0,53 (menor por causa do sorteio: ~12 falhas por mês) |
| Falhas no histórico | 366 |
| Fração das falhas por fim de vida (L70) | 1,6% (o aquecimento de 3 anos já trocou as luminárias mais velhas) |
| Luminárias cintilando num dia qualquer | ~10%, estável ao longo do histórico |

**Limitação:** um chamado de lâmpada apagada não é exatamente uma falha de luminária (pode haver
chamados repetidos, ou falhas sem chamado). A taxa da Emlurb é uma referência de ordem de grandeza.

## 6. Teste de robustez (g.5)

`treinar_falha.py` avalia o modelo treinado em parques gerados com premissas alteradas, com a mesma
calibração do cenário base (o mundo muda, o modelo não sabe):

| Cenário | Alteração |
|---|---|
| `noites_mais_quentes_+3C` | temperatura noturna de 25,5 para 28,5 °C |
| `surtos_em_dobro` | taxa de surtos de 0,01 para 0,02 por dia |
| `lote_mais_irregular` | dispersão da qualidade do lote de 0,6 para 0,9 |

Os resultados ficam em `models/metadados_falha.json` (chave `robustez`), no MLflow e no painel do
gestor (aba "Modelo de falha").

## 7. O que o grupo deve revisar

- Fontes das premissas marcadas como "premissa": se acharem referência melhor, troquem o valor no
  JSON e citem aqui.
- Os centros dos bairros (coordenadas aproximadas).
- Se a forma de Weibull (2) e o multiplicador da cintilação (10×) fazem sentido para o relatório.
