#include "diag.h"

#include <esp_system.h>
#include <esp_task_wdt.h>

namespace diag {
namespace {
constexpr uint32_t WDT_S = 10;
RTC_NOINIT_ATTR uint8_t crumb;   // survives a software / watchdog reset (not a power-off)
esp_reset_reason_t reason;
uint8_t last;
const char *const STAGES[] = {"none", "m5.update", "usb", "net", "commands", "dance", "audio", "face", "idle"};
}  // namespace

void begin() {
  reason = esp_reset_reason();
  last = crumb < sizeof(STAGES) / sizeof(*STAGES) ? crumb : NONE;
  crumb = NONE;
  esp_task_wdt_config_t cfg = {.timeout_ms = WDT_S * 1000, .idle_core_mask = 0, .trigger_panic = true};
  esp_task_wdt_reconfigure(&cfg);
  esp_task_wdt_add(nullptr);       // this task: loop()
}

void at(Stage s) {
  crumb = s;
  esp_task_wdt_reset();
}

const char *resetReason() {
  switch (reason) {
    case ESP_RST_POWERON: return "power-on";
    case ESP_RST_SW: return "software";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_INT_WDT: return "interrupt watchdog";
    case ESP_RST_TASK_WDT: return "task watchdog";
    case ESP_RST_WDT: return "watchdog";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_USB: return "usb";
    default: return "other";
  }
}

const char *lastStage() { return STAGES[last]; }
}  // namespace diag
