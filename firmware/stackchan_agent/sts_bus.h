// Feetech STS bus servos (STS3215) over a half-duplex UART adapter (Waveshare Bus Servo Adapter A).
//
// Packet: FF FF id len instr params... chk, len = params + 2, chk = ~(id + len + instr + params).
// Reply:  FF FF id len err  params... chk.  Multi-byte registers are little endian; speed and load
// are sign-magnitude (bit 15 / bit 10).  The adapter may echo what we send; read() skips it.
#pragma once
#include <Arduino.h>

namespace sts {

enum Reg : uint8_t {
  ID = 5, BAUD = 6, MIN_ANGLE = 9, MAX_ANGLE = 11, TORQUE_ENABLE = 40, ACC = 41, GOAL_POS = 42,
  TORQUE_LIMIT = 48, LOCK = 55, PRESENT_POS = 56, PRESENT_SPEED = 58, PRESENT_LOAD = 60,
  VOLTAGE = 62, TEMP = 63, STATUS = 65, MOVING = 66,
};

struct State {       // one read of registers 56..66
  int pos;           // 0..4095, 2048 = middle
  int speed;         // steps/s, signed
  int load;          // 0.1 % of max torque, signed
  float volt;        // V
  int temp;          // deg C
  uint8_t status;    // error bits (voltage, sensor, temperature, current, angle, overload)
  bool moving;
};

class Bus {
 public:
  explicit Bus(HardwareSerial &port = Serial1) : port_(port) {}
  // Try `baud` on rx/tx; true if any of ids 1..probe_max answers a ping.
  bool begin(int rx, int tx, uint32_t baud, int probe_max = 12);
  void end();
  bool ok() const { return ok_; }
  int rx() const { return rx_; }
  int tx() const { return tx_; }
  uint32_t baud() const { return baud_; }
  uint32_t errors() const { return errors_; }   // checksum / framing errors (duplicate ids show up here)

  bool ping(uint8_t id, uint8_t *err = nullptr);
  bool read(uint8_t id, uint8_t addr, uint8_t *out, uint8_t n);
  bool write(uint8_t id, uint8_t addr, const uint8_t *data, uint8_t n);
  bool write8(uint8_t id, uint8_t addr, uint8_t v) { return write(id, addr, &v, 1); }
  bool write16(uint8_t id, uint8_t addr, uint16_t v);

  bool readState(uint8_t id, State &s);
  // Goal position with speed (steps/s, 0 = max) and acceleration (x100 steps/s^2, 0 = max).
  bool move(uint8_t id, int pos, int speed, int acc);
  // Same goal frame to several servos in one packet (they start together); no reply.
  void syncMove(const uint8_t *ids, const int *pos, int n, int speed, int acc);
  bool torque(uint8_t id, bool on) { return write8(id, TORQUE_ENABLE, on ? 1 : 0); }
  bool setId(uint8_t id, uint8_t new_id);
  // Diagnostic: broadcast ping on rx/tx at baud, return the raw bytes heard within 20 ms (echo included).
  int probe(int rx, int tx, uint32_t baud, uint8_t *out, int max);

 private:
  void send(uint8_t id, uint8_t instr, const uint8_t *params, uint8_t n);
  int reply(uint8_t id, uint8_t *params, uint8_t n, uint8_t *err);
  HardwareSerial &port_;
  bool ok_ = false;
  int rx_ = -1, tx_ = -1;
  uint32_t baud_ = 0, errors_ = 0;
  uint8_t sent_[64];
  int sent_n_ = 0;
};

inline int toSigned(uint16_t v, int sign_bit) { return (v & (1 << sign_bit)) ? -(int)(v & ((1 << sign_bit) - 1)) : v; }

}  // namespace sts
