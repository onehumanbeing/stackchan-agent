#include "camera.h"

#include <M5Unified.h>
#include <esp_camera.h>
#include <img_converters.h>

namespace camera {

namespace {
camera_config_t config = {
  .pin_pwdn = -1, .pin_reset = -1, .pin_xclk = -1, .pin_sccb_sda = 12, .pin_sccb_scl = 11,
  .pin_d7 = 47, .pin_d6 = 48, .pin_d5 = 16, .pin_d4 = 15, .pin_d3 = 42, .pin_d2 = 41, .pin_d1 = 40, .pin_d0 = 39,
  .pin_vsync = 46, .pin_href = 38, .pin_pclk = 45,
  .xclk_freq_hz = 20000000, .ledc_timer = LEDC_TIMER_0, .ledc_channel = LEDC_CHANNEL_0,
  .pixel_format = PIXFORMAT_RGB565, .frame_size = FRAMESIZE_QVGA, .jpeg_quality = 0, .fb_count = 2,
  .fb_location = CAMERA_FB_IN_PSRAM, .grab_mode = CAMERA_GRAB_WHEN_EMPTY, .sccb_i2c_port = -1,
};
bool ready = false;
SemaphoreHandle_t lock;
SemaphoreHandle_t encoder = xSemaphoreCreateMutex();
uint8_t *jpg = nullptr;           // newest frame (PSRAM)
size_t jpg_len = 0;
uint32_t jpg_seq = 0;
volatile uint32_t interval = 0, wanted_until = 0;
volatile int jpeg_q = 60;

void task(void *) {
  for (;;) {
    if (!interval || (int32_t)(millis() - wanted_until) > 0) { vTaskDelay(pdMS_TO_TICKS(20)); continue; }
    uint32_t t0 = millis();
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) { vTaskDelay(pdMS_TO_TICKS(50)); continue; }
    uint8_t *out = nullptr;
    size_t n = 0;
    xSemaphoreTake(encoder, portMAX_DELAY);
    bool ok = frame2jpg(fb, jpeg_q, &out, &n);
    xSemaphoreGive(encoder);
    esp_camera_fb_return(fb);
    if (ok) {
      xSemaphoreTake(lock, portMAX_DELAY);
      free(jpg);
      jpg = out, jpg_len = n, jpg_seq++;
      xSemaphoreGive(lock);
    }
    uint32_t spent = millis() - t0;
    vTaskDelay(pdMS_TO_TICKS(spent < interval ? interval - spent : 1));
  }
}
}  // namespace

bool begin() {
  M5.In_I2C.release();       // the camera's SCCB shares the internal I2C pins (as in M5CoreS3)
  ready = esp_camera_init(&config) == ESP_OK;
  if (!ready) return false;
  lock = xSemaphoreCreateMutex();
  xTaskCreatePinnedToCore(task, "camera", 6144, nullptr, 1, nullptr, 0);
  return true;
}

bool ok() { return ready; }

void want(uint32_t interval_ms) {
  interval = interval_ms;
  wanted_until = millis() + 3000;      // stops by itself when nobody asks for 3 s
}

bool latest(uint32_t after, uint8_t **out, size_t *len, uint32_t *seq, uint32_t timeout_ms) {
  if (!ready) return false;
  uint32_t t0 = millis();
  for (;;) {
    xSemaphoreTake(lock, portMAX_DELAY);
    if (jpg && jpg_seq > after) {
      *out = (uint8_t *)ps_malloc(jpg_len);
      if (*out) memcpy(*out, jpg, jpg_len), *len = jpg_len, *seq = jpg_seq;
      xSemaphoreGive(lock);
      return *out != nullptr;
    }
    xSemaphoreGive(lock);
    if (millis() - t0 >= timeout_ms) return false;
    want(interval ? interval : 100);      // keep the capture task awake while we wait
    delay(5);
  }
}

bool encodeRgb565(const uint8_t *buf, size_t len, int w, int h, int quality, uint8_t **out, size_t *out_len) {
  xSemaphoreTake(encoder, portMAX_DELAY);
  bool ok = fmt2jpg((uint8_t *)buf, len, w, h, PIXFORMAT_RGB565, quality, out, out_len);
  xSemaphoreGive(encoder);
  return ok;
}

void setQuality(int q) { jpeg_q = constrain(q, 10, 95); }
int quality() { return jpeg_q; }

void setFlip(bool hmirror, bool vflip) {
  sensor_t *s = esp_camera_sensor_get();
  if (s) s->set_hmirror(s, hmirror), s->set_vflip(s, vflip);
}

}  // namespace camera
