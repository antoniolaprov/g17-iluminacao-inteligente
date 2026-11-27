# T8 · Revisão de UX dos painéis

Concluída em **27/11/2026**, por **Luiz Claudio**, na branch `fase2-central-ml`.

## Ajustes implementados

| Problema observado | Ajuste |
|---|---|
| Indicadores globais pareciam acompanhar os filtros | Apagadas, cintilando e acima do limiar usam o mesmo recorte da lista e do mapa; o cabeçalho informa quantas luminárias estão visíveis. |
| Mapa e lista disputavam espaço | A operação começa pela lista de manutenção, seguida dos alertas recolhíveis e do mapa em toda a largura disponível. |
| Destaques do mapa divergiam da lista ao filtrar | Pontos maiores correspondem aos mesmos IDs da lista filtrada; o número # continua identificado como posição no ranking geral. |
| Legenda incompleta e cores pouco explícitas | Faixas com amostras das cores reais, rótulos e limites sem sobreposição, incluindo apagada e sem previsão. Borda laranja e tamanho dos pontos explicados. |
| Risco do mapa confundido com o limiar aprendido | Indicador “Acima do limiar” tem ajuda com o limiar do modelo; as cores do mapa continuam sendo faixas fixas. |
| A rolagem da página podia mudar o zoom | Zoom por roda desabilitado; controles do mapa continuam disponíveis. Enquadramento acompanha o recorte. |
| Navegação técnica antes da operação diária | Ordem: Operação → Luminária → Dimerização → Modelo → CPTED. Abas globais informam que não seguem os filtros. |
| Recortes vazios e atualização pouco claros | Mensagens para recorte vazio, botão de limpar filtros, recuperação quando API/parque está indisponível e atualização imediata após limpar o cache. |
| Muitas informações técnicas no primeiro contato | Endereço da API em detalhes; CPTED explicado; séries de potência com nomes completos; data explicitamente identificada como cenário simulado. |
| Comandos da maquete pouco evidentes | Controles antes dos gráficos, destino explícito, atalhos “Enviar N%” e aviso de envio imediato. Confirmação de publicação não é apresentada como confirmação de aplicação. |
| Controles disponíveis sem telemetria recente | Slider, enviar e atalhos desabilitados sem conexão/leitura recente; aviso de desconexão e valores históricos. |
| Troca de poste/reconexão podia manter valores anteriores | Campos sem telemetria são limpos; cada poste mantém seus próprios gráficos e histórico. |
| Atualização periódica reconstruía os botões | Botões de seleção são preservados durante as atualizações, mantendo o foco do teclado. |
| Uso em celular | Seletores de poste em duas colunas, SVG limitado à largura, foco visível, alvos de toque maiores, título do gestor reduzido e tabelas com rolagem interna. |
| Índice de bairro parecia probabilidade de falha do poste | Card da maquete identifica o ranking relativo do bairro e explica a diferença. |

Os contratos MQTT, as rotas da API, os modelos versionados e as regras de iluminação não foram alterados.

## Validação e origem das evidências

- **37 testes aprovados** com `python -m pytest applications/tests -q`. Os cinco novos testes em
  `test_dashboard_gestor.py` cobrem indicadores/lista/alertas no mesmo recorte, preservação de apagadas
  com filtro de risco, limpeza de recorte vazio, API sem dados/indisponível e atualização imediata.
- JavaScript extraído da página conferido com `node --check`.
- Navegação real no navegador: filtro por Boa Viagem, limpar filtros, abas, histórico individual,
  temas claro/escuro, seleção de P01/P06, publicação de 90% e leitura subsequente de `pedido=90`.
- Páginas conferidas em **1280 px**, **390 px** e **320 px**. Não houve transbordamento horizontal
  da página; tabelas possuem rolagem própria. No celular, filtros ficam na barra lateral recolhível.
- Estado de desconexão exercitado com destino local sem broker; envio ficou desabilitado, valores
  foram limpos na reconexão e o broker de teste foi restaurado. Foco no botão de comando permaneceu
  durante as atualizações periódicas.
- API real respondeu HTTP 200 para luminárias, alertas, métricas, CPTED, dimerização e detalhe da
  luminária. Sem erros de console nos dois painéis após a revisão final.

### Cenário de validação (não é uma demonstração física)

As capturas foram feitas após os ajustes, em serviços locais separados da demo: SQLite temporário,
500 luminárias geradas pelo simulador por 180 dias, API FastAPI e painel Streamlit reais, broker
MQTT local e os dez postes do simulador, incluindo P01 com cascata em Y. Referência do parque:
**2024-06-28**. O plano gerado teve **6.000 comandos e zero violações**.

O artefato XGBoost versionado apresentou `input stream corrupted` ao ser desserializado neste Windows.
Para exercitar o fluxo de dados da interface, foi usado um XGBoost pequeno treinado e salvo somente
no diretório temporário de validação. Isso **não reavalia a qualidade do ML de produção**. Os valores
da aba Modelo são os metadados históricos versionados, do treino de **26/11/2026**, e não métricas
desse modelo temporário. Os modelos e dados de produção do repositório foram preservados.

Os alertas de anomalia de P06 foram publicados como cenário controlado de UX, identificado no próprio
card como “cenário de validação UX”; não são evidência de detecção do modelo nem de defeito físico.
Não houve acesso ao broker público ou à placa. As bibliotecas e os mapas usam recursos públicos da web.

## Capturas após a revisão

| Evidência | Arquivo |
|---|---|
| Operação e lista prioritária | [Gestor desktop](figuras/t8/gestor_operacao_desktop.jpg) |
| Mapa e legenda completa | [Mapa desktop](figuras/t8/gestor_mapa_desktop.jpg) |
| Métricas históricas do modelo | [Modelo](figuras/t8/gestor_modelo_desktop.jpg) |
| Pesos e sensibilidade | [CPTED](figuras/t8/gestor_cpted_desktop.jpg) |
| Plano e segurança | [Dimerização](figuras/t8/gestor_dimerizacao_desktop.jpg) |
| Gestor em 390 px | [Celular](figuras/t8/gestor_mobile.jpg) |
| Gestor em 320 px | [Tela estreita](figuras/t8/gestor_mobile_320.jpg) |
| P01 com cascata, risco e anomalia | [Maquete desktop](figuras/t8/maquete_p01_desktop.jpg) |
| P06 com alerta controlado | [Alerta desktop](figuras/t8/maquete_p06_desktop.jpg) |
| P01 em 390 px | [Maquete celular](figuras/t8/maquete_p01_mobile.jpg) |
| Sem conexão | [Estado indisponível](figuras/t8/maquete_sem_conexao_mobile.jpg) |

Essas são as evidências dos **painéis** relacionadas à T2, com a origem acima. A T2 completa permanece
pendente: Airflow, MLflow, Swagger e os demais registros da demonstração oficial continuam no backlog.
Validação com a placa física permanece nas T10–T12.
