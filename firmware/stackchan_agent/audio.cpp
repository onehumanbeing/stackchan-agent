#include "audio.h"
#include <M5Unified.h>
#include <deque>

namespace audio {

namespace {
QueueHandle_t mic_q;                      // filled chunks: int16_t[CHUNK] in PSRAM
TaskHandle_t mic_task;
volatile int mic_client = -1;
volatile bool mic_on = false;
std::deque<std::pair<int16_t *, size_t>> pending, inflight;   // speaker chunks (samples)

void micTask(void *) {
  static int16_t ring[3][CHUNK];          // M5 Mic double-buffers: after queueing k, k-2 is complete
  int k = 0, queued = 0;
  for (;;) {
    if (!mic_on) { queued = 0; vTaskDelay(pdMS_TO_TICKS(20)); continue; }
    if (!M5.Mic.record(ring[k], CHUNK, RATE)) { vTaskDelay(pdMS_TO_TICKS(5)); continue; }
    if (++queued >= 3) {
      int16_t *copy = (int16_t *)ps_malloc(CHUNK * 2);
      if (copy) {
        memcpy(copy, ring[(k + 1) % 3], CHUNK * 2);
        if (xQueueSend(mic_q, &copy, 0) != pdTRUE) free(copy);   // nobody reading: drop
      }
    }
    k = (k + 1) % 3;
  }
}

void freeAll(std::deque<std::pair<int16_t *, size_t>> &d) {
  for (auto &c : d) free(c.first);
  d.clear();
}
}  // namespace

void begin() {
  mic_q = xQueueCreate(32, sizeof(int16_t *));
  M5.Speaker.setVolume(180);
  xTaskCreatePinnedToCore(micTask, "mic", 4096, nullptr, 2, &mic_task, 1);
}

bool micStart(int client) {
  if (playing()) return false;
  freeAll(inflight);
  M5.Speaker.end();
  auto cfg = M5.Mic.config();
  cfg.sample_rate = RATE;
  cfg.noise_filter_level = 2;
  M5.Mic.config(cfg);
  if (!M5.Mic.begin()) return false;
  mic_client = client, mic_on = true;
  return true;
}

void micStop() {
  mic_on = false, mic_client = -1;
  delay(60);                               // let the task leave record()
  M5.Mic.end();
  int16_t *c;
  while (xQueueReceive(mic_q, &c, 0) == pdTRUE) free(c);
}

int micClient() { return mic_on ? mic_client : -1; }

bool micChunk(int16_t *out) {
  int16_t *c;
  if (xQueueReceive(mic_q, &c, 0) != pdTRUE) return false;
  memcpy(out, c, CHUNK * 2);
  free(c);
  return true;
}

void play(const uint8_t *pcm, size_t bytes) {
  if (mic_on) micStop();
  if (!M5.Speaker.isEnabled()) M5.Speaker.begin();
  size_t n = bytes / 2;
  int16_t *c = (int16_t *)ps_malloc(n * 2);
  if (!c) return;
  memcpy(c, pcm, n * 2);
  pending.push_back({c, n});
}

void stop() {
  M5.Speaker.stop();
  freeAll(pending);
  freeAll(inflight);
}

bool playing() { return !pending.empty() || (M5.Speaker.isEnabled() && M5.Speaker.isPlaying(0)); }

void setVolume(int v) { M5.Speaker.setVolume(constrain(v, 0, 255)); }

void loop() {
  if (pending.empty() || !M5.Speaker.isEnabled()) {
    if (!pending.empty()) M5.Speaker.begin();
    return;
  }
  if (M5.Speaker.isPlaying(0) >= 2) return;  // its queue holds two buffers
  auto c = pending.front();
  pending.pop_front();
  M5.Speaker.playRaw(c.first, c.second, RATE, false, 1, 0, false);
  inflight.push_back(c);
  while (inflight.size() > 3) {             // at most two are still queued: older ones are done
    free(inflight.front().first);
    inflight.pop_front();
  }
}

}  // namespace audio
