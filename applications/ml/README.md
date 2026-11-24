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
  154 bairros "brutos" para **97 bairros reais** depois de normalizar.
- **Colunas `consumo_kw` e `consumo_1` do cadastro de postes não fazem sentido** (ficam na casa de
  petawatt-hora para uma única luminária — claramente um artefato de exportação). Não são usadas
  aqui nem devem ser usadas sem recalcular a partir de `potencia`.

---

## 3. Normalização e cruzamento

Função `normalizar_bairro()` em `src/preparar_dados.py`: remove acento, deixa em CAIXA ALTA,
colapsa espaços duplicados e tira espaço nas pontas. Aplicada dos dois lados (cadastro de postes
e chamados) antes do `merge`.

Depois de normalizar: **98 bairros distintos** nos chamados de lâmpada apagada, **97** no cadastro
de postes, com **4 bairros nos chamados sem poste cadastrado correspondente**:
`ALTO DO MANDU SITIO GRANDE`, `BAIRRO NAO INFORMADO`, `COHAB IBURA DE CIMA`, `SITIO DOS PINTOS SAO
BRAS`. Esses casos ficam no painel final sem as colunas de poste preenchidas (`NaN`) — são bairros
"compostos" ou mal cadastrados no 156, não dá pra reconciliar automaticamente sem decisão manual.

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
| `postes_por_bairro.csv` | 1 linha por bairro: total de postes, % LED, potência média, RPA | 97 |
| `risco_bairro_mes.csv` | 1 linha por bairro × mês (2022-01 a 2025-11), com o rótulo e o split | 4.747 |

Essas duas saídas **são pequenas e podem ir para o Git** (não são os CSVs brutos da Emlurb).

### Colunas de `risco_bairro_mes.csv`
| Coluna | Significado |
|---|---|
| `bairro_norm` | Bairro normalizado (sem acento, caixa alta) |
| `ano_mes` | Mês de referência (`AAAA-MM`) |
| `chamados_lampada_apagada` | Quantos chamados de lâmpada apagada esse bairro teve nesse mês |
| `total_postes`, `postes_sem_id`, `potencia_media_w`, `pct_led`, `rpa` | Features do cadastro de postes (seção 2) |
| `teve_chamado_mes_seguinte` | **Rótulo**: 1 se o bairro teve ≥ 1 chamado no mês seguinte |
| `conjunto` | `treino` (2022-01 a 2024-12) ou `teste` (2025-01 a 2025-11), separado por tempo, não aleatório |

---

## 5. Atenção para quem for treinar o modelo: o rótulo está desbalanceado ao contrário

Depois de agregar por bairro e mês, **91,4% das linhas de treino e 91,6% das de teste já têm
`teve_chamado_mes_seguinte = 1`**. Faz sentido: com ~95 bairros dividindo ~3.000 chamados de
lâmpada apagada por mês, quase todo bairro tem pelo menos um chamado em quase todo mês. Isso é o
**oposto** do desbalanceamento "clássico" que o `MACHINE_LEARNING.md` avisava (rótulo raro) — aqui
o raro é o **zero**.

Prever "vai ter chamado ou não" nesse nível de agregação tende a virar um modelo que só acerta
dizendo sempre "sim". Vale considerar, antes de treinar:
- prever a **contagem** de chamados do mês seguinte (regressão) ou um **ranking** de bairros por
  intensidade, em vez de um sim/não;
- ou agregar por uma unidade menor que bairro (não temos coordenada/poste confiável nos chamados
  para isso, seção 2);
- ou tratar como desbalanceado na classe 0 (bairro sem nenhum chamado no mês seguinte), que é a
  minoria de verdade.

Isso é uma decisão de modelagem, não foi resolvido aqui — fica para quem tocar o `treinar.py`.

---

## 6. Notebook de exploração

[`notebooks/01_exploracao.ipynb`](notebooks/01_exploracao.ipynb) — já executado, com gráficos embutidos.
Roda com `py -m jupyter nbconvert --to notebook --execute --inplace notebooks/01_exploracao.ipynb`
se os dados mudarem. Principais achados (além do que já está nas seções acima):

- **Boa Viagem concentra muito mais chamados que qualquer outro bairro** (~9.300 no período, quase
  o dobro do 2º colocado, Santo Amaro). Faz sentido usar isso como "estudo de caso" na apresentação.
- **98,4% dos postes já são LED**, em média por bairro — a transição para LED na cidade já está bem
  avançada, não há muita variação de `pct_led` entre bairros pra usar como feature forte sozinha.
- Não há uma relação linear clara entre `% LED` e volume de chamados no gráfico de dispersão — o
  volume parece dominado pelo tamanho do bairro (mais postes = mais chamados em termos absolutos),
  reforçando a necessidade de uma feature de exposição (`total_postes`) no modelo.

---

## 7. Próximos passos (estrutura do `MACHINE_LEARNING.md`, seção 6)

> Confirmado em 24/11: MLflow, Airflow, API e Docker são requisito desta disciplina, não "extra".
> A lista abaixo já reflete isso.

- [x] `data/raw/` baixado (postes 2025 + 156 de 2022-2025 + dicionário)
- [x] `src/preparar_dados.py` (normalização, cruzamento por bairro, rótulo, split treino/teste)
- [x] `notebooks/01_exploracao.ipynb` (EDA + visualizações, seção 2.0 do `MACHINE_LEARNING.md`)
- [ ] `src/treinar.py` (`RandomForestClassifier`/`GradientBoostingClassifier` vs. regra simples,
      métricas da seção 4 do `MACHINE_LEARNING.md`, cada treino como uma run do **MLflow**)
- [ ] `src/api.py` (FastAPI servindo a inferência do modelo registrado)
- [ ] `src/publicar_risco.py` (chama a API e publica risco + comando no MQTT)
- [ ] `dags/risco_dag.py` (Airflow: orquestra os três scripts acima)
- [ ] `Dockerfile` + `docker-compose.yml` (Mosquitto + coletor + API + MLflow + Airflow)
- [ ] `config.json` (mapear `P01`-`P03` para `id_ponto` reais do cadastro)
