#include <WiFi.h>
#include <WebServer.h>

const char* ssid = "Shone";
const char* password = "12345678";

#define BUZZER 25
#define LED1   26   // RED LED (Hazard Indicator)
#define LED2   27   // GREEN LED (Normal/Safe Indicator)

WebServer server(80);

String hazard = "NONE";
bool isAlertActive = false;
unsigned long lastAlertTime = 0;
const unsigned long ALERT_TIMEOUT_MS = 2000; // Auto-silence buzzer if no hazard for 2s

// -------------------------------------------------------------
// HAZARD ALERT: Turn ON Buzzer, Turn ON Red LED, Turn OFF Green
// -------------------------------------------------------------
void alert(String type) {
  hazard = type;
  isAlertActive = true;
  lastAlertTime = millis();

  digitalWrite(BUZZER, HIGH); // Buzzer ON
  digitalWrite(LED1, HIGH);   // Red LED ON
  digitalWrite(LED2, LOW);    // Green LED OFF

  Serial.println("🚨 [HAZARD ACTIVE]: " + type + " -> BUZZER ON, RED LED ON");
  server.send(200, "text/plain", "OK_" + type);
}

// -------------------------------------------------------------
// NORMAL STATE: Turn OFF Buzzer, Turn OFF Red LED, Turn ON Green
// -------------------------------------------------------------
void normal() {
  hazard = "NONE";
  isAlertActive = false;

  digitalWrite(BUZZER, LOW);  // Buzzer OFF
  digitalWrite(LED1, LOW);   // Red LED OFF (back to previous stage)
  digitalWrite(LED2, HIGH);  // Green LED ON (Safe)

  Serial.println("✅ [ALL CLEAR]: Hazards gone -> BUZZER OFF, RED LED OFF, GREEN ON");
  server.send(200, "text/plain", "OK_NORMAL");
}

void status() {
  String json = "{\"hazard\":\"" + hazard + "\",\"buzzer\":" + String(isAlertActive ? "true" : "false") + "}";
  server.send(200, "application/json", json);
}

void setup() {
  Serial.begin(115200);

  pinMode(BUZZER, OUTPUT);
  pinMode(LED1, OUTPUT);
  pinMode(LED2, OUTPUT);

  // Initial State: Safe / Normal
  digitalWrite(BUZZER, LOW);
  digitalWrite(LED1, LOW);
  digitalWrite(LED2, HIGH);

  WiFi.begin(ssid, password);
  Serial.print("Connecting to Wi-Fi");

  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }

  Serial.println("\n✅ Connected to Wi-Fi!");
  Serial.print("📡 ESP32 IP: ");
  Serial.println(WiFi.localIP());

  server.on("/", []() {
    server.send(200, "text/plain", "CivicSense ESP32 Online");
  });

  server.on("/pothole",  []() { alert("POTHOLE"); });
  server.on("/fire",     []() { alert("FIRE"); });
  server.on("/smoke",    []() { alert("SMOKE"); });
  server.on("/overflow", []() { alert("OVERFLOW"); });
  server.on("/normal",   normal);
  server.on("/status",   status);

  server.begin();
  Serial.println("🌐 HTTP Alert Server Ready on port 80.");
}

void loop() {
  server.handleClient();

  // Watchdog: When hazard signal is gone and no alert received within 2s,
  // automatically turn off buzzer and return to normal!
  if (isAlertActive && (millis() - lastAlertTime > ALERT_TIMEOUT_MS)) {
    normal();
  }
}