// =============================================================
//  Poste Inteligente G17 - v3.0 (FreeRTOS + Wi-Fi + MQTT)
//  CESAR School - Sistemas Embarcados
//
//  Maquete com rua em Y: 3 mini postes (LED 3 V, cada um com resistor de
//  100 ohms) em pinos separados, base no GPIO18, braco esquerdo no GPIO22 e
//  braco direito no GPIO23. No Wokwi, que nao tem o mini poste, a base e um
//  LED RGB com R, G e B juntos (branco) e os bracos sao LEDs brancos.
//  O LED RGB em 19/21/5 e o indicador de status.
//
//  Cascata: quando o sensor S1 (entrada da rua) detecta um pedestre, o poste da
//  base vai a 100% e os dois bracos sao pre-acesos a 85%, porque ainda nao se
//  sabe o caminho. Se o modelo de ML responder (topico .../rota), so o braco
//  previsto acende, a 100%, antes de o pedestre chegar. O sensor S2, no braco
//  esquerdo, confirma o caminho: S2 disparou = esquerda (esquerdo a 100%);
//  nao disparou na janela = direita (direito a 100%).
// =============================================================
#include <WiFi.h>
#include <PubSubClient.h>
#include <stdarg.h>

#define SIMULACAO 1   // 1 = Wokwi | 0 = placa fisica
#define USAR_REDE 1   // 1 = Wi-Fi + MQTT | 0 = teste local so com sensores e LEDs (sem fail-safe de rede)
#define USAR_S2   1   // 1 = sensor S2 ligado no braco esquerdo | 0 = so o S1 (preve, mas nao confirma)

// ---------------- Rede ----------------
#if SIMULACAO
const char* WIFI_SSID  = "Wokwi-GUEST";
const char* WIFI_SENHA = "";
#else
const char* WIFI_SSID  = "NOME_DA_SUA_REDE";
const char* WIFI_SENHA = "SENHA_DA_SUA_REDE";
#endif
const char* MQTT_BROKER = "broker.hivemq.com";
const int   MQTT_PORTA  = 1883;
const char* POSTE_ID    = "P01";

char TOPICO_TELEMETRIA[48];
char TOPICO_COMANDO[48];
char TOPICO_STATUS[48];
char TOPICO_EVENTO[48];     // poste -> ML: pedestre entrou (pede previsao)
char TOPICO_ROTA[48];       // ML -> poste: previsao do braco
char TOPICO_TRAVESSIA[48];  // poste -> central: travessia completa (dado de treino)

// ---------------- Pinos ----------------
const int PINO_POSTE_BASE = 18;   // poste da entrada da rua (base do Y)
const int PINO_POSTE_ESQ  = 22;   // poste do braco esquerdo
const int PINO_POSTE_DIR  = 23;   // poste do braco direito
const int PINO_R          = 19;   // LED RGB de status
const int PINO_G          = 21;
const int PINO_B          = 5;
const int PINO_TRIG_S1    = 26;   // S1: entrada da rua
const int PINO_ECHO_S1    = 27;
// S2 no D2/D4: testado na placa em 26/11 (em D25/D32 nao respondeu). O D2 tambem acende o LED
// azul da placa, que por isso deixou de indicar "conectado a central"; o pulso do TRIG e curto
// demais para o LED piscar visivelmente.
const int PINO_TRIG_S2    = 2;    // S2: braco esquerdo
const int PINO_ECHO_S2    = 4;
const int PINO_LDR        = 34;
const int PINO_POT        = 35;

const int BASE = 0, ESQ = 1, DIR = 2;
const int PINOS_POSTE[3] = {PINO_POSTE_BASE, PINO_POSTE_ESQ, PINO_POSTE_DIR};
const char* NOME_LADO[3] = {"nenhuma", "esquerda", "direita"};   // indice ESQ/DIR; 0 = sem rota

// ---------------- Ajustes ----------------
#if SIMULACAO
const bool LDR_INVERTIDO = true;
const int  LIMIAR_NOITE  = 2000;
const int  LIMIAR_DIA    = 2200;
const float GAMMA_LUMINARIA = 2.2;  // correcao gama: brilho percebido (1.0 = PWM linear)
#else
const bool LDR_INVERTIDO = false;   // sensor de 2 pernas + 10k: mais luz = numero maior
const int  LIMIAR_NOITE  = 2500;    // escurece abaixo disso (19/11: sala ~3000, sombra da mao ~2200, dedo ~400)
const int  LIMIAR_DIA    = 2700;    // so volta a ser dia acima disso (histerese: nao pisca perto do limite)
// Mini poste (LED 3 V num pino de 3,3 V) brilha pouco e comprime a diferenca entre 70% e 100%.
// Gama maior deixa o 70% bem mais escuro na maquete (~24% de PWM) e o 100% fica evidente.
const float GAMMA_LUMINARIA = 4.0;
#endif
const bool  RGB_ANODO_COMUM = false;

// Sensores na maquete. Calibrar com o Monitor: DIST_PRESENCA tem que ser MENOR que a distancia
// ate o outro lado da rua (senao o sensor "ve" a parede como pedestre o tempo todo).
const float DIST_PRESENCA_S1_CM = 10;   // S1 atravessa a rua da base
const float DIST_PRESENCA_S2_CM = 10;   // S2 atravessa o braco esquerdo

const unsigned long TEMPO_PRESENCA_MS = 500;   // base fica a 100% por 0,5 s depois que o pedestre sai
const unsigned long JANELA_ROTA_MS    = 4000;  // tempo para o S2 confirmar a esquerda; depois disso = direita
const unsigned long TEMPO_BRACO_MS    = 2500;  // braco confirmado fica a 100% por esse tempo
const int   PRE_PCT         = 85;              // bracos pre-acesos enquanto o caminho nao e conhecido
const int   PISO_PCT        = 70;              // piso CPTED, vale para cada poste
const float LIMIAR_DESGASTE = 0.70;
const unsigned long INTERVALO_TELEMETRIA_MS = 5000;
const unsigned long CARENCIA_FAILSAFE_MS    = 15000;  // queda maior que isso -> fail-safe

// ---------------- Estado compartilhado ----------------
struct Estado {
  int   luz;
  bool  noite;
  float dist;          // S1 (campo "dist" da telemetria, mantido do contrato original)
  bool  presenca;      // S1
  float dist2;         // S2
  bool  presenca2;     // S2
  float desgaste;
  int   pct;           // = pct do poste da base (campo "pct" do contrato original)
  int   pctPoste[3];
  const char* nome;
  int   rota;          // 0 = nenhuma, ESQ ou DIR
  const char* rotaFonte;
  bool  conectado;
  unsigned long semRedeDesde;  // millis() em que a rede caiu (0 = desde o boot)
  int   pedido;                // potencia solicitada pela central (0-100)
  int   rotaModelo;            // previsao recebida do ML para a travessia atual (0 = nenhuma)
  float confiancaModelo;
};
Estado est = {0, false, 999, false, 999, false, 0, 0, {0, 0, 0}, "INICIANDO", 0, "", false, 0, 40, 0, 0};
SemaphoreHandle_t mutexEstado;
SemaphoreHandle_t mutexSerial;

// Eventos que a tarefa de controle gera e a de comunicacao publica (PubSubClient nao e thread-safe)
struct Evento {
  bool  travessia;      // false = entrada (pede previsao), true = travessia completa
  float distS1;
  int   previsto;
  const char* fonte;
  int   real;           // 0 = desconhecido (sem S2)
  unsigned long duracaoMs;
  unsigned long uptime;
};
QueueHandle_t filaEventos;

WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

// =============================================================
//  Funcoes auxiliares
// =============================================================
// Serial protegido: uma tarefa nao "atropela" a linha da outra
void logf(const char* formato, ...) {
  char buf[320];
  va_list args;
  va_start(args, formato);
  vsnprintf(buf, sizeof(buf), formato, args);
  va_end(args);
  xSemaphoreTake(mutexSerial, portMAX_DELAY);
  Serial.println(buf);
  xSemaphoreGive(mutexSerial);
}

float distanciaCm(int trig, int echo) {
  digitalWrite(trig, LOW);  delayMicroseconds(2);
  digitalWrite(trig, HIGH); delayMicroseconds(10);
  digitalWrite(trig, LOW);
  unsigned long duracao = pulseIn(echo, HIGH, 6000);   // ~1 m: basta na maquete e a leitura vazia fica rapida
  if (duracao == 0) return 999;   // nada detectado
  float cm = duracao / 58.0;
  if (cm < 2) return 999;         // o HC-SR04 nao mede abaixo de 2 cm: eco falso
  return cm;
}

void setRGB(int r, int g, int b) {
  if (RGB_ANODO_COMUM) { r = 255 - r; g = 255 - g; b = 255 - b; }
  analogWrite(PINO_R, r);
  analogWrite(PINO_G, g);
  analogWrite(PINO_B, b);
}

void setConectado(bool valor) {
  xSemaphoreTake(mutexEstado, portMAX_DELAY);
  if (!valor && est.conectado) est.semRedeDesde = millis();  // acabou de cair
  est.conectado = valor;
  xSemaphoreGive(mutexEstado);
}

// =============================================================
//  TAREFA 1 - Sensores (a cada 60 ms)
// =============================================================
// Detector de presenca de um sensor: 2 leituras seguidas perto (um eco falso isolado nao
// conta) e a presenca dura TEMPO_PRESENCA_MS depois da ultima deteccao.
struct Detector {
  int leiturasPerto = 0;
  bool jaViu = false;           // evita o "pedestre fantasma" no boot
  unsigned long ultima = 0;
  bool atualizar(float dist, float limite) {
    if (dist < limite) leiturasPerto++;
    else               leiturasPerto = 0;
    if (leiturasPerto >= 2) { jaViu = true; ultima = millis(); }
    return jaViu && (millis() - ultima < TEMPO_PRESENCA_MS);
  }
};

void tarefaSensores(void* param) {
  Detector s1, s2;
  bool noite = false;

  for (;;) {
    int luz = analogRead(PINO_LDR);
    if (LDR_INVERTIDO) luz = 4095 - luz;
    // Histerese: escurece abaixo de LIMIAR_NOITE, mas so clareia acima de LIMIAR_DIA
    if (noite) { if (luz > LIMIAR_DIA) noite = false; }
    else if (luz < LIMIAR_NOITE) noite = true;

    // Um ultrassonico de cada vez, com pausa entre eles: disparados juntos, um ouve o eco do outro
    float dist1 = distanciaCm(PINO_TRIG_S1, PINO_ECHO_S1);
    bool presenca1 = s1.atualizar(dist1, DIST_PRESENCA_S1_CM);
    float dist2 = 999;
    bool presenca2 = false;
#if USAR_S2
    vTaskDelay(pdMS_TO_TICKS(25));
    dist2 = distanciaCm(PINO_TRIG_S2, PINO_ECHO_S2);
    presenca2 = s2.atualizar(dist2, DIST_PRESENCA_S2_CM);
#endif

    float desgaste = analogRead(PINO_POT) / 4095.0;

    xSemaphoreTake(mutexEstado, portMAX_DELAY);
    est.luz       = luz;
    est.noite     = noite;
    est.dist      = dist1;
    est.presenca  = presenca1;
    est.dist2     = dist2;
    est.presenca2 = presenca2;
    est.desgaste  = desgaste;
    xSemaphoreGive(mutexEstado);

    vTaskDelay(pdMS_TO_TICKS(USAR_S2 ? 35 : 60));   // ~60 ms entre disparos de cada sensor
  }
}

// =============================================================
//  TAREFA 2 - Controle da luz e da cascata (a cada 20 ms)
// =============================================================
void tarefaControle(void* param) {
  unsigned long ultimoLog = 0;

  // Travessia em andamento (uma por vez)
  bool travessia = false;
  bool confirmada = false;
  bool presencaAntes = false;
  unsigned long inicio = 0, confirmadaEm = 0;
  int previsto = 0, real = 0;
  const char* fonte = "";
  float distEntrada = 999;

  for (;;) {
    xSemaphoreTake(mutexEstado, portMAX_DELAY);
    Estado e = est;
    xSemaphoreGive(mutexEstado);
    unsigned long agora = millis();

    // ---------- cascata: detectar, prever, confirmar ----------
    bool novaEntrada = e.presenca && !presencaAntes;
    presencaAntes = e.presenca;

    // Entrada nova no S1 comeca outra travessia, mesmo que o braco da anterior ainda esteja aceso
    if (novaEntrada && (!travessia || confirmada)) {
      travessia = true;
      confirmada = false;
      inicio = agora;
      real = 0;
      distEntrada = e.dist;    // vai no evento: e uma das entradas do modelo de rota
      previsto = 0;            // sem previsao ate o modelo responder: os dois bracos pre-acendem
      fonte = "sem_previsao";
      xSemaphoreTake(mutexEstado, portMAX_DELAY);
      est.rotaModelo = 0;
      xSemaphoreGive(mutexEstado);
      e.rotaModelo = 0;
      Evento ev = {false, distEntrada, previsto, fonte, 0, 0, agora / 1000};
      xQueueSend(filaEventos, &ev, 0);   // pede a previsao do modelo
    }

    if (travessia && !confirmada) {
      // Previsao do ML chegou para esta travessia: so o braco previsto acende
      if (e.rotaModelo != 0) { previsto = e.rotaModelo; fonte = "modelo"; }

#if USAR_S2
      if (e.presenca2) { real = ESQ; confirmada = true; confirmadaEm = agora; }
      else if (agora - inicio > JANELA_ROTA_MS) { real = DIR; confirmada = true; confirmadaEm = agora; }
      if (confirmada) {
        Evento ev = {true, distEntrada, previsto, fonte, real, agora - inicio, agora / 1000};
        xQueueSend(filaEventos, &ev, 0);
      }
#else
      // Sem S2 nao ha confirmacao: o braco previsto fica aceso durante a janela
      if (agora - inicio > JANELA_ROTA_MS) {
        Evento ev = {true, distEntrada, previsto, fonte, 0, agora - inicio, agora / 1000};
        xQueueSend(filaEventos, &ev, 0);
        travessia = false;
      }
#endif
    }
    if (travessia && confirmada && agora - confirmadaEm > TEMPO_BRACO_MS) travessia = false;

    int bracoAceso = 0;          // braco que deve estar a 100% pela cascata
    bool preAcender = false;     // caminho ainda desconhecido: os dois bracos a PRE_PCT
    const char* rotaFonte = "";
    if (travessia) {
      if (confirmada)    { bracoAceso = real;     rotaFonte = "confirmada"; }
      else if (previsto) { bracoAceso = previsto; rotaFonte = fonte; }
      else               { preAcender = true;     rotaFonte = "aguardando"; }
    }

    // ---------- brilho de cada poste (regras de seguranca valem para todos) ----------
    bool falha = e.desgaste > LIMIAR_DESGASTE;
    unsigned long tempoSemRede = e.conectado ? 0 : (agora - e.semRedeDesde);
    bool failsafe = USAR_REDE && !e.conectado && tempoSemRede > CARENCIA_FAILSAFE_MS;
    int piso = max(e.pedido, PISO_PCT);

    int pct[3];
    const char* nome;
    if (!e.noite) {
      pct[BASE] = pct[ESQ] = pct[DIR] = 0;
      nome = "DIA";
    } else if (failsafe) {
      pct[BASE] = pct[ESQ] = pct[DIR] = 100;   // sem rede ha muito tempo -> tudo a 100%
      nome = "FAILSAFE";
    } else {
      int pre = max(PRE_PCT, piso);
      pct[BASE] = e.presenca ? 100 : piso;
      pct[ESQ]  = (bracoAceso == ESQ || e.presenca2) ? 100 : (preAcender ? pre : piso);
      pct[DIR]  = (bracoAceso == DIR) ? 100 : (preAcender ? pre : piso);
      bool pedestre = e.presenca || e.presenca2 || travessia;
      nome = pedestre ? "PEDESTRE" : (piso < 100 ? "DIMERIZADO" : "NOITE");
    }
    if (falha) nome = "FALHA";

    // Correcao gama: o olho nao percebe brilho de forma linear; a falha faz os postes cintilarem
    bool cintila = falha && random(100) < 30;
    for (int i = 0; i < 3; i++) {
      int duty = (int)(pow(pct[i] / 100.0, GAMMA_LUMINARIA) * 255 + 0.5);
      if (cintila && duty > 0) duty /= 4;
      analogWrite(PINOS_POSTE[i], duty);
    }

    // LED RGB de status
    if (falha)                                  setRGB(255, 0, 0);     // vermelho
    else if (strcmp(nome, "FAILSAFE") == 0)     setRGB(0, 0, 255);     // azul
    else if (strcmp(nome, "DIMERIZADO") == 0)   setRGB(255, 255, 0);   // amarelo
    else                                        setRGB(0, 255, 0);     // verde

    xSemaphoreTake(mutexEstado, portMAX_DELAY);
    est.pct = pct[BASE];
    for (int i = 0; i < 3; i++) est.pctPoste[i] = pct[i];
    est.nome = nome;
    est.rota = bracoAceso;
    est.rotaFonte = rotaFonte;
    xSemaphoreGive(mutexEstado);

    if (agora - ultimoLog >= 1000) {
      ultimoLog = agora;
      logf("[%s] luz=%d noite=%d S1=%.0fcm S2=%.0fcm desgaste=%.2f postes base/esq/dir=%d/%d/%d rota=%s %s%s",
           nome, e.luz, e.noite, e.dist, e.dist2, e.desgaste, pct[BASE], pct[ESQ], pct[DIR],
           NOME_LADO[bracoAceso], rotaFonte,
           !USAR_REDE ? " (teste local, sem rede)" : (e.conectado ? "" : " rede=0"));
    }

    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

// =============================================================
//  TAREFA 3 - Comunicacao (Wi-Fi + MQTT)
// =============================================================
void tratarComando(const char* msg) {
  // Aceita {"potencia":90} ou apenas 90
  int valor = -1;
  const char* p = strstr(msg, "potencia");
  if (p) {
    p = strchr(p, ':');
    if (p) valor = atoi(p + 1);
  } else if (isdigit(msg[0])) {
    valor = atoi(msg);
  }

  if (valor < 0 || valor > 100) {
    logf("[MQTT] comando ignorado: %s", msg);
    return;
  }

  xSemaphoreTake(mutexEstado, portMAX_DELAY);
  est.pedido = valor;
  xSemaphoreGive(mutexEstado);
  logf("[MQTT] comando recebido: potencia solicitada = %d%%", valor);
}

void tratarRota(const char* msg) {
  // Previsao do ML: {"direcao":"esquerda","confianca":0.82}
  int lado = strstr(msg, "esquerda") ? ESQ : (strstr(msg, "direita") ? DIR : 0);
  float confianca = 1.0;
  const char* p = strstr(msg, "confianca");
  if (p && (p = strchr(p, ':'))) confianca = atof(p + 1);
  if (lado == 0 || confianca < 0.5) {
    logf("[MQTT] previsao de rota ignorada: %s", msg);
    return;
  }
  xSemaphoreTake(mutexEstado, portMAX_DELAY);
  est.rotaModelo = lado;
  est.confiancaModelo = confianca;
  xSemaphoreGive(mutexEstado);
  logf("[MQTT] modelo preve %s (confianca %.2f)", NOME_LADO[lado], confianca);
}

void aoReceberMensagem(char* topico, byte* payload, unsigned int tamanho) {
  char msg[128];
  if (tamanho > sizeof(msg) - 1) tamanho = sizeof(msg) - 1;
  memcpy(msg, payload, tamanho);
  msg[tamanho] = '\0';
  if (strcmp(topico, TOPICO_ROTA) == 0) tratarRota(msg);
  else tratarComando(msg);
}

bool conectarMQTT() {
  char clientId[32];
  snprintf(clientId, sizeof(clientId), "g17-%s-%04X", POSTE_ID, (unsigned)random(0xFFFF));
  // LWT: se o poste cair, o broker publica "offline" sozinho
  bool ok = mqtt.connect(clientId, nullptr, nullptr, TOPICO_STATUS, 1, true, "offline");
  if (ok) {
    mqtt.publish(TOPICO_STATUS, "online", true);
    mqtt.subscribe(TOPICO_COMANDO);
    mqtt.subscribe(TOPICO_ROTA);
  }
  return ok;
}

void publicarTelemetria() {
  xSemaphoreTake(mutexEstado, portMAX_DELAY);
  Estado e = est;
  xSemaphoreGive(mutexEstado);

  // Campos originais primeiro e sem mudanca (dashboard e coletor dependem deles); os da
  // cascata vem no fim
  char json[420];
  snprintf(json, sizeof(json),
    "{\"id\":\"%s\",\"luz\":%d,\"noite\":%d,\"dist\":%.0f,\"presenca\":%d,"
    "\"desgaste\":%.2f,\"pct\":%d,\"estado\":\"%s\",\"pedido\":%d,\"uptime\":%lu,"
    "\"dist_s2\":%.0f,\"presenca_s2\":%d,\"pct_base\":%d,\"pct_esq\":%d,\"pct_dir\":%d,"
    "\"rota\":\"%s\",\"rota_fonte\":\"%s\"}",
    POSTE_ID, e.luz, e.noite, e.dist, e.presenca, e.desgaste,
    e.pct, e.nome, e.pedido, millis() / 1000,
    e.dist2, e.presenca2, e.pctPoste[BASE], e.pctPoste[ESQ], e.pctPoste[DIR],
    NOME_LADO[e.rota], e.rotaFonte);

  mqtt.publish(TOPICO_TELEMETRIA, json);
  logf("[MQTT] telemetria enviada: %s", json);
}

void publicarEvento(const Evento& ev) {
  char json[256];
  if (!ev.travessia) {
    snprintf(json, sizeof(json), "{\"id\":\"%s\",\"tipo\":\"entrada\",\"dist_s1\":%.1f,\"uptime\":%lu}",
             POSTE_ID, ev.distS1, ev.uptime);
    mqtt.publish(TOPICO_EVENTO, json);
  } else {
    snprintf(json, sizeof(json),
      "{\"id\":\"%s\",\"dist_s1\":%.1f,\"previsto\":\"%s\",\"fonte\":\"%s\",\"real\":\"%s\","
      "\"acertou\":%d,\"duracao_ms\":%lu,\"uptime\":%lu}",
      POSTE_ID, ev.distS1, NOME_LADO[ev.previsto], ev.fonte,
      ev.real ? NOME_LADO[ev.real] : "desconhecido",
      (ev.real && ev.previsto) ? (ev.real == ev.previsto) : -1, ev.duracaoMs, ev.uptime);
    mqtt.publish(TOPICO_TRAVESSIA, json);
  }
  logf("[MQTT] %s: %s", ev.travessia ? "travessia" : "evento", json);
}

void tarefaComunicacao(void* param) {
  // O Wi-Fi ja foi iniciado no setup(); aqui so acompanhamos e cuidamos do MQTT
  mqtt.setServer(MQTT_BROKER, MQTT_PORTA);
  mqtt.setCallback(aoReceberMensagem);
  mqtt.setBufferSize(512);
  mqtt.setSocketTimeout(3);   // espera no maximo 3 s pelo broker (watchdog e 5 s)
  mqtt.setKeepAlive(30);      // tolera simulador lento sem derrubar a conexao

  bool wifiAntes = false;
  bool mqttAntes = false;
  unsigned long ultimoAviso = 0;
  unsigned long ultimaTentativa = 0;
  unsigned long ultimaTelemetria = 0;

  for (;;) {
    bool wifiOk = (WiFi.status() == WL_CONNECTED);
    if (wifiOk != wifiAntes) {
      if (wifiOk) logf("[WiFi] conectado! IP: %s", WiFi.localIP().toString().c_str());
      else        logf("[WiFi] desconectado");
      wifiAntes = wifiOk;
    }

    if (!wifiOk) {
      setConectado(false);
      if (millis() - ultimoAviso > 5000) {
        ultimoAviso = millis();
        logf("[WiFi] ainda conectando... status=%d", WiFi.status());
      }
    } else if (!mqtt.connected()) {
      setConectado(false);
      if (mqttAntes) {
        logf("[MQTT] conexao com o broker caiu (codigo %d)", mqtt.state());
        mqttAntes = false;
      }
      if (ultimaTentativa == 0 || millis() - ultimaTentativa > 5000) {
        ultimaTentativa = millis();
        if (conectarMQTT()) {
          logf("[MQTT] conectado ao broker!");
          mqttAntes = true;
        } else {
          logf("[MQTT] falhou (codigo %d), tentando de novo em 5 s", mqtt.state());
        }
      }
    } else {
      setConectado(true);
      mqtt.loop();
      Evento ev;
      while (xQueueReceive(filaEventos, &ev, 0) == pdTRUE) publicarEvento(ev);
      if (millis() - ultimaTelemetria >= INTERVALO_TELEMETRIA_MS) {
        ultimaTelemetria = millis();
        publicarTelemetria();
      }
    }

    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

// =============================================================
//  Setup / Loop
// =============================================================
void setup() {
  Serial.begin(115200);

#if USAR_REDE
  // Wi-Fi iniciado antes das tarefas (mais confiavel no Wokwi)
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
#if SIMULACAO
  WiFi.begin(WIFI_SSID, WIFI_SENHA, 6);   // canal 6 acelera no Wokwi
#else
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
#endif
#endif

  for (int i = 0; i < 3; i++) pinMode(PINOS_POSTE[i], OUTPUT);
  pinMode(PINO_R, OUTPUT);
  pinMode(PINO_G, OUTPUT);
  pinMode(PINO_B, OUTPUT);
  pinMode(PINO_TRIG_S1, OUTPUT);
  pinMode(PINO_ECHO_S1, INPUT);
  pinMode(PINO_TRIG_S2, OUTPUT);
  pinMode(PINO_ECHO_S2, INPUT);

  randomSeed(esp_random());

  snprintf(TOPICO_TELEMETRIA, sizeof(TOPICO_TELEMETRIA), "g17/poste/%s/telemetria", POSTE_ID);
  snprintf(TOPICO_COMANDO,    sizeof(TOPICO_COMANDO),    "g17/poste/%s/comando",    POSTE_ID);
  snprintf(TOPICO_STATUS,     sizeof(TOPICO_STATUS),     "g17/poste/%s/status",     POSTE_ID);
  snprintf(TOPICO_EVENTO,     sizeof(TOPICO_EVENTO),     "g17/poste/%s/evento",     POSTE_ID);
  snprintf(TOPICO_ROTA,       sizeof(TOPICO_ROTA),       "g17/poste/%s/rota",       POSTE_ID);
  snprintf(TOPICO_TRAVESSIA,  sizeof(TOPICO_TRAVESSIA),  "g17/poste/%s/travessia",  POSTE_ID);

  mutexEstado = xSemaphoreCreateMutex();
  mutexSerial = xSemaphoreCreateMutex();
  filaEventos = xQueueCreate(8, sizeof(Evento));

  logf("Poste inteligente G17 v3.0 iniciado (cascata em Y, FreeRTOS + MQTT, S2 %s)", USAR_S2 ? "ligado" : "desligado");
#if USAR_REDE
  logf("[WiFi] conectando...");
#else
  logf("Modo teste local: sem Wi-Fi/MQTT, fail-safe de rede desligado, pedido fixo em %d%%", est.pedido);
#endif

  //                       funcao              nome          pilha  param prio handle nucleo
  xTaskCreatePinnedToCore(tarefaSensores,    "sensores",    4096,  NULL, 2,   NULL,  1);
  xTaskCreatePinnedToCore(tarefaControle,    "controle",    4096,  NULL, 3,   NULL,  1);
#if USAR_REDE
  xTaskCreatePinnedToCore(tarefaComunicacao, "comunicacao", 8192,  NULL, 1,   NULL,  0);
#endif
}

void loop() {
  vTaskDelete(NULL);   // tudo roda nas tarefas FreeRTOS
}
