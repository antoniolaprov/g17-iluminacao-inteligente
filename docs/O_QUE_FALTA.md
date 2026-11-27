# O que falta para terminar o projeto (Grupo 17)

> **Lista única e atual** do que ainda precisa ser feito, com critério de pronto. Atualizada em
> **27/11/2026**. Prazos: **03/12, 23h59** (relatório CSBC em PDF + link do GitHub no Classroom) e
> **12/12** (apresentação ao vivo na Mostra TechDesign).
>
> O resto do projeto (firmware, maquete, central, modelos, pipeline, painéis, Docker, testes) **está
> pronto e testado**: veja a seção "Já está pronto" no fim. Não refaça o que já funciona.

---

## Como usar este arquivo com o Claude (ou outra IA)

1. `git pull` na branch **`fase2-central-ml`**.
2. Escolha uma tarefa pelo número e peça: *"Faça a tarefa T4 do docs/O_QUE_FALTA.md"*.
3. Legenda de quem faz:
   - 🤖 **o Claude consegue fazer sozinho** (código, documentação, notebooks);
   - 🤝 **o Claude ajuda, mas uma pessoa decide ou executa uma parte** (decisão do grupo, print, conta);
   - 👤 **só uma pessoa** (placa física, texto do relatório, conversa com os professores).
4. Regras para a IA (estão também no `CLAUDE.md`):
   - responder em português, em passos pequenos;
   - rodar os testes antes de commitar mudança em Python:
     `cd applications` e depois `docker compose run --rm --no-deps api python -m pytest tests -q`;
   - **quem fez a tarefa commita com a própria conta**, com a linha de coautoria da IA no fim da mensagem;
   - **no mesmo commit, marcar a tarefa como feita aqui** (troque ⬜ por ✅ e escreva a data e quem fez);
   - **não escrever o texto do relatório** (o edital só permite IA para revisão).

---

## Prioridade 1: antes de 03/12 (entrega)

### ⬜ T1 · Relatório CSBC 👤 (com revisão 🤝)
- **O que é:** relatório no template da SBC (CSBC) com introdução, metodologia, resultados e os códigos
  em apêndice, mais a **declaração de uso de IA**. Vale 20 pontos.
- **Quem escreve:** o grupo. A IA só pode **revisar o texto, conferir números e explicar conceitos**.
- **Onde estão os fatos para citar:**
  - [`CONTEXTO_PARA_IA.md`](CONTEXTO_PARA_IA.md), seções 4, 8 e 10.0;
  - [`ALINHAMENTO_PROPOSTA.md`](ALINHAMENTO_PROPOSTA.md), com a tabela de verificação;
  - [`PREMISSAS_SIMULADOR.md`](PREMISSAS_SIMULADOR.md);
  - o notebook `applications/ml/notebooks/03_falha_14d.ipynb`.
- **Cuidados:**
  - Os resultados do modelo de falha são sobre **dados simulados** (proposta, g.5).
  - Mostre a PR-AUC de **validação e de teste**. Em três treinos ela variou de 0,067 a 0,098.
  - Cite a queda da PR-AUC no teste de robustez como limitação.
- **Pronto quando:** `docs/Projeto_Embarcados_Grupo17.pdf` estiver commitado e enviado no Classroom com
  o link do GitHub.

### ⬜ T2 · Prints e figuras para o relatório 🤝
- **O que fazer:**
  1. Suba tudo com `INICIAR_DEMO.bat` (responda N se a maquete não estiver por perto).
  2. No Airflow (http://localhost:8080; a senha sai de
     `docker compose exec airflow cat standalone_admin_password.txt`), **despause** os DAGs
     `g17_falha_14d` e `g17_falha_14d_treino` e dispare os três DAGs `g17_*`. Eles foram pausados de
     propósito em 26/11, para os modelos não mudarem sozinhos durante a noite.
  3. Tire os prints e salve em `docs/figuras/`:
     - **Airflow:** os 3 DAGs verdes, na visão Grid;
     - **MLflow** (http://localhost:5000): o experimento `falha_14d`, com a comparação e as tentativas do
       Optuna, e o modelo registrado;
     - **Swagger da API:** http://localhost:8000/docs;
     - **Painel do gestor** (http://localhost:8501): as abas mapa, modelo, CPTED e dimerização;
     - **Dashboard da maquete:** `applications/dashboard/index.html?broker=ws://localhost:9001`, com o
       P01 selecionado (cascata em Y, risco, anomalia) e o P06 em alerta de anomalia.
  4. Se precisar, exporte as figuras do notebook 03.
- **Quem faz:** o Claude pode abrir as páginas e tirar os prints, se tiver o navegador integrado; se
  não tiver, uma pessoa tira.
- **Pronto quando:** as figuras estiverem em `docs/figuras/` com nomes claros (`airflow_dags.png`,
  `mlflow_falha_14d.png`...).

### ⬜ T3 · Esquemático e fotos atualizados (`/schematics`) 🤝
- **Problema:** `schematics/esquematico-wokwi.png` e `schematics/README.md` são de **19/11**, de antes do
  firmware v3.0. Eles não mostram os 3 postes em pinos separados (D18, D22, D23) nem o segundo
  ultrassônico (S2 em D2/D4). O `diagram.json` já está atualizado. Uma pasta fraca tira nota.
- **O que fazer:**
  1. 🤝 Abrir o `esp32-esp8266/poste_g17/diagram.json` no Wokwi e salvar o print novo do circuito.
  2. 🤖 Reescrever o `schematics/README.md` com a tabela de pinos da v3.0 (seção 6 do contexto).
  3. 👤 Tirar fotos da maquete montada, na faculdade, e commitar em `schematics/fotos/`.
- **Pronto quando:** o esquemático, o README e as fotos batem com a montagem atual.

### ⬜ T4 · Declaração de uso de IA no README 🤖 (o grupo confere)
- **O que fazer:** criar uma seção "Uso de IA" no `README.md`, dizendo:
  - onde a IA foi usada: código, documentação e revisão, com o Claude Code;
  - que os commits com IA têm a linha de coautoria;
  - que o relatório só teve revisão de texto.
- **Pronto quando:** a seção existe e o grupo confirmou que está correta.

### ⬜ T5 · Decisões que são do grupo 🤝
O Claude explica as opções, **o grupo decide** e depois o Claude ajusta o código, a documentação e os testes.
- **T5a, matriz AHP do score CPTED:** em `applications/ml/src/cpted.py` (`MATRIZ_AHP` e
  `JUSTIFICATIVAS`). A proposta (g.4) pede que o grupo justifique cada comparação. Responsável pela
  frente: **Henrique**.
  - **Pronto quando:** a matriz foi revisada, CR < 0,10 e o teste `tests/test_cpted.py` passa.
- **T5b, premissas do simulador:** revisar `docs/PREMISSAS_SIMULADOR.md` e `simulador/premissas_parque.json`
  (as linhas marcadas como "premissa"). Se algum valor mudar, gerar o parque de novo e retreinar.
- **T5c, risco por bairro, contagem ou taxa** (ML-06 da auditoria): o padrão é `contagem` em
  `applications/ml/config.json`.

### ⬜ T6 · Commits de todos os integrantes 👤
- **Situação em 27/11:** só **Antônio, Felipe e fthenri2** têm commits. **Arthur, Bruno, Luiz Claudio e
  Miguel não têm nenhum.** A nota avalia "commits colaborativos".
- **O que fazer:** cada um pega pelo menos uma tarefa desta lista e commita com a **própria conta**.
  Sugestão, pelas frentes da proposta:

  | Pessoa | Frente na proposta | Tarefas sugeridas |
  |---|---|---|
  | Arthur Sales | UX/UI e Dashboard | T8 |
  | Bruno Mayer | Backend e Integração | T9, T17 |
  | Luiz Claudio Pinheiro | DevOps, Testes e Validação | T2, T18 |
  | Miguel Becker | IA / MLOps | T5b, T15 |
  | Henrique Figueredo | CPTED e Eficiência Energética | T5a |
  | Felipe Andrade | Gestão e documentação | T1 (coordenação), T4 |
  | Antônio Augusto | IoT e Engenharia de Dados | T3, T10, T11, T12 |
- **Pronto quando:** todos os 7 aparecem em `git shortlog -sn --all`.

### ⬜ T7 · Juntar a `fase2-central-ml` na `main` 🤝 (decisão do representante)
- **Por quê:** o repositório é público, e a branch padrão, que é o que os professores abrem, é a **`main`**.
  A `fase2-central-ml` tem pelo menos 16 commits que ainda não estão na `main`.
- **O que fazer:**
  1. Todos dão push no que tiverem.
  2. Rodar os testes.
  3. Abrir o pull request `fase2-central-ml` → `main` (o Claude faz com `gh pr create`).
  4. Revisar e fazer o merge.
  5. Conferir se o README aparece certo na página do GitHub.
- **Pronto quando:** a `main` tiver tudo, antes de 03/12. Depois do merge, combinem se o trabalho
  continua na `main`.

### ⬜ T8 · Revisão de UX dos painéis 🤝 (Arthur)
- **O que fazer:** revisar o painel do gestor (`applications/dashboard_gestor/app.py`) e o dashboard da
  maquete com o olhar de usuário:
  - legenda do mapa, textos, ordem das abas;
  - o que o gestor vê primeiro;
  - funcionamento em tela menor.
- **Quem faz:** o Claude implementa os ajustes que a pessoa pedir.
- **Pronto quando:** a lista de ajustes foi feita e os prints da T2 foram tirados depois dela.

### ⬜ T9 · README final 🤖
- **O que fazer:** revisar o `README.md` da raiz como porta de entrada:
  - o que é o projeto;
  - as duas frentes (maquete e plataforma);
  - como rodar em dois cliques;
  - prints (os da T2);
  - status e equipe.
- **Pronto quando:** alguém de fora consegue entender e rodar o projeto só com o README.

---

## Prioridade 2: até 12/12 (demonstração), quase tudo com a placa

### ⬜ T10 · Placa na central local, pela ponte (A5) 👤 + 🤖
1. Ligue a maquete no Wi-Fi.
2. Rode o `INICIAR_DEMO.bat` respondendo **S**. Ele liga o Mosquitto com a ponte para o HiveMQ e não sobe
   o P01 simulado.
3. Confira:
   - o P01 aparece no dashboard (broker local);
   - o coletor grava (`docker compose logs -f coletor`);
   - um comando enviado pelo dashboard chega na placa.
- **Pronto quando:** a demo inteira funciona com a placa usando só a central local.

### ⬜ T11 · Travessias reais e modelo de rota com a placa (F4 e F10) 👤 + 🤖
1. Com a placa ligada (T10), passe o boneco ~10 min pela rua em Y, de um jeito consistente por lado da rua.
2. Rode `docker compose run --rm --no-deps rota python ml/src/prever_rota.py treinar` e confira as
   métricas `teste_reais_*`.
3. Confira a telemetria mostrando `rota_fonte=modelo`.
- **Pronto quando:** as linhas com `origem` vazia aparecem na tabela `travessia` e o dashboard mostra
  "O modelo de ML previu o caminho".

### ⬜ T12 · Dimerização e risco na placa (ML-09) 👤
- **O que fazer:** à noite, ou com o sensor de luz tampado, conferir:
  - o P01 recebe o comando da dimerização (log `[dimerizar] ... comandos aos postes` do serviço `pipeline`);
  - o LED nunca fica abaixo de 70%;
  - o pedestre leva o LED a 100%.
- **Prints:** o dashboard com o P01 e o log.
- **Pronto quando:** houver evidência (print ou vídeo) do comportamento na placa.

### ⬜ T13 · Ensaio da apresentação (E5) 🤝
- **O que fazer:** roteiro de ~10 min, dizendo quem fala o quê e em que ordem:
  1. problema e pesquisa;
  2. maquete ao vivo;
  3. painel do gestor;
  4. modelo e resultados;
  5. limitações.
- **Plano B sem internet:** `INICIAR_DEMO.bat` respondendo **N** (tudo simulado, inclusive o P01).
- **Checklist do dia:**
  - Docker Desktop aberto antes;
  - imagens já construídas na véspera (a primeira construção leva ~20 min);
  - o parque já gerado (o banco fica no volume do Docker);
  - o notebook 03 aberto;
  - os prints da T2 como reserva.
- **Quem faz:** o Claude pode rascunhar o roteiro e o checklist; o grupo ajusta e ensaia.
- **Pronto quando:** houve pelo menos um ensaio completo antes de 12/12.

### ⬜ T14 · Decorar a maquete 👤

---

## Prioridade 3: bônus e opcionais

### ⬜ T15 · Alertas no Telegram (D1, bônus de até +10) 🤝
1. 👤 Crie um bot no **@BotFather** e pegue o `chat_id` (passo a passo em `applications/README.md`).
2. 👤 Crie `applications/.env` com `TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID`. Esse arquivo **nunca** vai para o Git.
3. 🤖 Confira se a mensagem chega quando o P02 entra em FALHA, que acontece em poucos minutos no simulador.
- **Pronto quando:** houver o print da mensagem no celular.

### ⬜ T16 · IPv6: confirmar com os professores como será avaliado 👤
- Já está testado localmente (`::1`, ver `applications/README.md`).
- **Pronto quando:** souberem se o teste local basta.

### ⬜ T17 · Notebooks 01 e 02 do modelo de bairro (ML-04 da auditoria) 🤖
- **O que fazer:**
  - no notebook 02: gráficos de resíduos, real × previsto e R², e a tabela com MAE, RMSE, R² e precisão no top 10%;
  - no notebook 01: uma seção inicial resumindo a limpeza feita em `preparar_dados.py`;
  - executar os dois de novo.
- **Pronto quando:** os dois notebooks estiverem reexecutados, com as saídas salvas.

### ⬜ T18 · Testes automáticos no GitHub Actions 🤖 (Luiz)
- **O que fazer:** criar um workflow que instala `applications/requirements-central.txt` e roda
  `python -m pytest applications/tests -q` a cada push ou pull request.
- **Pronto quando:** o selo verde aparecer no GitHub.

### ⬜ T19 · K-Means de zonas prioritárias (ML-12) 🤖, opcional
### ⬜ T20 · `id_ponto` real no `config.json` (ML-07) 🤝, opcional
- Precisa baixar o CSV bruto de postes do portal de dados abertos do Recife.

---

## Já está pronto (não refazer)

| Parte | Onde |
|---|---|
| Firmware v3.0 (cascata em Y), testado na placa | `esp32-esp8266/poste_g17/` |
| Dashboard da maquete (tempo real, risco, rota, anomalia) | `applications/dashboard/` |
| Central em Docker: Mosquitto (IPv4/IPv6/WebSocket, ponte com o HiveMQ), coletor + SQLite, simulador P02..P10 | `applications/` |
| Parque de 500 luminárias com degradação, calibrado com a Emlurb, em PostgreSQL | `applications/simulador/parque.py`, `banco_parque.py` |
| Modelo de falha em 14 dias (RF/XGBoost, Optuna, calibração, PR-AUC, robustez, MLflow) | `applications/ml/src/treinar_falha.py` |
| Score CPTED (AHP) e dimerização com teste de segurança (0 violações) | `applications/ml/src/cpted.py`, `dimerizacao.py` |
| Pipeline e DAGs do Airflow (3 DAGs testados e verdes em 26/11) | `applications/ml/src/pipeline_parque.py`, `ml/dags/` |
| Painel do gestor (Streamlit + mapa) e API | `applications/dashboard_gestor/`, `ml/src/api.py` |
| Modelo de risco por bairro (Emlurb), modelo de rota e detector de anomalias | `applications/ml/src/` |
| Demo em dois cliques | `INICIAR_DEMO.bat`, `PARAR_DEMO.bat` |
| Testes automáticos (32) | `applications/tests/` |

## Como conferir que está tudo funcionando

1. `INICIAR_DEMO.bat` → responda N → espere as páginas abrirem.
2. Os testes: `cd applications` e `docker compose run --rm --no-deps api python -m pytest tests -q`
   (tem que dar "32 passed").
3. Http://localhost:8501 mostra o mapa com as 500 luminárias, e a aba "Dimerização" mostra "0 violações".
