// Persistent settings in NVS: bus pins / baud, per-servo soft limits, Wi-Fi networks.
// Wi-Fi passwords are only written here (set over USB with `stackchan wifi set`); they are never
// sent back by any command.
#pragma once
#include <Arduino.h>
#include <Preferences.h>

namespace settings {

constexpr int MAX_WIFI = 5;

struct BusCfg { int rx = -1, tx = -1; uint32_t baud = 1000000; };

inline Preferences &prefs() { static Preferences p; static bool open = p.begin("stackchan", false); (void)open; return p; }

inline BusCfg bus() {
  BusCfg c;
  c.rx = prefs().getInt("bus_rx", -1);
  c.tx = prefs().getInt("bus_tx", -1);
  c.baud = prefs().getUInt("bus_baud", 1000000);
  return c;
}
inline void setBus(const BusCfg &c) {
  prefs().putInt("bus_rx", c.rx), prefs().putInt("bus_tx", c.tx), prefs().putUInt("bus_baud", c.baud);
}

// Soft limits in raw steps (0..4095); default = full range.
inline void limits(int id, int &lo, int &hi) {
  char k[8];
  snprintf(k, sizeof(k), "lo%d", id), lo = prefs().getInt(k, 0);
  snprintf(k, sizeof(k), "hi%d", id), hi = prefs().getInt(k, 4095);
}
inline void setLimits(int id, int lo, int hi) {
  char k[8];
  snprintf(k, sizeof(k), "lo%d", id), prefs().putInt(k, lo);
  snprintf(k, sizeof(k), "hi%d", id), prefs().putInt(k, hi);
}

inline String wifiSsid(int i) { char k[4]; snprintf(k, sizeof(k), "s%d", i); return prefs().getString(k, ""); }
inline String wifiPass(int i) { char k[4]; snprintf(k, sizeof(k), "p%d", i); return prefs().getString(k, ""); }

// Add or replace a network; returns false when all slots are taken.
inline bool addWifi(const String &ssid, const String &pass) {
  int slot = -1;
  for (int i = 0; i < MAX_WIFI; i++) {
    String s = wifiSsid(i);
    if (s == ssid) { slot = i; break; }
    if (s.isEmpty() && slot < 0) slot = i;
  }
  if (slot < 0) return false;
  char k[4];
  snprintf(k, sizeof(k), "s%d", slot), prefs().putString(k, ssid);
  snprintf(k, sizeof(k), "p%d", slot), prefs().putString(k, pass);
  return true;
}
inline bool forgetWifi(const String &ssid) {
  for (int i = 0; i < MAX_WIFI; i++) {
    if (wifiSsid(i) != ssid) continue;
    char k[4];
    snprintf(k, sizeof(k), "s%d", i), prefs().remove(k);
    snprintf(k, sizeof(k), "p%d", i), prefs().remove(k);
    return true;
  }
  return false;
}

}  // namespace settings
