// Hang diagnostics: a loop watchdog (reboot after WDT_S without a pass through loop()) and a breadcrumb of the loop
// stage that ran last, kept across that reboot, so sys.info can say where the firmware got stuck.
#pragma once
#include <Arduino.h>

namespace diag {
enum Stage : uint8_t { NONE, M5_UPDATE, USB, NET, COMMANDS, DANCE, AUDIO, FACE, IDLE };
void begin();             // call first in setup(): reads the last reset, starts the watchdog
void at(Stage s);         // mark the stage about to run (and feed the watchdog)
const char *resetReason();
const char *lastStage();  // the stage that ran when the last reset happened (meaningful after a watchdog reset)
}  // namespace diag
