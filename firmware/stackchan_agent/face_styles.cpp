#include "face_styles.h"

namespace face {

const Style STYLES[] = {
  {"eyes", drawEyes},
};
const int STYLE_COUNT = sizeof(STYLES) / sizeof(STYLES[0]);

// "eyes": two white rounded pills on black.  An expression's Shape cuts lids and arcs out of them
// (face_lib.cpp) and adds a few decorations: hearts, tears, blush, sparkles, a spiral, sweat, "z z", a yawn.
namespace {
constexpr int CX = 160, CY = 112, SPACING = 76, W = 66, H = 112;
constexpr uint32_t WHITE = 0xFFFFFF, BLACK = 0x000000, BLUE = 0x66CCFF, PINK = 0xFF6F91;

void heart(LGFX_Sprite &c, int x, int y, float s) {
  int r = s * 0.27f;
  c.fillCircle(x - r, y - r / 2, r, WHITE);
  c.fillCircle(x + r, y - r / 2, r, WHITE);
  c.fillTriangle(x - 2 * r, y - r / 4, x + 2 * r, y - r / 4, x, y + 1.7f * r, WHITE);
}

void spiral(LGFX_Sprite &c, int x, int y, float s, uint32_t t) {
  float a0 = t / 120.0f;
  for (float a = 0; a < 15; a += 0.08f) {
    float r = a * s / 14;
    c.fillCircle(x + cosf(a + a0) * r, y + sinf(a + a0) * r, 3, WHITE);
  }
}

void sparkle(LGFX_Sprite &c, int x, int y, float s) {
  c.fillTriangle(x, y - s, x - s / 4, y, x + s / 4, y, WHITE), c.fillTriangle(x, y + s, x - s / 4, y, x + s / 4, y, WHITE);
  c.fillTriangle(x - s, y, x, y - s / 4, x, y + s / 4, WHITE), c.fillTriangle(x + s, y, x, y - s / 4, x, y + s / 4, WHITE);
}

void drop(LGFX_Sprite &c, int x, int y, int r, uint32_t color) {
  c.fillCircle(x, y, r, color);
  c.fillTriangle(x - r, y - 1, x + r, y - 1, x, y - 2.4f * r, color);
}

void eye(LGFX_Sprite &c, int side, const Look &k) {    // side: -1 = left on screen, +1 = right
  const Shape &s = *k.shape;
  float w = W * s.w, h = H * s.h * k.open;
  if (side > 0) h *= 1 - s.asym;
  h *= 1.0f + 0.12f * k.mouth * sinf(k.t / 60.0f);       // speaking: the eyes bob along
  int x = CX + side * SPACING + k.gaze_h * 26 + k.dx, y = CY + k.gaze_v * 20 + k.dy;

  if (s.extra & HEART) {
    heart(c, x, y, w * 1.05f * max(k.open, 0.2f) * (1 + 0.06f * sinf(k.t / 140.0f)));
    return;
  }
  if (s.extra & SPIRAL) {
    spiral(c, x, y, w * 0.55f, side > 0 ? k.t : k.t + 600);
    return;
  }
  bool shut = (side > 0 && s.wink > 0.5f) || (s.extra & ARC);
  if (shut) {                                             // a closed, smiling eye: "^"
    int r = w * 0.5f;
    c.fillArc(x, y + r / 2, r - 10, r, 200, 340, WHITE);
    return;
  }
  h = max(h, 6.0f);
  int r = min(w, h) / 2, top = y - h / 2;
  c.fillSmoothRoundRect(x - w / 2, top, w, h, r, WHITE);
  if (s.smile > 0.02f) c.fillEllipse(x, y + h * (0.42f + (1 - s.smile) * 0.9f), w * 0.8f, h * 0.6f, BLACK);   // a crescent
  if (fabsf(s.slant) > 0.02f) {                           // a slanted lid: sad (outer low) or angry (inner low)
    int outer = x + side * w / 2, inner = x - side * w / 2, d = h * fabsf(s.slant);
    if (s.slant < 0) c.fillTriangle(outer + side * 2, top - 2, outer + side * 2, top + d, inner, top - 2, BLACK);
    else c.fillTriangle(inner - side * 2, top - 2, inner - side * 2, top + d, outer, top - 2, BLACK);
  }
  if (s.lid > 0.02f) c.fillRect(x - w / 2 - 2, top - 2, w + 4, h * s.lid + 2, BLACK);
  if (s.extra & TEARS) {
    int fall = (k.t / 12) % 60;
    drop(c, x - side * w / 4, y + h / 2 + 10 + fall, 6, BLUE);
  }
  if (s.extra & BLUSH) c.fillEllipse(x + side * 8, y + h / 2 + 16, 24, 8, PINK);
  if (s.extra & SPARKLE) sparkle(c, x + side * (w / 2 + 16), y - h / 2 + 4, 7 + 3 * sinf(k.t / 150.0f + side));
}
}  // namespace

void drawEyes(LGFX_Sprite &c, const Look &k) {
  c.fillScreen(BLACK);
  eye(c, -1, k);
  eye(c, +1, k);
  const Shape &s = *k.shape;
  if (s.extra & SWEAT) drop(c, CX + SPACING + 52 + k.dx, 34 + k.dy + (k.t / 40) % 6, 7, BLUE);
  if (s.extra & YAWN) {                                   // a mouth that opens and closes
    float o = fabsf(sinf(k.t / 600.0f));
    int ry = 5 + 16 * o;
    c.fillEllipse(CX + k.dx, 196 + k.dy, ry * 0.8f + 4, ry, WHITE);
    c.fillEllipse(CX + k.dx, 196 + k.dy, max(1.0f, ry * 0.8f - 2), max(1, ry - 6), BLACK);
  }
  if (s.extra & ZZZ) {                                    // "z" letters drifting up
    c.setTextDatum(middle_center);
    c.setTextColor(WHITE);
    for (int i = 0; i < 3; i++) {
      int p = (k.t / 25 + i * 40) % 120;
      c.setTextSize(1.5f + p / 80.0f);
      c.drawString("z", CX + SPACING + 10 + p / 3, 100 - p * 2 / 3);
    }
    c.setTextSize(1);
  }
}

}  // namespace face
