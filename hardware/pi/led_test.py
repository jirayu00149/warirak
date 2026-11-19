"""Command the Warirak ESP8266 test LED over USB serial."""

import argparse
import math
from secrets import token_hex
import sys
import time

from usb_link import UsbLink, open_port

KEEPALIVE_SECONDS = 0.25


def set_led(link, on):
    state = "ON" if on else "OFF"
    nonce = token_hex(4)
    link.port.write(f"WRLED1 SET {nonce} {state}\n".encode("ascii"))
    expected = f"WRLED1 ACK {nonce} {state}".encode("ascii")
    if not link.wait_for(expected, timeout=0.35):
        raise RuntimeError(f"No ESP8266 LED ACK {state}; check the port and uploaded sketch")


def hold_on(link, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        started = time.monotonic()
        set_led(link, True)
        time.sleep(max(0, min(started + KEEPALIVE_SECONDS, deadline) - time.monotonic()))
    set_led(link, False)


def test_led(port_name, action, seconds, count):
    with open_port(port_name) as port:
        time.sleep(2)  # Allow boards that reset on USB serial open to boot.
        port.reset_input_buffer()
        link = UsbLink(port)
        try:
            set_led(link, False)
            print("ESP8266 connected. ACK OFF", flush=True)
            if action == "on":
                print(f"Turning LED on for {seconds:g} seconds", flush=True)
                hold_on(link, seconds)
            elif action == "blink":
                for index in range(count):
                    print(f"Blink {index + 1}/{count}", flush=True)
                    hold_on(link, 0.5)
                    if index + 1 < count:
                        time.sleep(0.5)
            print("Test complete. ACK OFF", flush=True)
        finally:
            try:
                set_led(link, False)
            except (OSError, RuntimeError):
                print("OFF was not acknowledged. The ESP8266 LED timer expires in 1 second.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("blink", "on", "off"))
    parser.add_argument("--port", default="/dev/ttyUSB0", help="Example: /dev/ttyUSB0 or COM9")
    parser.add_argument("--count", type=int, default=5, help="Number of blinks")
    parser.add_argument("--seconds", type=float, default=3, help="Time to hold the LED on")
    args = parser.parse_args()
    if not 1 <= args.count <= 30 or not math.isfinite(args.seconds) or not 0.05 <= args.seconds <= 60:
        parser.error("--count must be 1–30 and --seconds must be 0.05–60")
    try:
        test_led(args.port, args.action, args.seconds, args.count)
    except KeyboardInterrupt:
        return 130
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        print(f"LED test: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
