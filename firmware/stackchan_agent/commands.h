// The protocol (docs/protocol.md): one JSON object per line, the same over USB serial and WebSocket.
// Channel USB = -1, WebSocket clients 0..net::MAX_CLIENTS-1.
#pragma once
#include <Arduino.h>

namespace commands {

constexpr int USB = -1;
constexpr const char *FW_VERSION = "0.1.0";

void begin();                                          // finds the servo bus (saved pins first)
void loop();                                           // state streams
void handleLine(int ch, const char *line, size_t len);
void onClient(int ch, bool connected);                 // hello on connect, drops the stream on close
void hello(int ch);
bool moveHead(int hid, int raw, int ms);              // head servo 1 (yaw) / 2 (pitch), raw 0..1023, travel ms
void moveArms(const uint8_t *ids, const int *raws, int n, int speed, int acc);   // one sync write, soft limits applied

}  // namespace commands
