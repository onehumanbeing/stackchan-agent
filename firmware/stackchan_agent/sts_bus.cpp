#include "sts_bus.h"

namespace sts {

namespace {
constexpr uint8_t PING = 0x01, READ = 0x02, WRITE = 0x03, SYNC_WRITE = 0x83, BROADCAST = 0xFE;
constexpr uint32_t REPLY_TIMEOUT_US = 3000;
}  // namespace

bool Bus::begin(int rx, int tx, uint32_t baud, int probe_max) {
  end();
  port_.begin(baud, SERIAL_8N1, rx, tx);
  port_.setTimeout(2);
  rx_ = rx, tx_ = tx, baud_ = baud;
  delay(5);
  for (int id = 1; id <= probe_max; id++) {
    if (ping(id)) return ok_ = true;
  }
  return ok_ = false;
}

int Bus::probe(int rx, int tx, uint32_t baud, uint8_t *out, int max) {
  end();
  port_.begin(baud, SERIAL_8N1, rx, tx);
  delay(5);
  send(BROADCAST, PING, nullptr, 0);
  int n = 0;
  uint32_t t0 = millis();
  while (n < max && millis() - t0 < 20) if (port_.available()) out[n++] = port_.read();
  end();
  return n;
}

void Bus::end() {
  if (baud_) port_.end();
  ok_ = false;
  baud_ = 0;
}

void Bus::send(uint8_t id, uint8_t instr, const uint8_t *params, uint8_t n) {
  while (port_.available()) port_.read();
  uint8_t *p = sent_;
  uint8_t sum = id + (n + 2) + instr;
  *p++ = 0xFF, *p++ = 0xFF, *p++ = id, *p++ = n + 2, *p++ = instr;
  for (int i = 0; i < n; i++) sum += params[i], *p++ = params[i];
  *p++ = ~sum;
  sent_n_ = p - sent_;
  port_.write(sent_, sent_n_);
  port_.flush();
}

// Read one reply from `id` into params (n bytes).  Returns n, or -1 on timeout / bad packet.
int Bus::reply(uint8_t id, uint8_t *params, uint8_t n, uint8_t *err) {
  uint8_t buf[64];
  int got = 0, want = 6 + n;
  bool echo = true;      // bytes so far match what we sent
  uint32_t t0 = micros();
  while (got < (int)sizeof(buf) && micros() - t0 < REPLY_TIMEOUT_US) {
    if (!port_.available()) continue;
    buf[got++] = port_.read();
    if (echo) {
      if (buf[got - 1] != sent_[got - 1]) echo = false;
      else if (got == sent_n_) { got = 0, echo = false; continue; }   // our whole packet came back: drop it
      else continue;
    }
    if (got >= 2 && !(buf[0] == 0xFF && buf[1] == 0xFF)) {            // resync on the header
      memmove(buf, buf + 1, --got);
    }
    if (got >= want) break;
  }
  if (got < want) return -1;
  uint8_t sum = 0;
  for (int i = 2; i < want - 1; i++) sum += buf[i];
  if (buf[2] != id || buf[3] != n + 2 || (uint8_t)~sum != buf[want - 1]) {
    errors_++;
    return -1;
  }
  if (err) *err = buf[4];
  memcpy(params, buf + 5, n);
  return n;
}

bool Bus::ping(uint8_t id, uint8_t *err) {
  send(id, PING, nullptr, 0);
  return reply(id, nullptr, 0, err) == 0;
}

bool Bus::read(uint8_t id, uint8_t addr, uint8_t *out, uint8_t n) {
  uint8_t p[2] = {addr, n};
  send(id, READ, p, 2);
  return reply(id, out, n, nullptr) == n;
}

bool Bus::write(uint8_t id, uint8_t addr, const uint8_t *data, uint8_t n) {
  uint8_t p[32];
  p[0] = addr;
  memcpy(p + 1, data, n);
  send(id, WRITE, p, n + 1);
  return id == BROADCAST || reply(id, nullptr, 0, nullptr) == 0;
}

bool Bus::write16(uint8_t id, uint8_t addr, uint16_t v) {
  uint8_t d[2] = {(uint8_t)(v & 0xFF), (uint8_t)(v >> 8)};
  return write(id, addr, d, 2);
}

bool Bus::readState(uint8_t id, State &s) {
  uint8_t b[11];   // 56..66
  if (!read(id, PRESENT_POS, b, sizeof(b))) return false;
  s.pos = b[0] | b[1] << 8;
  s.speed = toSigned(b[2] | b[3] << 8, 15);
  s.load = toSigned(b[4] | b[5] << 8, 10);
  s.volt = b[6] / 10.0f;
  s.temp = b[7];
  s.status = b[9];
  s.moving = b[10];
  return true;
}

static void goalFrame(uint8_t *d, int pos, int speed, int acc) {   // registers 41..47
  pos = constrain(pos, 0, 4095);
  d[0] = constrain(acc, 0, 254);
  d[1] = pos & 0xFF, d[2] = pos >> 8;
  d[3] = 0, d[4] = 0;                         // goal time unused
  d[5] = speed & 0xFF, d[6] = (speed >> 8) & 0x7F;
}

bool Bus::move(uint8_t id, int pos, int speed, int acc) {
  uint8_t d[7];
  goalFrame(d, pos, speed, acc);
  return write(id, ACC, d, 7);
}

void Bus::syncMove(const uint8_t *ids, const int *pos, int n, int speed, int acc) {
  uint8_t p[2 + 8 * 8];
  n = min(n, 8);
  p[0] = ACC, p[1] = 7;
  for (int i = 0; i < n; i++) {
    p[2 + 8 * i] = ids[i];
    goalFrame(p + 3 + 8 * i, pos[i], speed, acc);
  }
  send(BROADCAST, SYNC_WRITE, p, 2 + 8 * n);
}

bool Bus::setId(uint8_t id, uint8_t new_id) {
  if (!write8(id, LOCK, 0)) return false;           // unlock EEPROM
  if (!write8(id, ID, new_id)) return false;
  delay(5);
  return write8(new_id, LOCK, 1);
}

}  // namespace sts
