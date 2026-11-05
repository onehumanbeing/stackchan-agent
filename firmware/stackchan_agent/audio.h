// CoreS3 microphone and speaker, half duplex (they cannot run at the same time on this board).
// Mic: 16 kHz mono int16 chunks of 40 ms, captured by a task, handed to the main loop for sending.
// Speaker: the client streams 16 kHz mono int16 chunks; they are copied and played in order.
#pragma once
#include <Arduino.h>

namespace audio {

constexpr uint32_t RATE = 16000;
constexpr size_t CHUNK = 640;            // samples per mic chunk (40 ms)

void begin();
bool micStart(int client);               // stops the speaker first; false if it is still playing
void micStop();
int micClient();                         // -1 when the mic is off
bool micChunk(int16_t *out);             // next captured chunk (CHUNK samples), if any
void play(const uint8_t *pcm, size_t bytes);   // queue speaker audio (switches the mic off)
void stop();                             // drop queued speaker audio
bool playing();
void setVolume(int v);                   // 0..255
void loop();                             // feeds the speaker queue

}  // namespace audio
