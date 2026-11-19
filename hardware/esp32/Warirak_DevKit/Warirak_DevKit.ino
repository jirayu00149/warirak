#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <cstring>

// Bench firmware for USB link and physical mode selection.
// Aim is image metadata. All acknowledgements report STOP.
#if defined(ARDUINO_ARCH_ESP8266)
constexpr uint8_t MODE_BUTTON_PIN = 14;  // D5 on NodeMCU
#else
constexpr uint8_t MODE_BUTTON_PIN = 27;  // ESP32 DevKit
#endif
constexpr uint32_t MODE_DEBOUNCE_MS = 30;
constexpr uint8_t OLED_WIDTH = 128;
constexpr uint8_t OLED_HEIGHT = 64;
constexpr uint8_t OLED_ADDRESSES[] = {0x3C, 0x3D};
constexpr uint32_t LINK_TIMEOUT_MS = 400;
constexpr size_t NONCE_LENGTH = 8;
constexpr char PREFIX[] = "WR1 PING ";

enum class ControlMode { Manual, Auto };
ControlMode controlMode = ControlMode::Manual;
bool lastButtonPressed = false;
bool stableButtonPressed = false;
uint32_t buttonChangedMs = 0;
Adafruit_SSD1306 oled(OLED_WIDTH, OLED_HEIGHT, &Wire, -1);
bool oledReady = false;

char line[40];
size_t lineLength = 0;
bool discardLine = false;
bool linkActive = false;
uint32_t lastPingMs = 0;

bool beginOled() {
  Wire.begin();
  for (const uint8_t address : OLED_ADDRESSES) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      return oled.begin(SSD1306_SWITCHCAPVCC, address, false, false);
    }
  }
  return false;
}

void reportControlMode() {
  const char* modeName = controlMode == ControlMode::Manual ? "MANUAL" : "AUTO";
  Serial.printf("WR1 MODE %s\n", modeName);
  if (!oledReady) return;

  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(3);
  int16_t textX, textY;
  uint16_t textWidth, textHeight;
  oled.getTextBounds(modeName, 0, 0, &textX, &textY, &textWidth, &textHeight);
  oled.setCursor((OLED_WIDTH - textWidth) / 2 - textX,
                 (OLED_HEIGHT - textHeight) / 2 - textY);
  oled.print(modeName);
  oled.display();
}

void updateModeButton(uint32_t now) {
  const bool pressed = digitalRead(MODE_BUTTON_PIN) == LOW;
  if (pressed != lastButtonPressed) {
    lastButtonPressed = pressed;
    buttonChangedMs = now;
  }
  if (pressed == stableButtonPressed || now - buttonChangedMs < MODE_DEBOUNCE_MS) {
    return;
  }

  stableButtonPressed = pressed;
  if (stableButtonPressed) {
    controlMode = controlMode == ControlMode::Manual ? ControlMode::Auto : ControlMode::Manual;
    reportControlMode();
  }
}

bool validHex(char value) {
  return (value >= '0' && value <= '9') || (value >= 'a' && value <= 'f');
}

void acknowledgePing() {
  constexpr size_t start = sizeof(PREFIX) - 1;
  constexpr size_t separator = start + NONCE_LENGTH;
  if (lineLength <= separator || strncmp(line, PREFIX, start) != 0 || line[separator] != ' ') {
    return;
  }
  for (size_t i = start; i < separator; ++i) {
    if (!validHex(line[i])) return;
  }
  const char* aim = line + separator + 1;
  if (strcmp(aim, "NONE") != 0 && strcmp(aim, "LEFT") != 0 &&
      strcmp(aim, "CENTER") != 0 && strcmp(aim, "RIGHT") != 0) {
    return;
  }

  lastPingMs = millis();
  linkActive = true;
  line[separator] = '\0';
  Serial.printf("WR1 ACK %s %s STOP\n", line + start, aim);
}

void readByte(char value) {
  if (value == '\n') {
    if (!discardLine) {
      if (lineLength > 0 && line[lineLength - 1] == '\r') --lineLength;
      line[lineLength] = '\0';
      acknowledgePing();
    }
    lineLength = 0;
    discardLine = false;
    return;
  }
  if (discardLine) return;
  if (value == '\0' || lineLength >= sizeof(line) - 1) {
    discardLine = true;
    return;
  }
  line[lineLength++] = value;
}

void setup() {
  pinMode(MODE_BUTTON_PIN, INPUT_PULLUP);
  lastButtonPressed = digitalRead(MODE_BUTTON_PIN) == LOW;
  stableButtonPressed = lastButtonPressed;

  Serial.begin(115200);
  Serial.println("WR1 READY STOP");
  oledReady = beginOled();
  if (!oledReady) Serial.println("WR1 OLED UNAVAILABLE");
  reportControlMode();
}

void loop() {
  const uint32_t now = millis();
  updateModeButton(now);
  if (linkActive && now - lastPingMs >= LINK_TIMEOUT_MS) {
    linkActive = false;
    Serial.println("WR1 TIMEOUT STOP");
  }
  // Limit work per loop so a noisy serial stream cannot starve the timer check.
  for (unsigned int i = 0; i < 64 && Serial.available() > 0; ++i) {
    readByte(static_cast<char>(Serial.read()));
  }
  delay(1);
}
