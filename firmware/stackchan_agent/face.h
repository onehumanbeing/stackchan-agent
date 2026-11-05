// The face: an engine that animates blinks, gaze and expressions and draws them with a style
// (face_styles.h; default "eyes").  Renders on its own task, so servo work is not held up.
#pragma once
#include <Arduino.h>

namespace face {

void begin();
void loop();                                    // clears timed balloons
bool setExpression(const String &name);         // neutral happy sad angry doubt sleepy surprised
bool setStyle(const String &name);
void gaze(float vertical, float horizontal);    // -1..1; idle glances resume after 5 s
void mouth(float open);                         // 0..1
void say(const String &text, uint32_t ms = 0);  // caption under the eyes; ms = 0 keeps it, "" clears
void blink();
const char *expression();
const char *style();
String styleNames();                            // JSON array
uint8_t *snapJpeg(size_t *len);                 // the current frame as JPEG; caller frees

}  // namespace face
