# ML: risco de falha por bairro

Prepara a base que cruza o cadastro de postes da Emlurb com os chamados de "lâmpada apagada"
da Central 156, para treinar o modelo de risco descrito no [`MACHINE_LEARNING.md`](../../MACHINE_LEARNING.md)
da raiz. Este README documenta o que já foi decidido e verificado nos dados reais, para o grupo
inteiro acompanhar sem precisar reabrir os CSVs.

---

## 1. Dados usados

| Fonte | Arquivo baixado | Período | Onde fica |
|---|---|---|---|
| Cadastro de postes (Emlurb) | `iluminacao-publica-do-recife-2025.csv` | só 2025 | `data/raw/postes/` |
| Chamados Central 156 (Emlurb) | `2022-2025-central-de-atendimento-de-servicos-da-emlurb-156.csv` | 2022 a 2025 | `data/raw/central156/` |
| Dicionário de dados do 156 | `.pdf` e `.json` | — | `data/raw/central156/` |

Baixados do [portal de dados abertos do Recife](https://dados.recife.pe.gov.br) (licença ODbL),
via API do CKAN (`/api/3/action/package_show?id=...`), que dá o link direto de cada recurso sem
precisar raspar a página. **Esses CSVs não estão no Git** (`applications/ml/data/raw/` está no
`.gitignore` da raiz) — rode o script da seção 4 para gerar os dados de novo, ou peça a quem já
baixou.

**Por que só 2025 do cadastro de postes:** as colunas que usamos (bairro, RPA, tipo de lâmpada,
potência) mudam pouco de ano para ano. Os 4 anos de chamados, por outro lado, são necessários
porque é de lá que vem o rótulo de falha, e o plano pede separar treino (passado) de teste
(futuro).

---

## 2. O dicionário de dados está desatualizado — e o que descobrimos no lugar

O `dicionario-de-dados-central-156.json` só documenta 11 colunas, todas de 2012-2014. Comparando
com os CSVs reais:

- **`latitude` e `longitude` existem no CSV e não estão no dicionário**, nos 4 anos. Mas só
  **35,9% dos chamados de iluminação de 2025** vêm com essas colunas preenchidas — não dá para
  usar como fonte principal de geolocalização.
- **`BAIRRO` está 100% preenchido** em todos os anos, e **nunca tem acento** (nem nos chamados,
  nem é bug — é assim que a Emlurb grava esse campo desde sempre). Por isso o cruzamento das
  duas bases é **por bairro**, não por coordenada nem endereço.

### A armadilha: a Emlurb trocou a tabela de códigos de serviço em 2024
Em 2022 e 2023, as colunas de texto `GRUPOSERVICO_DESCRICAO` e `SERVICO_DESCRICAO` vêm com a
acentuação corrompida na fonte (ex.: `"ILUMINA??O P?BLICA"` em 2022, `"ILUMINAO PBLICA"` em 2023 —
as letras acentuadas somem). Filtrar por essas strings dava **zero linhas** em 2022/2023. O
problema não é só de acentuação: **os códigos numéricos também mudaram**:

| Período | `GRUPOSERVICO_CODIGO` | `SERVICO_CODIGO` | Descrição (quando legível) |
|---|---|---|---|
| 2022–2023 | `17` | `25` | "manutenção em lâmpada apagada" |
| 2024–2025 | `4` | `55` | `MANUTENCAO EM LAMPADA APAGADA` |

Confirmamos que os códigos antigos (`17`/`25`) não aparecem nenhuma vez em 2024/2025 e vice-versa,
então o script filtra pelos dois pares de código ao mesmo tempo, sem risco de misturar com outro
serviço. **Lição para quem for mexer nisso:** nunca confiar só no texto descritivo ao combinar
anos diferentes de um dataset da prefeitura — sempre conferir se os códigos batem.

### Outros problemas de qualidade encontrados e corrigidos
- **1 linha do cadastro de postes (em 111.666) vem com os campos desalinhados na fonte**: o valor
  de longitude aparece também no campo `bairro`. Essa linha é descartada (nenhum bairro de
  verdade tem dígito no nome, então o filtro é simples).
- **~7.100 postes (6,4% do total) não têm `id_ponto`**, mas têm bairro, tipo de lâmpada e potência
  preenchidos normalmente — são postes de verdade, só sem ID atribuído ainda no cadastro. Contar
  postes por `id_ponto.count()` subestimava o total em todos os bairros com esse problema; o
  script conta pelo tamanho do grupo, não pela coluna `id_ponto`.
- **O mesmo bairro aparece com grafias diferentes no cadastro de postes** (Title Case numa linha,
  CAIXA ALTA noutra — ex.: `"Boa Viagem"` e `"BOA VIAGEM"`). Isso por si só derrubou a contagem de
  154 bairros "brutos" para 97 depois de normalizar por acento/caixa/espaço.
- **3 bairros do cadastro têm erro de digitação** que a normalização de acento/caixa não resolve,
  porque são letras diferentes, não só formatação: `CIDADDE UNIVERSITARIA` (1 poste) vs. `CIDADE
  UNIVERSITARIA` (217 postes), `IMBIRBEIRA` (8 postes) vs. `IMBIRIBEIRA` (4.491 postes), `TEJIIPIO`
  (2 postes) vs. `TEJIPIO` (665 postes). Sem corrigir, cada um vira um "bairro" fantasma com **zero
  chamados em todos os 47 meses** — não porque seja seguro, mas porque a grafia errada nunca bate
  com os chamados de verdade. `CORRECOES_BAIRRO` no `preparar_dados.py` funde os três pares
  (deixando **94 bairros reais**, não 97).
- **`BAIRRO NAO INFORMADO`** não é um bairro — é o valor que a Central 156 grava quando o
  atendente não registrou o bairro (54 chamados em 4 anos, só em 2024, de ~130 mil). Fica fora do
  painel por bairro em vez de virar uma categoria.
- **Colunas `consumo_kw` e `consumo_1` do cadastro de postes não fazem sentido** (ficam na casa de
  petawatt-hora para uma única luminária — claramente um artefato de exportação). Não são usadas
  aqui nem devem ser usadas sem recalcular a partir de `potencia`.

---

## 3. Normalização e cruzamento

Função `normalizar_bairro()` em `src/preparar_dados.py`: remove acento, deixa em CAIXA ALTA,
colapsa espaços duplicados e tira espaço nas pontas. Aplicada dos dois lados (cadastro de postes
e chamados) antes do `merge`.

Depois de normalizar (e corrigir os 3 erros de digitação acima): **97 bairros distintos** nos
chamados de lâmpada apagada, **94** no cadastro de postes, com **3 bairros nos chamados sem poste
cadastrado correspondente**: `ALTO DO MANDU SITIO GRANDE`, `COHAB IBURA DE CIMA`, `SITIO DOS PINTOS
SAO BRAS` — nomes "compostos" que não bati com nenhuma grafia do cadastro. Esses 3 (144 linhas do
painel) são **descartados** antes de treinar, porque não têm nenhuma feature de poste (ficariam
`NaN` em tudo) — não dá pra reconciliar automaticamente sem decisão manual, e o volume é pequeno
perto do total.

---

## 4. Como rodar

```bash
pip install -r applications/ml/requirements.txt
py applications/ml/src/preparar_dados.py      # no Windows, se "python" não estiver no PATH
# ou: python applications/ml/src/preparar_dados.py
```

Lê tudo de `data/raw/`, imprime um resumo dos filtros e das contagens (os números desta página
vêm desse resumo) e grava em `data/processed/`:

| Arquivo | O que é | Linhas |
|---|---|---|
| `postes_por_bairro.csv` | 1 linha por bairro: total de postes, % LED, potência média, RPA | 94 |
| `risco_bairro_mes.csv` | 1 linha por bairro × mês, com features de defasagem, rótulo e split | 4.136 |

Essas duas saídas **são pequenas e podem ir para o Git** (não são os CSVs brutos da Emlurb). O
painel vai de **2022-04 a 2025-11**: os 3 primeiros meses de cada bairro ficam sem histórico de 3 meses
pra trás, e 2025-12 sai porque não tem "mês seguinte" nos dados (o alvo dele seria 2026-01).

O resumo impresso também mostra quantas datas `DATA_DEMANDA` não puderam ser lidas. **Esse número tem
que ser 0**: o `pd.to_datetime(..., errors="coerce")` transforma em vazio, sem avisar, qualquer data num
formato diferente do esperado, e esses chamados sumiriam da contagem.

### Colunas de `risco_bairro_mes.csv`
| Coluna | Significado |
|---|---|
| `bairro_norm` | Bairro normalizado (sem acento, caixa alta, erros de digitação corrigidos) |
| `ano_mes` | Mês de referência (`AAAA-MM`) |
| `chamados_lampada_apagada` | Quantos chamados de lâmpada apagada esse bairro teve nesse mês |
| `chamados_lag1`/`lag2`/`lag3`, `media_movel_3m` | Histórico dos 1-3 meses anteriores do mesmo bairro (seção 5) |
| `total_postes`, `postes_sem_id`, `potencia_media_w`, `pct_led`, `rpa` | Features do cadastro de postes (seção 2) |
| `teve_chamado_mes_seguinte` | Rótulo binário (1 se o bairro teve ≥ 1 chamado no mês seguinte) — **não é mais o alvo principal**, ver seção 5 |
| `chamados_mes_seguinte` | **Alvo principal**: contagem de chamados do bairro no mês seguinte |
| `conjunto` | `treino` ou `teste`, separado **pelo mês do alvo** (não aleatório): treino = linhas de 2022-04 a 2024-11 (alvos até 2024-12, 3.008 linhas); teste = linhas de 2024-12 a 2025-11 (alvos em 2025, 1.128 linhas) |

---

## 5. Decisão de alvo: contagem (regressão/ranking), não classificação binária

Depois de agregar por bairro e mês, **~95-97% das linhas já têm `teve_chamado_mes_seguinte = 1`**
(treino e teste próximos um do outro, então o split temporal está ok). Isso é o **oposto** do
desbalanceamento "clássico" que o `MACHINE_LEARNING.md` avisava (rótulo raro) — aqui o raro é o
**zero**: com ~94 bairros dividindo milhares de chamados de lâmpada apagada por mês, quase todo
bairro tem pelo menos um chamado em quase todo mês.

Para checar se isso quebra o modelo de verdade, comparamos a correlação (treino) de cada feature
contra os dois alvos possíveis:

| Feature | correlação com o binário | correlação com a contagem |
|---|---|---|
| `chamados_lampada_apagada` (mês atual) | 0,15 | **0,89** |
| `media_movel_3m` | 0,14 | **0,88** |
| `chamados_lag1` | 0,14 | **0,85** |
| `total_postes` (estática) | 0,04 | **0,80** |

**Nenhuma feature passa de 0,15 de correlação com o alvo binário — nem o próprio histórico do
bairro.** Contra a contagem, a mesma feature de histórico chega a 0,89. A classificação binária
neste nível de agregação está estruturalmente quebrada pela prevalência de ~95%; a contagem
preserva toda a informação.

> **Correção de 25/11 no split:** antes, a linha de 2024-12 ficava no treino, mas o alvo dela é a
> contagem de **2025-01**, que é período de teste (vazamento de 94 linhas). Agora o `preparar_dados.py`
> separa pelo mês do alvo, e o CSV processado já foi atualizado. Os números da tabela acima e das
> seções 4 e 5 do notebook foram calculados antes dessa correção (mudam pouco). **Rode o notebook de
> novo** antes de usar esses números no relatório.

**Decisão: o `treinar.py` prevê `chamados_mes_seguinte` (regressão), não `teve_chamado_mes_seguinte`
(classificação).** A previsão vira "risco de 0 a 1" normalizando por percentil entre os bairros do
mesmo mês — mantém o contrato já documentado no `MACHINE_LEARNING.md` (potência 90/80/70 por faixa
de risco) — e avaliada pela **"precisão no top 10%"** da seção 4 do `MACHINE_LEARNING.md`, que já é
uma métrica de ranking e se encaixa na regressão de forma mais natural do que na classificação
binária original. O rótulo binário continua salvo na base, caso o relatório queira comparar as
duas abordagens, mas não é mais o alvo principal. Números completos e o gráfico de comparação estão
na seção 5 do [notebook de exploração](notebooks/01_exploracao.ipynb).

---

### O que o modelo precisa vencer (calculado em 25/11, conjunto de teste)

Com o mês atual explicando 0,89 do mês seguinte, regras de uma linha já acertam muito. O modelo só vale a
pena se **ganhar das duas primeiras linhas** (MAE menor **e** precisão no top 10% maior):

| Regra simples | MAE | Precisão no top 10% |
|---|---|---|
| Persistência: "mês seguinte = mês atual" (`chamados_lampada_apagada`) | 9,21 | **0,81** |
| `media_movel_3m` | **8,66** | 0,75 |
| Só o tamanho do bairro (`total_postes`) | — | 0,66 |

Teste: 12 meses (linhas de 2024-12 a 2025-11), 94 bairros, média de 32,7 chamados por bairro por mês.
**Precisão no top 10%:** em cada mês, pegue os 9 bairros (10% de 94) com maior previsão e os 9 com maior
contagem real no mês seguinte; a precisão é quantos estão nos dois grupos, dividido por 9. Depois, tire a
média dos 12 meses.

### Recomendação: risco por tamanho ou por taxa?

Só o número de postes já acerta 66% do top 10%: em contagem absoluta, "bairro de risco" vira quase
sinônimo de "bairro grande" (Boa Viagem sempre no topo). Para priorizar manutenção isso é útil (é onde
está o volume de trabalho), mas não diz onde **cada poste** falha mais. Sugestão para o grupo decidir e
explicar no relatório: treinar com a contagem (como decidido) e **mostrar os dois rankings**, o de
contagem prevista e o de **taxa prevista por 1.000 postes** (`previsão / total_postes * 1000`), e
escolher qual deles vira o risco de 0 a 1 publicado no MQTT.

---

## 6. Notebook de exploração

[`notebooks/01_exploracao.ipynb`](notebooks/01_exploracao.ipynb) — já executado, com gráficos embutidos.
Roda com `py -m jupyter nbconvert --to notebook --execute --inplace notebooks/01_exploracao.ipynb`
se os dados mudarem. Principais achados (além do que já está nas seções acima):

- **Boa Viagem concentra muito mais chamados que qualquer outro bairro** (~9.300 no período, quase
  o dobro do 2º colocado, Santo Amaro). Faz sentido usar isso como "estudo de caso" na apresentação.
- **98,3% dos postes já são LED**, em média por bairro — a transição para LED na cidade já está bem
  avançada, não há muita variação de `pct_led` entre bairros pra usar como feature forte sozinha.
- Não há uma relação linear clara entre `% LED` e volume de chamados no gráfico de dispersão — o
  volume parece dominado pelo tamanho do bairro (mais postes = mais chamados em termos absolutos),
  reforçando a necessidade de uma feature de exposição (`total_postes`) no modelo.
- **A decisão de alvo da seção 5** (contagem, não binário) é o achado mais importante do notebook —
  feito comparando a correlação de cada feature contra as duas opções de rótulo.

---

## 7. Próximos passos (estrutura do `MACHINE_LEARNING.md`, seção 6)

> Confirmado em 24/11: MLflow, Airflow, API e Docker são requisito desta disciplina, não "extra".
> A lista abaixo já reflete isso.

- [x] `data/raw/` baixado (postes 2025 + 156 de 2022-2025 + dicionário)
- [x] `src/preparar_dados.py` (normalização, cruzamento por bairro, rótulo, split treino/teste)
- [x] `notebooks/01_exploracao.ipynb` (EDA + visualizações, seção 2.0 do `MACHINE_LEARNING.md`)
- [ ] `src/treinar.py` (`RandomForestRegressor`/`GradientBoostingRegressor` prevendo
      `chamados_mes_seguinte`, seção 5 acima, vs. regra simples, métricas da seção 4 do
      `MACHINE_LEARNING.md`, cada treino como uma run do **MLflow**)
- [ ] `src/api.py` (FastAPI servindo a inferência do modelo registrado)
- [ ] `src/publicar_risco.py` (chama a API e publica risco + comando no MQTT)
- [ ] `dags/risco_dag.py` (Airflow: orquestra os três scripts acima)
- [ ] `Dockerfile` + `docker-compose.yml` (Mosquitto + coletor + API + MLflow + Airflow)
- [ ] `config.json` (mapear o poste `P01` da maquete para um `id_ponto` e um bairro reais do cadastro;
      os 3 mini postes da maquete estão no mesmo ESP32/GPIO18, então são **um** poste lógico)
- [ ] Rodar o notebook de novo depois da correção do split (seção 5)
