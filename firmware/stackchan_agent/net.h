// Wi-Fi station (networks from NVS, strongest first), mDNS stackchan.local, WebSocket server :81.
// Each WebSocket text frame is one protocol line (docs/protocol.md).
#pragma once
#include <Arduino.h>
#include <functional>

namespace net {

constexpr uint16_t WS_PORT = 81;
constexpr int MAX_CLIENTS = 4;

using TextHandler = std::function<void(int client, const char *text, size_t len)>;
using ClientHandler = std::function<void(int client, bool connected)>;

void begin(TextHandler on_text, ClientHandler on_client);
void loop();                    // call often: reconnects, serves WebSocket
void reconnect();               // after the network list changed
bool connected();
String ip();
String ssid();
int rssi();
String scanJson();              // [{"ssid":..,"rssi":..,"open":..}], strongest first (blocks ~2 s)
void send(int client, const char *text, size_t len);
void sendBinary(int client, const uint8_t *data, size_t len);   // camera JPEG frames
bool clientConnected(int client);

}  // namespace net
