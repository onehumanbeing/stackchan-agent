#include "net.h"

#include <ESPmDNS.h>
#include <WebSocketsServer.h>
#include <WiFi.h>

#include "settings.h"

namespace net {

namespace {
WebSocketsServer ws(WS_PORT);
TextHandler text_cb;
ClientHandler client_cb;
BinaryHandler binary_cb;
bool clients[MAX_CLIENTS];
bool mdns_up = false;
uint32_t next_try = 0;
int next_slot = 0;
constexpr uint32_t RETRY_MS = 8000;

void onEvent(uint8_t num, WStype_t type, uint8_t *payload, size_t len) {
  if (num >= MAX_CLIENTS) return;
  switch (type) {
    case WStype_CONNECTED: clients[num] = true; if (client_cb) client_cb(num, true); break;
    case WStype_DISCONNECTED: clients[num] = false; if (client_cb) client_cb(num, false); break;
    case WStype_TEXT: if (text_cb) text_cb(num, (const char *)payload, len); break;
    case WStype_BIN: if (binary_cb && len > 1) binary_cb(num, payload[0], payload + 1, len - 1); break;
    default: break;
  }
}

// Try the next saved network (round robin); the station keeps the last good one on its own.
void tryNext() {
  for (int k = 0; k < settings::MAX_WIFI; k++) {
    int i = (next_slot + k) % settings::MAX_WIFI;
    String s = settings::wifiSsid(i);
    if (s.isEmpty()) continue;
    next_slot = i + 1;
    WiFi.begin(s.c_str(), settings::wifiPass(i).c_str());
    return;
  }
}
}  // namespace

void begin(TextHandler on_text, ClientHandler on_client, BinaryHandler on_binary) {
  text_cb = on_text, client_cb = on_client, binary_cb = on_binary;
  WiFi.mode(WIFI_STA);
  WiFi.setHostname("stackchan");
  WiFi.setAutoReconnect(true);
  ws.begin();
  ws.onEvent(onEvent);
  tryNext();
  next_try = millis() + RETRY_MS;
}

void reconnect() {
  WiFi.disconnect();
  next_slot = 0;
  tryNext();
  next_try = millis() + RETRY_MS;
}

void loop() {
  ws.loop();
  if (WiFi.status() == WL_CONNECTED) {
    if (!mdns_up && MDNS.begin("stackchan")) {
      MDNS.addService("stackchan", "tcp", WS_PORT);
      mdns_up = true;
    }
    return;
  }
  if (mdns_up) MDNS.end(), mdns_up = false;
  if ((int32_t)(millis() - next_try) >= 0) {
    tryNext();
    next_try = millis() + RETRY_MS;
  }
}

bool connected() { return WiFi.status() == WL_CONNECTED; }
String ip() { return connected() ? WiFi.localIP().toString() : String(""); }
String ssid() { return connected() ? WiFi.SSID() : String(""); }
int rssi() { return connected() ? WiFi.RSSI() : 0; }

String scanJson() {
  int n = WiFi.scanNetworks();
  String out = "[";
  for (int i = 0; i < n; i++) {   // the driver returns them strongest first
    String s = WiFi.SSID(i);
    s.replace("\\", "\\\\"), s.replace("\"", "\\\"");
    out += (i ? "," : "") + String("{\"ssid\":\"") + s + "\",\"rssi\":" + WiFi.RSSI(i) +
           ",\"open\":" + (WiFi.encryptionType(i) == WIFI_AUTH_OPEN ? "true" : "false") + "}";
  }
  WiFi.scanDelete();
  return out + "]";
}

void send(int client, const char *text, size_t len) {
  if (client >= 0 && client < MAX_CLIENTS && clients[client]) ws.sendTXT(client, (const uint8_t *)text, len);
}

void sendBinary(int client, uint8_t type, const uint8_t *data, size_t len) {
  if (client < 0 || client >= MAX_CLIENTS || !clients[client]) return;
  uint8_t *buf = (uint8_t *)ps_malloc(len + 1);
  if (!buf) return;
  buf[0] = type;
  memcpy(buf + 1, data, len);
  ws.sendBIN(client, buf, len + 1);
  free(buf);
}

bool clientConnected(int client) { return client >= 0 && client < MAX_CLIENTS && clients[client]; }

}  // namespace net
