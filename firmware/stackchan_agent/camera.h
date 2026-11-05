// CoreS3 camera (GC0308): a task on core 0 grabs RGB565 frames and keeps the latest one as JPEG.
// Pin map from M5Stack's M5CoreS3 library (MIT).  Frames are only captured while someone wants them.
#pragma once
#include <Arduino.h>

namespace camera {

bool begin();
bool ok();
void want(uint32_t interval_ms);     // keep capturing at about this rate (0 = stop); refreshed by callers
// Copy of the newest JPEG with a sequence number > `after` (waits up to timeout_ms).  Caller frees *out.
bool latest(uint32_t after, uint8_t **out, size_t *len, uint32_t *seq, uint32_t timeout_ms);
// JPEG from an RGB565 buffer; the encoder is not reentrant, so every encode goes through here.
bool encodeRgb565(const uint8_t *buf, size_t len, int w, int h, int quality, uint8_t **out, size_t *out_len);
void setQuality(int q);              // JPEG quality 10..95
void setFlip(bool hmirror, bool vflip);
int quality();

}  // namespace camera
