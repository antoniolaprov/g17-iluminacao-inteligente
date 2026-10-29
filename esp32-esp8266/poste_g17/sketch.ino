// =============================================================
//  Poste Inteligente G17 - v2.8 (FreeRTOS + Wi-Fi + MQTT)
//  CESAR School - Sistemas Embarcados
//
//  Hardware: a luminaria e um LED RGB aceso em branco. As tres cores
//  (R, G e B), cada uma com seu resistor, vao juntas no GPIO18, entao
//  um unico PWM controla o brilho. O segundo LED RGB (19/21/5) e o
//  indicador de status.
// =============================================================
#include <WiFi.h>
#include <PubSubClient.h>
#include <stdarg.h>

#define SIMULACAO 1   // 1 = Wokwi | 0 = placa fisica
#define USAR_REDE 1   // 1 = Wi-Fi + MQTT | 0 = teste local so com sensores e LEDs (sem fail-safe de rede)

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

// ---------------- Pinos ----------------
const int PINO_LED     = 18;   // luminaria: LED RGB com R, G e B juntos (branco)
const int PINO_R       = 19;   // LED RGB de status (antes 16/17/23)
const int PINO_G       = 21;
const int PINO_B       = 5;
const int PINO_TRIG    = 26;
const int PINO_ECHO    = 27;
const int PINO_LDR     = 34;
const int PINO_POT     = 35;
const int PINO_ONBOARD = 2;

// ---------------- Ajustes ----------------
#if SIMULACAO
const bool LDR_INVERTIDO = true;
const int  LIMIAR_NOITE  = 2000;
#else
const bool LDR_INVERTIDO = false;   // modulo fisico: mais luz = numero maior (testado em 27/10)
const int  LIMIAR_NOITE  = 2000;    // sala clara ~4095, dedo em cima ~0
#endif
const bool  RGB_ANODO_COMUM           = false;
const float DIST_PRESENCA_CM          = 50;
const unsigned long TEMPO_PRESENCA_MS = 10000;
const int   PISO_PCT                  = 70;     // piso CPTED
const float LIMIAR_DESGASTE           = 0.70;
const unsigned long INTERVALO_TELEMETRIA_MS = 5000;
const unsigned long CARENCIA_FAILSAFE_MS    = 15000;  // queda maior que isso -> fail-safe

// ---------------- Estado compartilhado ----------------
struct Estado {
  int   luz;
  bool  noite;
  float dist;
  bool  presenca;
  float desgaste;
  int   pct;
  const char* nome;
  bool  conectado;
  unsigned long semRedeDesde;  // millis() em que a rede caiu (0 = desde o boot)
  int   pedido;                // potencia solicitada pela central (0-100)
};
Estado est = {0, false, 0, false, 0, 0, "INICIANDO", false, 0, 40};
SemaphoreHandle_t mutexEstado;
SemaphoreHandle_t mutexSerial;

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

float distanciaCm() {
  digitalWrite(PINO_TRIG, LOW);  delayMicroseconds(2);
  digitalWrite(PINO_TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(PINO_TRIG, LOW);
  unsigned long duracao = pulseIn(PINO_ECHO, HIGH, 30000);
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
//  TAREFA 1 - Sensores (a cada 100 ms)
// =============================================================
void tarefaSensores(void* param) {
  bool jaViuPedestre = false;          // evita o "pedestre fantasma" no boot
  unsigned long ultimaPresenca = 0;
  int leiturasPerto = 0;               // leituras seguidas abaixo do limite

  for (;;) {
    int luz = analogRead(PINO_LDR);
    if (LDR_INVERTIDO) luz = 4095 - luz;

    float dist = distanciaCm();
    // So conta pedestre com 2 leituras seguidas perto: um eco falso isolado nao acende a luz
    if (dist < DIST_PRESENCA_CM) leiturasPerto++;
    else                         leiturasPerto = 0;
    if (leiturasPerto >= 2) {
      jaViuPedestre = true;
      ultimaPresenca = millis();
    }
    bool presenca = jaViuPedestre && (millis() - ultimaPresenca < TEMPO_PRESENCA_MS);

    float desgaste = analogRead(PINO_POT) / 4095.0;

    xSemaphoreTake(mutexEstado, portMAX_DELAY);
    est.luz      = luz;
    est.noite    = luz < LIMIAR_NOITE;
    est.dist     = dist;
    est.presenca = presenca;
    est.desgaste = desgaste;
    xSemaphoreGive(mutexEstado);

    vTaskDelay(pdMS_TO_TICKS(100));
  }
}

// =============================================================
//  TAREFA 2 - Controle da luz (a cada 50 ms)
// =============================================================
void tarefaControle(void* param) {
  unsigned long ultimoLog = 0;

  for (;;) {
    xSemaphoreTake(mutexEstado, portMAX_DELAY);
    Estado e = est;
    xSemaphoreGive(mutexEstado);

    bool falha = e.desgaste > LIMIAR_DESGASTE;

    // Fail-safe so entra se a rede estiver fora por mais que a carencia
    unsigned long tempoSemRede = e.conectado ? 0 : (millis() - e.semRedeDesde);
    bool failsafe = USAR_REDE && !e.conectado && tempoSemRede > CARENCIA_FAILSAFE_MS;

    int pct;
    const char* nome;

    if (!e.noite)        { pct = 0;   nome = "DIA"; }
    else if (failsafe)   { pct = 100; nome = "FAILSAFE"; }   // sem rede ha muito tempo -> 100%
    else if (e.presenca) { pct = 100; nome = "PEDESTRE"; }
    else {
      pct  = max(e.pedido, PISO_PCT);
      nome = (pct < 100) ? "DIMERIZADO" : "NOITE";
    }
    if (falha) nome = "FALHA";

    // LED principal (com cintilacao se houver falha)
    int duty = pct * 255 / 100;
    if (falha && duty > 0 && random(100) < 30) duty /= 4;
    analogWrite(PINO_LED, duty);

    // LED RGB de status
    if (falha)                                  setRGB(255, 0, 0);     // vermelho
    else if (strcmp(nome, "FAILSAFE") == 0)     setRGB(0, 0, 255);     // azul
    else if (strcmp(nome, "DIMERIZADO") == 0)   setRGB(255, 255, 0);   // amarelo
    else                                        setRGB(0, 255, 0);     // verde

    digitalWrite(PINO_ONBOARD, e.conectado ? HIGH : LOW);

    xSemaphoreTake(mutexEstado, portMAX_DELAY);
    est.pct  = pct;
    est.nome = nome;
    xSemaphoreGive(mutexEstado);

    if (millis() - ultimoLog >= 1000) {
      ultimoLog = millis();
      if (!USAR_REDE) {
        logf("[%s] luz=%d noite=%d dist=%.0f presenca=%d desgaste=%.2f pct=%d (teste local, sem rede)",
             nome, e.luz, e.noite, e.dist, e.presenca, e.desgaste, pct);
      } else if (e.conectado) {
        logf("[%s] luz=%d noite=%d dist=%.0f presenca=%d desgaste=%.2f pct=%d pedido=%d rede=1",
             nome, e.luz, e.noite, e.dist, e.presenca, e.desgaste, pct, e.pedido);
      } else {
        logf("[%s] luz=%d noite=%d dist=%.0f presenca=%d desgaste=%.2f pct=%d pedido=%d rede=0 (sem rede ha %lus)",
             nome, e.luz, e.noite, e.dist, e.presenca, e.desgaste, pct, e.pedido, tempoSemRede / 1000);
      }
    }

    vTaskDelay(pdMS_TO_TICKS(50));
  }
}

// =============================================================
//  TAREFA 3 - Comunicacao (Wi-Fi + MQTT)
// =============================================================
void aoReceberMensagem(char* topico, byte* payload, unsigned int tamanho) {
  char msg[64];
  if (tamanho > 63) tamanho = 63;
  memcpy(msg, payload, tamanho);
  msg[tamanho] = '\0';

  // Aceita {"potencia":90} ou apenas 90
  int valor = -1;
  char* p = strstr(msg, "potencia");
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

bool conectarMQTT() {
  char clientId[32];
  snprintf(clientId, sizeof(clientId), "g17-%s-%04X", POSTE_ID, (unsigned)random(0xFFFF));
  // LWT: se o poste cair, o broker publica "offline" sozinho
  bool ok = mqtt.connect(clientId, nullptr, nullptr, TOPICO_STATUS, 1, true, "offline");
  if (ok) {
    mqtt.publish(TOPICO_STATUS, "online", true);
    mqtt.subscribe(TOPICO_COMANDO);
  }
  return ok;
}

void publicarTelemetria() {
  xSemaphoreTake(mutexEstado, portMAX_DELAY);
  Estado e = est;
  xSemaphoreGive(mutexEstado);

  char json[256];
  snprintf(json, sizeof(json),
    "{\"id\":\"%s\",\"luz\":%d,\"noite\":%d,\"dist\":%.0f,\"presenca\":%d,"
    "\"desgaste\":%.2f,\"pct\":%d,\"estado\":\"%s\",\"pedido\":%d,\"uptime\":%lu}",
    POSTE_ID, e.luz, e.noite, e.dist, e.presenca, e.desgaste,
    e.pct, e.nome, e.pedido, millis() / 1000);

  mqtt.publish(TOPICO_TELEMETRIA, json);
  logf("[MQTT] telemetria enviada: %s", json);
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

  pinMode(PINO_LED, OUTPUT);
  pinMode(PINO_R, OUTPUT);
  pinMode(PINO_G, OUTPUT);
  pinMode(PINO_B, OUTPUT);
  pinMode(PINO_TRIG, OUTPUT);
  pinMode(PINO_ECHO, INPUT);
  pinMode(PINO_ONBOARD, OUTPUT);

  randomSeed(esp_random());

  snprintf(TOPICO_TELEMETRIA, sizeof(TOPICO_TELEMETRIA), "g17/poste/%s/telemetria", POSTE_ID);
  snprintf(TOPICO_COMANDO,    sizeof(TOPICO_COMANDO),    "g17/poste/%s/comando",    POSTE_ID);
  snprintf(TOPICO_STATUS,     sizeof(TOPICO_STATUS),     "g17/poste/%s/status",     POSTE_ID);

  mutexEstado = xSemaphoreCreateMutex();
  mutexSerial = xSemaphoreCreateMutex();

  logf("Poste inteligente G17 v2.8 iniciado (FreeRTOS + MQTT)");
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
