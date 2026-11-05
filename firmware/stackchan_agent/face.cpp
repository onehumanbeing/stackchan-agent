#include "face.h"

#include <M5Unified.h>

#include "camera.h"
#include "face_styles.h"

namespace face {

namespace {
constexpr uint32_t FRAME_MS = 40;
constexpr uint32_t IDLE_AFTER_MS = 5000, DOZE_AFTER_MS = 5000;   // nobody talks to it for 5 s: it dozes off (no daydream stage)

LGFX_Sprite canvas(&M5.Display);
SemaphoreHandle_t lock;
const Style *current = &STYLES[0];
const Expression *expr = &EXPRESSIONS[0];       // what it was told to show
const Expression *idle_expr = nullptr;          // what it shows while daydreaming (nullptr = not idle)
Shape shape;                                    // blended toward the shown expression every frame
bool idle_on = true;
float gaze_v = 0, gaze_h = 0, target_v = 0, target_h = 0, mouth_open = 0;
uint32_t gaze_set_at = 0, next_glance = 0, next_blink = 0, blink_start = 0, active_at = 0, idle_until = 0;
String caption;
uint32_t caption_until = 0;

float blinkOpen(uint32_t now) {           // 1 = open; a 160 ms close-open
  uint32_t dt = now - blink_start;
  if (dt > 160) return 1.0f;
  float x = dt / 80.0f;
  return x < 1 ? 1 - x : x - 1;
}

const Expression *named(const char *n) { return findExpression(n); }

// Daydreaming: little scenes played on its own until someone sets an expression again.
void idleStep(uint32_t now) {
  if (!idle_on || now - active_at < IDLE_AFTER_MS) {
    idle_expr = nullptr;
    return;
  }
  if (idle_expr && now < idle_until) return;
  if (now - active_at > DOZE_AFTER_MS) {                 // dozing, now and then startled awake for a moment
    bool jolt = idle_expr && !strcmp(idle_expr->name, "doze") && random(4) == 0;
    idle_expr = named(jolt ? "surprised" : "doze"), idle_until = now + (jolt ? 700 : random(15000, 30000));
    return;
  }
  static const char *const SCENES[] = {"neutral", "neutral", "daydream", "daydream", "bored", "curious", "yawn", "happy", "sigh"};
  static const uint16_t MS[][2] = {{3000, 6000}, {3000, 6000}, {4000, 8000}, {4000, 8000}, {3000, 5000}, {1500, 2500},
                                   {2600, 2600}, {1500, 2500}, {2000, 3000}};
  int i = random(sizeof(SCENES) / sizeof(SCENES[0]));
  idle_expr = named(SCENES[i]), idle_until = now + random(MS[i][0], MS[i][1] + 1);
}

void step(uint32_t now) {
  if (now >= next_blink) {                               // blink, sometimes twice
    blink_start = now;
    next_blink = random(5) == 0 ? now + 260 : now + random(2200, 6000);
  }
  idleStep(now);
  blend(shape, (idle_expr ? idle_expr : expr)->shape, 0.25f);
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
  float glance = shape.scan > 0.1f ? 0.4f : 1.0f;          // glancing expressions move the eyes themselves
  float gv = constrain(gaze_v * glance + shape.gv, -1.0f, 1.0f);
  float gh = constrain(gaze_h * glance + shape.gh + shape.scan * sinf(now / shape.scan_ms), -1.0f, 1.0f);
  float dy = 2.0f * sinf(now * 2 * PI / 4000) - shape.bounce * fabsf(sinf(now / 170.0f));   // breathing, hops
  float dx = shape.jitter > 0.2f ? random(-100, 101) / 100.0f * shape.jitter : 0;
  if (shape.jitter > 0.2f) dy += random(-100, 101) / 100.0f * shape.jitter;
  Look look{(idle_expr ? idle_expr : expr)->name, gv, gh, blinkOpen(now), mouth_open, now, &shape, dx, dy};
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
  next_blink = millis() + 1500, active_at = millis();
  xTaskCreatePinnedToCore(task, "face", 6144, nullptr, 1, nullptr, 0);
}

void loop() {
  if (caption_until && (int32_t)(millis() - caption_until) >= 0) say("");
}

bool setExpression(const String &name) {
  const Expression *e = findExpression(name);
  if (!e) return false;
  expr = e, active_at = millis(), idle_expr = nullptr;
  return true;
}

void touch() { active_at = millis(); }
void setIdle(bool on) { idle_on = on, active_at = millis(); }
bool idle() { return idle_expr != nullptr; }

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
  gaze_set_at = active_at = millis();
}

void mouth(float open) { mouth_open = constrain(open, 0.0f, 1.0f), active_at = millis(); }
void blink() { blink_start = millis(); }

void say(const String &text, uint32_t ms) {
  xSemaphoreTake(lock, portMAX_DELAY);
  caption = text;
  if (text.length()) active_at = millis();
  xSemaphoreGive(lock);
  caption_until = (ms && text.length()) ? millis() + ms : 0;
}

const char *expression() { return (idle_expr ? idle_expr : expr)->name; }
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
