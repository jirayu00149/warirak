#include <Arduino.h>
#include <cstring>

constexpr uint8_t LED_PIN = 12;  // D6 on NodeMCU ESP8266
constexpr uint32_t LED_TIMEOUT_MS = 1000;
constexpr char PREFIX[] = "WRLED1 SET ";
constexpr size_t NONCE_LENGTH = 8;

char command[32];
size_t commandLength = 0;
bool discardCommand = false;
bool ledOn = false;
uint32_t lastOnMs = 0;

void setLed(bool on) {
  ledOn = on;
  digitalWrite(LED_PIN, on ? HIGH : LOW);
}

void handleCommand() {
  constexpr size_t nonceStart = sizeof(PREFIX) - 1;
  constexpr size_t separator = nonceStart + NONCE_LENGTH;
  if (commandLength <= separator || strncmp(command, PREFIX, nonceStart) != 0 ||
      command[separator] != ' ') {
    return;
  }
  for (size_t index = nonceStart; index < separator; ++index) {
    const char digit = command[index];
    if (!((digit >= '0' && digit <= '9') || (digit >= 'a' && digit <= 'f'))) {
      return;
    }
  }
  const char* state = command + separator + 1;
  if (strcmp(state, "ON") != 0 && strcmp(state, "OFF") != 0) {
    return;
  }
  const bool on = strcmp(state, "ON") == 0;
  if (on) {
    lastOnMs = millis();
  }
  setLed(on);
  command[separator] = '\0';
  Serial.printf("WRLED1 ACK %s %s\n", command + nonceStart, on ? "ON" : "OFF");
}

void readByte(char value) {
  if (value == '\n') {
    if (!discardCommand) {
      if (commandLength && command[commandLength - 1] == '\r') {
        --commandLength;
      }
      command[commandLength] = '\0';
      handleCommand();
    }
    commandLength = 0;
    discardCommand = false;
    return;
  }
  if (discardCommand) {
    return;
  }
  if (value == '\0' || commandLength >= sizeof(command) - 1) {
    discardCommand = true;
    return;
  }
  command[commandLength++] = value;
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  setLed(false);
  Serial.begin(115200);
  Serial.println("WRLED1 READY OFF");
}

void loop() {
  if (ledOn && millis() - lastOnMs >= LED_TIMEOUT_MS) {
    setLed(false);
    Serial.println("WRLED1 TIMEOUT OFF");
  }
  for (unsigned int count = 0; count < 64 && Serial.available() > 0; ++count) {
    readByte(static_cast<char>(Serial.read()));
  }
  delay(1);
}
