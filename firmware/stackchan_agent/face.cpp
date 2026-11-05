#include "face.h"

#include <M5Unified.h>

#include "camera.h"
#include "face_styles.h"

namespace face {

namespace {
constexpr const char *EXPRESSIONS[] = {"neutral", "happy", "sad", "angry", "doubt", "sleepy", "surprised", "listening", "thinking"};
constexpr uint32_t FRAME_MS = 40;

LGFX_Sprite canvas(&M5.Display);
SemaphoreHandle_t lock;
const Style *current = &STYLES[0];
const char *expr = "neutral";
float gaze_v = 0, gaze_h = 0, target_v = 0, target_h = 0, mouth_open = 0;
uint32_t gaze_set_at = 0, next_glance = 0, next_blink = 0, blink_start = 0;
String caption;
uint32_t caption_until = 0;

float blinkOpen(uint32_t now) {           // 1 = open; a 160 ms close-open
  uint32_t dt = now - blink_start;
  if (dt > 160) return 1.0f;
  float x = dt / 80.0f;
  return x < 1 ? 1 - x : x - 1;
}

void step(uint32_t now) {
  if (now >= next_blink) blink_start = now, next_blink = now + random(2200, 6000);
  if (now - gaze_set_at > 5000 && now >= next_glance) {    // idle: glance around now and then
    target_v = random(-30, 31) / 100.0f, target_h = random(-60, 61) / 100.0f;
    if (random(3) == 0) target_v = target_h = 0;
    next_glance = now + random(1500, 4000);
  }
  gaze_v += (target_v - gaze_v) * 0.25f, gaze_h += (target_h - gaze_h) * 0.25f;
}

void render() {
  uint32_t now = millis();
  xSemaphoreTake(lock, portMAX_DELAY);
  step(now);
  Look look{expr, gaze_v, gaze_h, blinkOpen(now), mouth_open, now};
  current->draw(canvas, look);
  if (caption.length()) {
    canvas.setTextDatum(bottom_center);
    canvas.setTextColor(0xFFFFFFU);
    canvas.drawString(caption, 160, 234);
  }
  xSemaphoreGive(lock);
  canvas.pushSprite(0, 0);
}

void task(void *) {
  for (;;) {
    uint32_t t0 = millis();
    render();
    uint32_t spent = millis() - t0;
    vTaskDelay(pdMS_TO_TICKS(spent < FRAME_MS ? FRAME_MS - spent : 1));
  }
}
}  // namespace

void begin() {
  lock = xSemaphoreCreateMutex();
  M5.Display.setRotation(1);
  canvas.setPsram(true);
  canvas.setColorDepth(16);
  canvas.createSprite(320, 240);
  canvas.setFont(&fonts::efontCN_16);
  next_blink = millis() + 1500;
  xTaskCreatePinnedToCore(task, "face", 6144, nullptr, 1, nullptr, 0);
}

void loop() {
  if (caption_until && (int32_t)(millis() - caption_until) >= 0) say("");
}

bool setExpression(const String &name) {
  for (const char *e : EXPRESSIONS) {
    if (name != e) continue;
    expr = e;
    return true;
  }
  return false;
}

bool setStyle(const String &name) {
  for (int i = 0; i < STYLE_COUNT; i++) {
    if (name != STYLES[i].name) continue;
    current = &STYLES[i];
    return true;
  }
  return false;
}

void gaze(float vertical, float horizontal) {
  target_v = constrain(vertical, -1.0f, 1.0f), target_h = constrain(horizontal, -1.0f, 1.0f);
  gaze_set_at = millis();
}

void mouth(float open) { mouth_open = constrain(open, 0.0f, 1.0f); }
void blink() { blink_start = millis(); }

void say(const String &text, uint32_t ms) {
  xSemaphoreTake(lock, portMAX_DELAY);
  caption = text;
  xSemaphoreGive(lock);
  caption_until = (ms && text.length()) ? millis() + ms : 0;
}

const char *expression() { return expr; }
const char *style() { return current->name; }

String styleNames() {
  String s = "[";
  for (int i = 0; i < STYLE_COUNT; i++) s += (i ? ",\"" : "\"") + String(STYLES[i].name) + "\"";
  return s + "]";
}

uint8_t *snapJpeg(size_t *len) {
  uint8_t *jpg = nullptr;
  xSemaphoreTake(lock, portMAX_DELAY);
  bool ok = camera::encodeRgb565((const uint8_t *)canvas.getBuffer(), 320 * 240 * 2, 320, 240, 80, &jpg, len);
  xSemaphoreGive(lock);
  return ok ? jpg : nullptr;
}

}  // namespace face
