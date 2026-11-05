#include "face_lib.h"

namespace face {

// Fields must stay in Shape's declaration order (designated initializers).
const Expression EXPRESSIONS[] = {
  {"neutral",   {}},
  {"happy",     {.h = 0.95f, .smile = 1}},
  {"excited",   {.w = 1.1f, .h = 1.05f, .smile = 1, .bounce = 6, .extra = SPARKLE}},
  {"love",      {.w = 1.15f, .h = 1.1f, .bounce = 3, .extra = HEART}},
  {"shy",       {.w = 0.95f, .h = 0.85f, .smile = 0.6f, .gv = 0.6f, .gh = 0.4f, .extra = BLUSH}},
  {"wink",      {.smile = 0.7f, .wink = 1, .extra = SPARKLE}},
  {"proud",     {.w = 1.05f, .h = 1.05f, .smile = 0.9f, .gv = -0.5f, .extra = SPARKLE}},
  {"smug",      {.h = 0.9f, .lid = 0.45f, .smile = 0.3f, .gh = 0.6f}},
  {"sad",       {.h = 0.9f, .slant = -0.38f, .gv = 0.4f}},
  {"cry",       {.h = 0.85f, .slant = -0.4f, .smile = 0.3f, .gv = 0.3f, .extra = TEARS}},
  {"angry",     {.h = 0.95f, .slant = 0.4f}},
  {"doubt",     {.lid = 0.1f, .gh = 0.3f, .asym = 0.55f}},
  {"curious",   {.w = 1.05f, .h = 1.1f, .gv = -0.2f, .gh = -0.3f, .asym = -0.25f}},
  {"surprised", {.w = 1.18f, .h = 1.12f, .gv = -0.2f}},
  {"scared",    {.w = 0.8f, .h = 1.05f, .slant = -0.15f, .jitter = 2.5f, .extra = SWEAT}},
  {"dizzy",     {.w = 1.05f, .h = 1.05f, .extra = SPIRAL}},
  {"sleepy",    {.lid = 0.72f, .gv = 0.3f}},
  {"sigh",      {.h = 0.9f, .slant = -0.2f, .lid = 0.4f, .gv = 0.5f}},
  {"bored",     {.lid = 0.5f, .gv = 0.2f, .gh = 0.5f}},
  {"listening", {.w = 1.06f, .h = 1.1f, .gv = -0.8f}},
  {"thinking",  {.lid = 0.3f, .gv = -0.5f, .scan = 0.9f, .scan_ms = 400}},
  // Daydreaming (the engine plays these on its own when nobody talks to it).
  {"daydream",  {.lid = 0.35f, .gv = -0.6f, .scan = 0.5f, .scan_ms = 2600}},
  {"yawn",      {.h = 0.9f, .smile = 1, .extra = YAWN | ARC}},
  {"doze",      {.lid = 0.92f, .gv = 0.4f, .extra = ZZZ}},
};
const int EXPRESSION_COUNT = sizeof(EXPRESSIONS) / sizeof(EXPRESSIONS[0]);

const Expression *findExpression(const String &name) {
  for (const Expression &e : EXPRESSIONS)
    if (name == e.name) return &e;
  return nullptr;
}

void blend(Shape &c, const Shape &t, float k) {
  auto mix = [k](float &a, float b) { a += (b - a) * k; };
  mix(c.w, t.w), mix(c.h, t.h), mix(c.slant, t.slant), mix(c.lid, t.lid), mix(c.smile, t.smile);
  mix(c.gv, t.gv), mix(c.gh, t.gh), mix(c.asym, t.asym), mix(c.wink, t.wink);
  mix(c.bounce, t.bounce), mix(c.jitter, t.jitter), mix(c.scan, t.scan), mix(c.scan_ms, t.scan_ms);
  c.extra = t.extra;
}

String expressionNames() {
  String s = "[";
  for (int i = 0; i < EXPRESSION_COUNT; i++) s += (i ? ",\"" : "\"") + String(EXPRESSIONS[i].name) + "\"";
  return s + "]";
}

}  // namespace face
