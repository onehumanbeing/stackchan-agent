// The expression library: every expression is a Shape (eye parameters plus a few decorations).
// The engine blends the current shape toward the target every frame, so expressions morph instead of jumping.
// To add an expression, add a row to EXPRESSIONS in face_lib.cpp.
#pragma once
#include <Arduino.h>

namespace face {

enum Extra : uint16_t {
  HEART = 1, TEARS = 2, BLUSH = 4, SPIRAL = 8, SWEAT = 16, SPARKLE = 32, ZZZ = 64, YAWN = 128, ARC = 256,
};

struct Shape {
  float w = 1, h = 1;     // eye size, x the base size
  float slant = 0;        // top-lid cut: > 0 angry (inner corner low), < 0 sad (outer corner low); fraction of height
  float lid = 0;          // flat top lid, fraction of height closed (sleepy, bored)
  float smile = 0;        // bottom arc cut 0..1: 1 = "^ ^" smiling eyes
  float gv = 0, gh = 0;   // gaze bias, -1..1 (v: - = up)
  float asym = 0;         // right eye smaller by this fraction (doubt, curious: < 0 = right eye bigger)
  float wink = 0;         // right eye closed 0..1
  float bounce = 0;       // vertical hop amplitude, px
  float jitter = 0;       // trembling, px
  float scan = 0;         // sideways glancing amplitude, -1..1 gaze units (thinking, daydream)
  float scan_ms = 400;    // glancing period
  uint16_t extra = 0;     // Extra flags
};

struct Expression {
  const char *name;
  Shape shape;
};

extern const Expression EXPRESSIONS[];
extern const int EXPRESSION_COUNT;

const Expression *findExpression(const String &name);
void blend(Shape &cur, const Shape &target, float k);   // k: 0..1 per frame
String expressionNames();                                // JSON array

}  // namespace face
