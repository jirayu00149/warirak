"""Warirak USB bench protocol. Every accepted message reports STOP."""
from secrets import token_hex
import time

BAUD = 115200
AIMS = ("NONE", "LEFT", "CENTER", "RIGHT")


class UsbLink:
    def __init__(self, serial_port):
        self.port = serial_port
        self.line = bytearray()
        self.discard_line = False

    def wait_for(self, expected, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            byte = self.port.read(1)
            if byte == b"\n":
                matched = not self.discard_line and self.line.rstrip(b"\r") == expected
                self.line.clear()
                self.discard_line = False
                if matched:
                    return True
            elif byte and not self.discard_line:
                if len(self.line) < 128:
                    self.line.extend(byte)
                else:
                    self.discard_line = True
        return False

    def ping(self, aim="NONE"):
        if aim not in AIMS:
            raise ValueError("Unsupported image aim")
        nonce = token_hex(4)
        packet = f"WR1 PING {nonce} {aim}\n".encode("ascii")
        self.port.write(packet)
        expected = f"WR1 ACK {nonce} {aim} STOP".encode("ascii")
        return self.wait_for(expected, timeout=0.35)


def open_port(name):
    import serial

    port = serial.Serial(baudrate=BAUD, timeout=0.02, write_timeout=0.15)
    port.port = name
    port.dtr = False
    port.rts = False
    port.open()
    return port


def check_link(name):
    with open_port(name) as port:
        time.sleep(2)  # Some USB-UART boards reset when their port is opened.
        port.reset_input_buffer()
        link = UsbLink(port)
        for aim in AIMS:
            if not link.ping(aim):
                raise RuntimeError(f"No matching STOP ACK for {aim}; check the port and sketch")
            print(f"ACK {aim} STOP", flush=True)
        if not link.wait_for(b"WR1 TIMEOUT STOP", timeout=1.5):
            raise RuntimeError("ESP32 did not report link timeout")
        if not link.ping():
            raise RuntimeError("ESP32 did not recover after timeout")
        print("PASS: STOP acknowledgement, link timeout, recovery", flush=True)
