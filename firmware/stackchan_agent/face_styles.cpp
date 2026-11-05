#include "face_styles.h"

namespace face {

const Style STYLES[] = {
  {"eyes", drawEyes},
};
const int STYLE_COUNT = sizeof(STYLES) / sizeof(STYLES[0]);

// "eyes": two white rounded pills on black.  Expressions only change the eye shapes:
// happy = smiling arcs, sad / angry = slanted lids, sleepy = half shut, doubt = one eye narrowed,
// surprised = big round eyes.  Speaking makes the eyes bounce a little.
namespace {
constexpr int CX = 160, CY = 112, SPACING = 76, W = 66, H = 112;
constexpr uint32_t WHITE = 0xFFFFFF, BLACK = 0x000000;

void eye(LGFX_Sprite &c, int side, const Look &k) {    // side: -1 = left on screen, +1 = right
  const String e = k.expression;
  float w = W, h = H * max(k.open, 0.06f);
  if (e == "surprised") w *= 1.18f, h *= 1.12f;
  if (e == "sleepy") h = min(h, H * 0.28f);
  if (e == "doubt" && side > 0) h *= 0.45f;
  h *= 1.0f + 0.08f * k.mouth * sinf(k.t / 60.0f);
  int x = CX + side * SPACING + k.gaze_h * 26, y = CY + k.gaze_v * 20;
  int r = min(w, h) / 2;
  c.fillSmoothRoundRect(x - w / 2, y - h / 2, w, h, r, WHITE);

  if (e == "happy") {             // cover the bottom: an upward arc
    c.fillEllipse(x, y + h * 0.62f, w * 0.9f, h * 0.62f, BLACK);
  } else if (e == "sad" || e == "angry") {   // a slanted lid cut off the top
    int outer = x + side * w / 2, inner = x - side * w / 2, top = y - h / 2;
    int drop = h * 0.38f;
    if (e == "sad") c.fillTriangle(outer, top - 2, outer, top + drop, inner, top - 2, BLACK);
    else c.fillTriangle(inner, top - 2, inner, top + drop, outer, top - 2, BLACK);
  }
}
}  // namespace

void drawEyes(LGFX_Sprite &c, const Look &k) {
  c.fillScreen(BLACK);
  eye(c, -1, k);
  eye(c, +1, k);
}

}  // namespace face
