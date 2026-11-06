#include "commands.h"

#include <ArduinoJson.h>
#include <M5Unified.h>
#include <WiFi.h>
#include <mbedtls/base64.h>

#include "audio.h"
#include "camera.h"
#include "dance.h"
#include "face.h"
#include "net.h"
#include "settings.h"
#include "sts_bus.h"

namespace commands {

namespace {
sts::Bus bus;
// M5Stack StackChan body: two SCS0009 head servos (1 = yaw, 2 = pitch) on their own bus, GPIO7 RX / GPIO6 TX.
// Same packets as STS, but registers are big endian and positions are 0..1023 over 300 degrees.
sts::Bus head(Serial2);
constexpr int HEAD_RX = 7, HEAD_TX = 6;
// The body switches the head servos' supply through a PY32 IO expander (internal I2C 0x6F, pin 0 = VM_EN). The stock
// firmware turns it on at boot; without it the head is limp after a full power-off.
constexpr uint8_t PY32 = 0x6F, PY32_VERSION = 0x02, PY32_DIR = 0x03, PY32_OUT = 0x05, PY32_PU = 0x09, PY32_PD = 0x0B, VM_EN = 1;
constexpr uint32_t PY32_HZ = 100000;

bool headPower(bool on) {
  uint8_t v = M5.In_I2C.readRegister8(PY32, PY32_VERSION, PY32_HZ);
  if (v == 0 || v == 0xFF) return false;       // no StackChan body
  M5.In_I2C.bitOn(PY32, PY32_DIR, VM_EN, PY32_HZ);
  M5.In_I2C.bitOff(PY32, PY32_PD, VM_EN, PY32_HZ);
  M5.In_I2C.bitOn(PY32, PY32_PU, VM_EN, PY32_HZ);
  return on ? M5.In_I2C.bitOn(PY32, PY32_OUT, VM_EN, PY32_HZ) : M5.In_I2C.bitOff(PY32, PY32_OUT, VM_EN, PY32_HZ);
}

struct Pins { int rx, tx; const char *port; };
constexpr Pins CANDIDATES[] = {   // CoreS3 Grove ports, both TX/RX orders
  {18, 17, "C"}, {17, 18, "C"}, {1, 2, "A"}, {2, 1, "A"}, {8, 9, "B"}, {9, 8, "B"},
};
const char *bus_port = "";

struct Stream {
  int hz = 0; uint8_t ids[16]; int n = 0; uint32_t next = 0; uint16_t bad = 0;
  uint32_t cam_ms = 0, cam_next = 0, cam_seq = 0;   // camera frames (WebSocket only)
};
Stream streams[1 + net::MAX_CLIENTS];   // [0] = USB
Stream &streamFor(int ch) { return streams[ch + 1]; }

float toDeg(int raw) { return (raw - 2048) * 360.0f / 4096.0f; }
int toRaw(float deg) { return lroundf(deg * 4096.0f / 360.0f) + 2048; }

// base64 of a heap buffer (freed here) into r[key]
void putBase64(JsonObject r, const char *key, uint8_t *data, size_t n) {
  size_t out = 0;
  mbedtls_base64_encode(nullptr, 0, &out, data, n);
  char *b = (char *)ps_malloc(out + 1);
  if (b && mbedtls_base64_encode((uint8_t *)b, out + 1, &out, data, n) == 0) b[out] = 0, r[key] = (const char *)b;
  r["bytes"] = n;
  free(b);
  free(data);
}

void emit(int ch, JsonDocument &doc) {
  String s;
  serializeJson(doc, s);
  if (ch == USB) {
    s += '\n';
    Serial.write((const uint8_t *)s.c_str(), s.length());
  } else {
    net::send(ch, s.c_str(), s.length());
  }
}

bool detectBus() {
  settings::BusCfg c = settings::bus();
  if (c.rx >= 0 && bus.begin(c.rx, c.tx, c.baud)) {
    for (const auto &p : CANDIDATES) if (p.rx == c.rx && p.tx == c.tx) bus_port = p.port;
    return true;
  }
  for (const auto &p : CANDIDATES) {
    if (!bus.begin(p.rx, p.tx, 1000000)) continue;
    bus_port = p.port;
    settings::setBus({p.rx, p.tx, 1000000});
    return true;
  }
  bus.end();
  bus_port = "";
  return false;
}

void stateJson(JsonObject o, int id, const sts::State &s) {
  o["id"] = id, o["pos"] = s.pos, o["deg"] = roundf(toDeg(s.pos) * 10) / 10, o["speed"] = s.speed;
  o["load"] = s.load, o["volt"] = s.volt, o["temp"] = s.temp, o["moving"] = s.moving;
  if (s.status) o["status"] = s.status;
}

// Goal in raw steps from args (raw or deg), clamped to the servo's soft limits.
int goal(JsonVariantConst a, int id, bool &clamped) {
  int raw = a["raw"].is<int>() ? a["raw"].as<int>() : toRaw(a["deg"] | 0.0f);
  int lo, hi;
  settings::limits(id, lo, hi);
  clamped = raw < lo || raw > hi;
  return constrain(raw, lo, hi);
}

void sysInfo(JsonObject r) {
  r["fw"] = FW_VERSION, r["mac"] = WiFi.macAddress(), r["uptime_s"] = millis() / 1000, r["heap"] = ESP.getFreeHeap();
  JsonObject w = r["wifi"].to<JsonObject>();
  w["connected"] = net::connected(), w["ssid"] = net::ssid(), w["ip"] = net::ip(), w["rssi"] = net::rssi();
  JsonObject b = r["bus"].to<JsonObject>();
  b["ok"] = bus.ok(), b["port"] = bus_port, b["rx"] = bus.rx(), b["tx"] = bus.tx(), b["baud"] = bus.baud();
  b["errors"] = bus.errors();
  JsonObject hp = r["head_power"].to<JsonObject>();
  hp["py32"] = M5.In_I2C.readRegister8(PY32, PY32_VERSION, PY32_HZ), hp["out"] = M5.In_I2C.readRegister8(PY32, PY32_OUT, PY32_HZ);
  r["face"] = face::expression(), r["face_style"] = face::style(), r["camera"] = camera::ok();
}

// Runs one command; returns an error string or nullptr.  Results go into r.
const char *run(int ch, const String &cmd, JsonVariantConst a, JsonObject r) {
  if (cmd == "ping") { r["pong"] = millis(); return nullptr; }
  if (cmd == "hello" || cmd == "sys.info") { sysInfo(r); return nullptr; }
  if (cmd == "sys.reboot") { Serial.flush(); delay(50); ESP.restart(); }

  if (cmd == "bus.detect") { settings::setBus({}); r["found"] = detectBus(); sysInfo(r); return nullptr; }
  if (cmd == "bus.probe") {     // raw bytes per pin pair / baud: tells wiring, echo and baud problems apart
    static const uint32_t BAUDS[] = {1000000, 500000, 115200};
    JsonArray out = r["probes"].to<JsonArray>();
    uint8_t buf[48];
    for (const auto &p : CANDIDATES) for (uint32_t b : BAUDS) {
      int n = bus.probe(p.rx, p.tx, b, buf, sizeof(buf));
      if (!n) continue;
      JsonObject o = out.add<JsonObject>();
      o["port"] = p.port, o["rx"] = p.rx, o["tx"] = p.tx, o["baud"] = b;
      char hex[3 * sizeof(buf) + 1] = "";
      for (int i = 0; i < n; i++) sprintf(hex + 3 * i, "%02X ", buf[i]);
      o["bytes"] = hex;
    }
    detectBus();
    return nullptr;
  }
  if (cmd == "bus.scan") {
    if (!bus.ok() && !detectBus()) return "bus not found (check the adapter wiring and its UART switch)";
    uint32_t e0 = bus.errors();
    JsonArray ids = r["ids"].to<JsonArray>();
    for (int id = a["from"] | 0; id <= (a["to"] | 253); id++) if (bus.ping(id)) ids.add(id);
    r["checksum_errors"] = bus.errors() - e0;   // > 0 usually means two servos share an id
    return nullptr;
  }

  int id = a["id"] | -1;
  if (cmd == "servo.read") {
    sts::State s;
    if (!bus.readState(id, s)) return "no reply";
    stateJson(r, id, s);
    int lo, hi;
    settings::limits(id, lo, hi);
    r["limits_deg"][0] = toDeg(lo), r["limits_deg"][1] = toDeg(hi);
    return nullptr;
  }
  if (cmd == "servo.move") {
    bool clamped;
    int raw = goal(a, id, clamped);
    if (!bus.move(id, raw, a["speed"] | 600, a["acc"] | 20)) return "no reply";
    r["raw"] = raw, r["deg"] = toDeg(raw), r["clamped"] = clamped;
    return nullptr;
  }
  if (cmd == "servo.sync_move") {
    uint8_t ids[8];
    int raws[8], n = 0;
    for (JsonVariantConst t : a["targets"].as<JsonArrayConst>()) {
      if (n == 8) break;
      bool clamped;
      ids[n] = t["id"] | 0;
      raws[n] = goal(t, ids[n], clamped);
      n++;
    }
    bus.syncMove(ids, raws, n, a["speed"] | 600, a["acc"] | 20);
    r["count"] = n;
    return nullptr;
  }
  if (cmd == "servo.torque") return bus.torque(id, a["on"] | true) ? nullptr : "no reply";
  if (cmd == "servo.torque_limit") return bus.write16(id, sts::TORQUE_LIMIT, constrain(a["permille"] | 1000, 0, 1000)) ? nullptr : "no reply";
  if (cmd == "servo.set_id") {
    int to = a["new_id"] | -1;
    if (to < 0 || to > 253) return "new_id must be 0..253";
    if (bus.ping(to)) return "new_id is already on the bus";
    return bus.setId(id, to) && bus.ping(to) ? nullptr : "set_id failed";
  }
  if (cmd == "servo.center") {   // so that moves around here never meet the 0/360 wrap (position mode cannot cross it)
    sts::State st;
    if (!bus.center(id) || !bus.readState(id, st) || abs(st.pos - 2048) > 8) return "center failed";
    stateJson(r, id, st);
    return nullptr;
  }
  if (cmd == "servo.limits") {
    if (!a["lo_deg"].isNull() && !a["hi_deg"].isNull()) settings::setLimits(id, toRaw(a["lo_deg"]), toRaw(a["hi_deg"]));
    int lo, hi;
    settings::limits(id, lo, hi);
    r["lo_deg"] = toDeg(lo), r["hi_deg"] = toDeg(hi);
    return nullptr;
  }

  if (cmd == "dance.play") return dance::play(a["name"] | "dance_1");
  if (cmd == "dance.stop") { dance::stop(); return nullptr; }
  if (cmd == "dance.status") { dance::status(r); return nullptr; }
  if (cmd == "dance.list") { dance::list(r); return nullptr; }
  if (cmd == "dance.delete") return dance::remove(a["name"] | "") ? nullptr : "no such dance";

  if (cmd == "mic.start") {      // WebSocket only: 'A' binary frames, 16 kHz mono int16, 40 ms each
    if (ch == USB) return "mic streams over WebSocket only";
    if (dance::playing()) return "it is dancing";
    if (!audio::micStart(ch)) return "speaker is still playing";
    r["rate"] = audio::RATE, r["chunk"] = audio::CHUNK;
    return nullptr;
  }
  if (cmd == "mic.stop") { audio::micStop(); return nullptr; }
  if (cmd == "speaker.stop") { audio::stop(); return nullptr; }
  if (cmd == "speaker.volume") { audio::setVolume(a["volume"] | 180); return nullptr; }
  if (cmd == "speaker.status") { r["playing"] = audio::playing(); r["mic"] = audio::micClient() >= 0; return nullptr; }
  if (cmd == "head.power") { r["ok"] = headPower(a["on"] | true); return nullptr; }   // {"on": false} = limp head
  if (cmd == "head.read") {   // raw 0..1023, deg = (raw - 512) * 300 / 1024
    JsonArray out = r["servos"].to<JsonArray>();
    for (int hid = 1; hid <= 2; hid++) {
      uint8_t b[2];
      if (!head.read(hid, sts::PRESENT_POS, b, 2)) continue;
      int raw = b[0] << 8 | b[1];
      JsonObject o = out.add<JsonObject>();
      o["id"] = hid, o["raw"] = raw, o["deg"] = roundf((raw - 512) * 3000.0f / 1024) / 10;
    }
    return nullptr;
  }
  if (cmd == "head.move") {   // id (1 yaw, 2 pitch), raw (0..1023) or deg, ms (travel time)
    int hid = a["id"] | 0;
    if (hid < 1 || hid > 2) return "id must be 1 (yaw) or 2 (pitch)";
    int raw = a["raw"].is<int>() ? a["raw"].as<int>() : 512 + lroundf((a["deg"] | 0.0f) * 1024 / 300);
    raw = constrain(raw, 0, 1023);
    if (!moveHead(hid, raw, a["ms"] | 400)) return "no reply";
    r["raw"] = raw;
    return nullptr;
  }
  if (cmd == "head.torque") {
    int hid = a["id"] | 0;
    if (!head.write8(hid, sts::TORQUE_ENABLE, a["on"] | false ? 1 : 0)) return "no reply";
    return nullptr;
  }
  if (cmd == "stream.start") {
    Stream &s = streamFor(ch);
    s.hz = constrain(a["hz"] | 20, 1, 100), s.n = 0, s.next = millis(), s.bad = 0;
    for (JsonVariantConst v : a["ids"].as<JsonArrayConst>()) if (s.n < 16) s.ids[s.n++] = v.as<int>();
    r["hz"] = s.hz, r["count"] = s.n;
    return s.n ? nullptr : "ids is empty";
  }
  if (cmd == "stream.stop") { streamFor(ch).hz = 0; return nullptr; }

  if (cmd == "face.set") {
    if (a["expression"].is<const char *>() && !face::setExpression(a["expression"].as<String>())) return "unknown expression";
    if (a["style"].is<const char *>() && !face::setStyle(a["style"].as<String>())) return "unknown style";
    if (a["blink"] | false) face::blink();
    if (a["gaze"].is<JsonArrayConst>()) face::gaze(a["gaze"][0] | 0.0f, a["gaze"][1] | 0.0f);
    if (!a["mouth"].isNull()) face::mouth(a["mouth"] | 0.0f);
    if (!a["say"].isNull()) face::say(a["say"].as<String>(), a["ms"] | 0);
    if (!a["idle"].isNull()) face::setIdle(a["idle"] | true);
    face::touch();
    r["expression"] = face::expression(), r["style"] = face::style(), r["idle"] = face::idle();
    return nullptr;
  }
  if (cmd == "face.styles") { r["styles"] = serialized(face::styleNames()); return nullptr; }
  if (cmd == "face.expressions") { r["expressions"] = serialized(face::expressionNames()); return nullptr; }
  if (cmd == "face.snap") {
    size_t n = 0;
    uint8_t *jpg = face::snapJpeg(&n);
    if (!jpg) return "snapshot failed";
    putBase64(r, "jpeg", jpg, n);
    return nullptr;
  }

  if (cmd == "camera.snap") {
    if (!camera::ok()) return "camera not available";
    if (!a["quality"].isNull()) camera::setQuality(a["quality"]);
    uint8_t *jpg;
    size_t n;
    uint32_t seq;
    if (!camera::latest(streamFor(ch).cam_seq, &jpg, &n, &seq, 2000)) return "no frame";
    putBase64(r, "jpeg", jpg, n);
    r["seq"] = seq;
    return nullptr;
  }
  if (cmd == "camera.start") {
    if (ch == USB) return "camera.start is WebSocket only (use camera.snap over USB)";
    if (!camera::ok()) return "camera not available";
    Stream &s = streamFor(ch);
    int fps = constrain(a["fps"] | 5, 1, 15);
    if (!a["quality"].isNull()) camera::setQuality(a["quality"]);
    s.cam_ms = 1000 / fps, s.cam_next = millis();
    r["fps"] = fps, r["quality"] = camera::quality();
    return nullptr;
  }
  if (cmd == "camera.stop") { streamFor(ch).cam_ms = 0; return nullptr; }
  if (cmd == "camera.config") {
    if (!a["quality"].isNull()) camera::setQuality(a["quality"]);
    if (!a["hmirror"].isNull() || !a["vflip"].isNull()) camera::setFlip(a["hmirror"] | false, a["vflip"] | false);
    r["quality"] = camera::quality();
    return nullptr;
  }

  if (cmd == "wifi.scan") { r["networks"] = serialized(net::scanJson()); return nullptr; }
  if (cmd == "wifi.set") {
    if (ch != USB) return "wifi.set is USB only";
    String ssid = a["ssid"] | "", pass = a["pass"] | "";
    if (ssid.isEmpty()) return "ssid is empty";
    if (!settings::addWifi(ssid, pass)) return "all wifi slots are used: forget one first";
    net::reconnect();
    return nullptr;
  }
  if (cmd == "wifi.forget") { if (!settings::forgetWifi(a["ssid"] | "")) return "not saved"; net::reconnect(); return nullptr; }
  if (cmd == "wifi.list") {
    JsonArray l = r["saved"].to<JsonArray>();
    for (int i = 0; i < settings::MAX_WIFI; i++) if (!settings::wifiSsid(i).isEmpty()) l.add(settings::wifiSsid(i));
    return nullptr;
  }
  if (cmd == "wifi.status") { sysInfo(r); return nullptr; }
  return "unknown command";
}
}  // namespace

// Holding a pose, the head servos hum. They hold it by friction, so relax them HEAD_RELAX_MS after the last move;
// the next move turns torque back on.
constexpr uint32_t HEAD_RELAX_MS = 3000;
uint32_t head_moved_at = 0;
bool head_tight = false;

void relaxHeadWhenIdle() {
  if (!head_tight || millis() - head_moved_at < HEAD_RELAX_MS) return;
  for (int hid = 1; hid <= 2; hid++) head.write8(hid, sts::TORQUE_ENABLE, 0);
  head_tight = false;
}

bool moveHead(int hid, int raw, int ms) {
  raw = constrain(raw, 0, 1023);
  head_moved_at = millis() + ms, head_tight = true;
  uint8_t d[6] = {(uint8_t)(raw >> 8), (uint8_t)raw, (uint8_t)(ms >> 8), (uint8_t)ms, 0, 0};
  return head.write8(hid, sts::TORQUE_ENABLE, 1) && head.write(hid, sts::GOAL_POS, d, 6);
}

void moveArms(const uint8_t *ids, const int *raws, int n, int speed, int acc) {
  int lim[8];
  for (int i = 0; i < n && i < 8; i++) {
    int lo, hi;
    settings::limits(ids[i], lo, hi);
    lim[i] = constrain(raws[i], lo, hi);
  }
  bus.syncMove(ids, lim, min(n, 8), speed, acc);
}

void begin() {
  bool ok = detectBus();
  headPower(true);
  delay(200);                                  // let the servos boot before the first read
  head.begin(HEAD_RX, HEAD_TX, 1000000, 2);
  face::say(ok ? String("bus ") + bus_port + " ok" : "bus not found", 4000);
}

void hello(int ch) {
  JsonDocument doc;
  sysInfo(doc.to<JsonObject>());
  doc["ev"] = "hello";
  emit(ch, doc);
}

void onClient(int ch, bool connected) {
  streamFor(ch).hz = 0, streamFor(ch).cam_ms = 0;
  if (connected) hello(ch);
}

void handleLine(int ch, const char *line, size_t len) {
  JsonDocument req, rep;
  if (deserializeJson(req, line, len)) {
    rep["ok"] = false, rep["error"] = "bad json";
    emit(ch, rep);
    return;
  }
  if (!req["id"].isNull()) rep["id"] = req["id"];
  const char *err = run(ch, req["cmd"] | "", req["args"], rep["result"].to<JsonObject>());
  rep["ok"] = err == nullptr;
  if (err) rep["error"] = err, rep.remove("result");
  emit(ch, rep);
}

void cameraLoop() {
  uint32_t fastest = 0;
  for (int ch = 0; ch < net::MAX_CLIENTS; ch++) {
    Stream &s = streamFor(ch);
    if (!s.cam_ms) continue;
    if (!net::clientConnected(ch)) { s.cam_ms = 0; continue; }
    fastest = fastest ? min(fastest, s.cam_ms) : s.cam_ms;
    if ((int32_t)(millis() - s.cam_next) < 0) continue;
    uint8_t *jpg;
    size_t n;
    uint32_t seq;
    if (!camera::latest(s.cam_seq, &jpg, &n, &seq, 0)) continue;   // no new frame yet
    net::sendBinary(ch, 'J', jpg, n);
    free(jpg);
    s.cam_seq = seq, s.cam_next = millis() + s.cam_ms;
  }
  if (fastest) camera::want(fastest);
}

void micLoop() {
  static int16_t chunk[audio::CHUNK];
  int ch = audio::micClient();
  if (ch < 0) return;
  if (!net::clientConnected(ch)) { audio::micStop(); return; }
  while (audio::micChunk(chunk)) net::sendBinary(ch, 'A', (const uint8_t *)chunk, sizeof(chunk));
}

void loop() {
  relaxHeadWhenIdle();
  cameraLoop();
  micLoop();
  for (int ch = USB; ch < net::MAX_CLIENTS; ch++) {
    Stream &s = streamFor(ch);
    if (!s.hz || (int32_t)(millis() - s.next) < 0) continue;
    if (ch != USB && !net::clientConnected(ch)) { s.hz = 0; continue; }
    s.next += 1000 / s.hz;
    if ((int32_t)(millis() - s.next) > 0) s.next = millis();    // fell behind: don't burst
    JsonDocument doc;
    doc["ev"] = "state", doc["t"] = millis();
    JsonArray arr = doc["servos"].to<JsonArray>();
    for (int i = 0; i < s.n; i++) {
      sts::State st;
      bool ok = bus.readState(s.ids[i], st);
      bool was_bad = s.bad & (1 << i);
      if (ok) stateJson(arr.add<JsonObject>(), s.ids[i], st);
      if (ok == was_bad) {     // went offline or came back
        JsonDocument f;
        f["ev"] = "fault", f["id"] = s.ids[i], f["fault"] = ok ? "back" : "no reply";
        emit(ch, f);
        s.bad ^= (1 << i);
      }
    }
    emit(ch, doc);
  }
}

}  // namespace commands
