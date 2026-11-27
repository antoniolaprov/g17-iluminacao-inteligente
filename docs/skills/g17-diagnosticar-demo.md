# Diagnosticar a demo do G17

Consulte [o guia da central](../../applications/README.md), [o Compose](../../applications/docker-compose.yml) e as tarefas T2, T10 e T13 no [backlog](../O_QUE_FALTA.md). Comece pelo sintoma observado e registre o modo da demo, o serviço e o horário da falha.

## Localizar a falha

1. Confirme que a engine responde com `docker info`. Em `applications/`, use `docker compose --profile sim --profile airflow ps -a` para identificar serviços ausentes, parados ou reiniciando. Leia os logs do primeiro serviço suspeito com `docker compose logs --tail 100 <serviço>`.
2. Se o P01 sumiu, confira o modo efetivo do simulador em execução e o arquivo de configuração montado no Mosquitto. O modo simulado usa `SIM_INCLUIR_P01=1` e `mosquitto.conf`. O modo maquete usa `SIM_INCLUIR_P01=0` e `mosquitto-ponte.conf`. Confirme que só uma origem publica como P01 no broker usado. Verifique se a telemetria chega ao broker local, se aparece nos logs do `coletor` e se o dashboard usa `ws://localhost:9001`.
3. Se o painel do gestor estiver vazio, siga `parque → mosquitto → ingestor → postgres → pipeline → api → gestor`. Comece pela primeira etapa sem dados. Confira `http://localhost:8000/saude`, depois `/luminarias`, `/previsoes` ou `/dimerizacao` conforme o sintoma. Durante a geração inicial do histórico, confirme progresso nos logs antes de concluir que o pipeline travou.
4. Se o problema estiver em MLflow ou Airflow, confira `http://localhost:5000/health` e a execução relevante do experimento `falha_14d`. Para DAGs, confirme se o profile `airflow` está ativo e se a execução está pausada, em fila ou falhou. Leia o log da primeira tarefa com erro. O Airflow sobe separadamente da demo.
5. Se for preciso iniciar a demo para a tarefa, use `INICIAR_DEMO.bat simulado` sem placa ou `INICIAR_DEMO.bat maquete` com a placa ligada. Verifique serviços e artefatos antes de reiniciar. A inicialização pode treinar modelos ausentes e regravar artefatos locais. Preserve os volumes e o estado dos DAGs durante o diagnóstico. Siga as ações da T2 para a coleta de evidências quando ela fizer parte do pedido.

## Registrar o resultado

Informe em que etapa o fluxo parou, qual log ou resposta sustenta o diagnóstico, o ajuste aplicado ou indicado e o resultado da conferência. Para a T2, salve em `docs/figuras/` as capturas realmente obtidas, seguindo a lista vigente do backlog. Registre a execução ou data usada e os prints pendentes. O modo simulado serve de reserva para o ensaio. Confirme a integração física em um teste com a placa.
