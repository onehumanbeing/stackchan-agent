// Dances stored on the robot (FAT partition "ffat") and played on its own clock: no computer needed while it dances.
// A dance file is made and uploaded by the CLI (`stackchan dance upload`): servo goals sampled from the
// choreography's curves, already in raw units (calibration applied), plus face changes and the music.
//
// File /<name>.dnc, little endian:
//   "SCD1" u16 hz, u16 samples, u16 faces, u8 arm_ids[2], u32 pcm_bytes
//   samples x {i16 left_raw, i16 right_raw, i16 yaw_raw, i16 pitch_raw, i16 arm_speed}
//   faces   x {u32 ms, char name[12]}
//   pcm     16 kHz mono int16
#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

namespace dance {

void begin();                                                  // mounts the FAT partition (formats it the first time)
void upload(int client, const uint8_t *data, size_t len);     // one 'U' frame: u8 n, name[n], u32 offset, u32 total, bytes
const char *play(const String &name);                          // nullptr or an error
void stop();                                                   // music off, joints ease back to the last (neutral) pose
bool playing();
void status(JsonObject r);
void list(JsonObject r);
bool remove(const String &name);
void loop();                                                   // the dance clock; also: hold the screen 1 s = play "dance_1"

}  // namespace dance
