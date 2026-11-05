#include "dance.h"

#include <FFat.h>
#include <M5Unified.h>

#include "audio.h"
#include "commands.h"
#include "face.h"
#include "net.h"

namespace dance {

namespace {
constexpr uint32_t AUDIO_LATENCY_MS = 30;    // from audio::play to the first sample being heard
constexpr const char *TOUCH_DANCE = "dance_1";

struct Sample { int16_t l, r, yaw, pitch, speed; };
struct Face { uint32_t ms; char name[12]; };

struct Loaded {
  String name;
  uint16_t hz = 0, n = 0, nf = 0;
  uint8_t ids[2] = {0, 0};
  Sample *s = nullptr;
  Face *f = nullptr;
};
Loaded cur;
bool on = false;
uint32_t t0 = 0;
int last = -1, next_face = 0;

File up;                                     // the upload in progress
String up_name;
uint32_t up_got = 0;                         // bytes written (a FAT file's size() lags while it is open)

String path(const String &name, const char *ext = ".dnc") { return "/" + name + ext; }

bool validName(const String &n) {
  if (n.isEmpty() || n.length() > 24) return false;
  for (char c : n) if (!isalnum(c) && c != '_' && c != '-') return false;
  return true;
}

void unload() {
  free(cur.s), free(cur.f);
  cur = Loaded();
}

void pose(const Sample &s, int arm_speed, int head_ms) {
  int raws[2] = {s.l, s.r};
  commands::moveArms(cur.ids, raws, 2, arm_speed, 200);
  commands::moveHead(1, s.yaw, head_ms);
  commands::moveHead(2, s.pitch, head_ms);
}

void reply(int client, const String &name, uint32_t got, uint32_t total, const char *err) {
  JsonDocument d;
  d["ev"] = "upload", d["name"] = name, d["got"] = got, d["total"] = total, d["done"] = !err && got == total;
  if (err) d["error"] = err;
  String s;
  serializeJson(d, s);
  net::send(client, s.c_str(), s.length());
}
}  // namespace

void begin() {
  if (!FFat.begin(true)) face::say("storage failed", 4000);
  M5.Touch.setHoldThresh(1000);
}

void upload(int client, const uint8_t *data, size_t len) {
  if (len < 9 || len < 9u + data[0]) return reply(client, "", 0, 0, "short frame");
  String name((const char *)data + 1, data[0]);
  const uint8_t *p = data + 1 + data[0];
  uint32_t offset, total;
  memcpy(&offset, p, 4), memcpy(&total, p + 4, 4);
  p += 8, len -= p - data;
  if (!validName(name)) return reply(client, name, 0, total, "bad name");
  if (on && cur.name == name) return reply(client, name, 0, total, "it is dancing that one");
  if (offset == 0) {
    if (up) up.close();
    up = FFat.open(path(name, ".tmp"), "w"), up_name = name, up_got = 0;
  }
  if (!up || up_name != name || up_got != offset) return reply(client, name, up_got, total, "out of order: start again at 0");
  if (up.write(p, len) != len) {
    up.close();
    return reply(client, name, offset, total, "storage full");
  }
  uint32_t got = up_got = offset + len;
  if (got >= total) {
    up.close();
    FFat.remove(path(name));
    FFat.rename(path(name, ".tmp"), path(name));
  }
  reply(client, name, got, total, nullptr);
}

const char *play(const String &name) {
  if (on) stop();
  File fl = FFat.open(path(name), "r");
  if (!fl) return "no such dance (upload it first)";
  char magic[4];
  uint32_t pcm_bytes = 0;
  unload();
  if (fl.read((uint8_t *)magic, 4) != 4 || memcmp(magic, "SCD1", 4)) return "not a dance file";
  fl.read((uint8_t *)&cur.hz, 2), fl.read((uint8_t *)&cur.n, 2), fl.read((uint8_t *)&cur.nf, 2);
  fl.read(cur.ids, 2), fl.read((uint8_t *)&pcm_bytes, 4);
  cur.s = (Sample *)ps_malloc(cur.n * sizeof(Sample));
  cur.f = (Face *)ps_malloc(max<int>(1, cur.nf) * sizeof(Face));
  if (!cur.hz || !cur.n || !cur.s || !cur.f) return unload(), "bad dance file";
  fl.read((uint8_t *)cur.s, cur.n * sizeof(Sample));
  fl.read((uint8_t *)cur.f, cur.nf * sizeof(Face));
  cur.name = name;

  pose(cur.s[0], 600, 800);                      // ease into the first pose
  face::touch();
  delay(850);
  audio::stop();
  audio::setVolume(200);
  static uint8_t buf[16000];                     // the music, queued in 0.5 s pieces
  for (uint32_t left = pcm_bytes; left;) {
    size_t k = fl.read(buf, min<uint32_t>(sizeof(buf), left));
    if (!k) break;
    audio::play(buf, k);
    left -= k;
  }
  fl.close();
  t0 = millis() + AUDIO_LATENCY_MS, last = -1, next_face = 0, on = true;
  return nullptr;
}

void stop() {
  if (!on) return;
  on = false;
  audio::stop();
  audio::setVolume(180);
  pose(cur.s[cur.n - 1], 600, 800);              // the last sample is the neutral pose
  face::setExpression("neutral");
}

bool playing() { return on; }

void status(JsonObject r) {
  r["playing"] = on, r["name"] = cur.name;
  if (on) r["t"] = (int32_t)(millis() - t0) / 1000.0f, r["seconds"] = cur.n / (float)cur.hz;
}

void list(JsonObject r) {
  JsonArray a = r["dances"].to<JsonArray>();
  File root = FFat.open("/");
  for (File f = root.openNextFile(); f; f = root.openNextFile()) {
    String n = f.name();
    if (!n.endsWith(".dnc")) continue;
    JsonObject o = a.add<JsonObject>();
    uint16_t h[3] = {0, 0, 0};
    f.seek(4), f.read((uint8_t *)h, 6);
    o["name"] = n.substring(0, n.length() - 4), o["bytes"] = f.size();
    if (h[0]) o["seconds"] = h[1] / (float)h[0];
  }
  r["free"] = FFat.totalBytes() - FFat.usedBytes();
}

bool remove(const String &name) { return validName(name) && FFat.remove(path(name)); }

void loop() {
  auto t = M5.Touch.getDetail();
  if (on && t.wasClicked()) stop();
  else if (!on && t.wasHold()) play(TOUCH_DANCE);

  if (!on) return;
  int32_t ms = millis() - t0;
  if (ms < 0) return;
  while (next_face < cur.nf && cur.f[next_face].ms <= (uint32_t)ms) {
    char name[13] = {0};
    memcpy(name, cur.f[next_face++].name, 12);
    face::setExpression(name);
  }
  int i = ms * cur.hz / 1000;
  if (i >= cur.n) {
    on = false;
    pose(cur.s[cur.n - 1], 600, 400);            // settle on the neutral pose (the curve's last speed is tiny)
    audio::setVolume(180);
    face::setExpression("neutral");
    return;
  }
  if (i == last) return;
  last = i;
  pose(cur.s[i], cur.s[i].speed, 1000 / cur.hz + 10);
}

}  // namespace dance
