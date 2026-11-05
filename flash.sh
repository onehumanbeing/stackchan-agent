#!/usr/bin/env bash
# Build and flash the StackChan (M5Stack CoreS3) over USB.
# Needs arduino-cli, the esp32 core 3.3.x and: M5Unified M5GFX ArduinoJson WebSockets
#   arduino-cli lib install M5Unified M5GFX ArduinoJson WebSockets
# Usage: ./flash.sh [port] [--build-only]
set -euo pipefail
cd "$(dirname "$0")"
FQBN="esp32:esp32:m5stack_cores3:PSRAM=enabled"
PORT="" BUILD_ONLY=0
for a in "$@"; do
  case $a in
    --build-only) BUILD_ONLY=1 ;;
    *) PORT=$a ;;
  esac
done
arduino-cli compile -b "$FQBN" --output-dir build firmware/stackchan_agent
(( BUILD_ONLY )) && exit 0
if [[ -z $PORT ]]; then
  for p in /dev/cu.usbmodem* /dev/ttyACM*; do [[ -e $p ]] && { PORT=$p; break; }; done
fi
[[ -n $PORT ]] || { echo "no StackChan on USB"; exit 1; }
arduino-cli upload -b "$FQBN" -p "$PORT" --input-dir build firmware/stackchan_agent
