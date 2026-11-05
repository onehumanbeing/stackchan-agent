// Face styles: how the face is drawn.  The engine (face.cpp) animates blinking, gaze and timing and
// calls a style's draw() into a 320 x 240 sprite every frame.  To add your own style, write a draw
// function in a new .cpp file and add it to STYLES in face_styles.cpp.
#pragma once
#include <M5GFX.h>

namespace face {

struct Look {
  const char *expression;   // neutral happy sad angry doubt sleepy surprised
  float gaze_v, gaze_h;     // -1..1 (smoothed)
  float open;               // eye openness 0..1 (blinks included)
  float mouth;              // 0..1, e.g. while speaking
  uint32_t t;               // ms
};

struct Style {
  const char *name;
  void (*draw)(LGFX_Sprite &canvas, const Look &look);
};

extern const Style STYLES[];
extern const int STYLE_COUNT;

void drawEyes(LGFX_Sprite &canvas, const Look &look);   // default: two eyes, nothing else

}  // namespace face
