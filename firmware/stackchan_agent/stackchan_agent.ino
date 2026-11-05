// StackChan agent firmware (M5Stack CoreS3): face + STS bus servos + NDJSON protocol over USB and Wi-Fi.
// Build / flash: ../../flash.sh.  Protocol: ../../docs/protocol.md.
#include <M5Unified.h>

#include "audio.h"
#include "camera.h"
#include "commands.h"
#include "face.h"
#include "net.h"

namespace {
char usb_line[1024];
size_t usb_len = 0;

void pollUsb() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (usb_len) commands::handleLine(commands::USB, usb_line, usb_len);
      usb_len = 0;
    } else if (usb_len < sizeof(usb_line) - 1) {
      usb_line[usb_len++] = c;
    }
  }
}
}  // namespace

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);
  M5.Power.setExtOutput(true);   // 5 V on the Grove ports (the bus adapter may take its logic power from there)
  Serial.begin(115200);
  face::begin();
  audio::begin();
  bool cam = camera::begin();
  commands::begin();
  if (!cam) face::say("camera failed", 4000);
  net::begin([](int ch, const char *text, size_t len) { commands::handleLine(ch, text, len); },
             [](int ch, bool connected) { commands::onClient(ch, connected); },
             [](int ch, uint8_t type, const uint8_t *data, size_t len) { if (type == 'S') audio::play(data, len); });
  commands::hello(commands::USB);
}

void loop() {
  M5.update();
  pollUsb();
  net::loop();
  commands::loop();
  audio::loop();
  face::loop();
  static bool was_connected = false;
  if (net::connected() != was_connected) {
    was_connected = net::connected();
    face::say(was_connected ? net::ip() : String("wifi lost"), 5000);
  }
  delay(1);
}
