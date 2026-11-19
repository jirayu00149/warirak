#include <Arduino.h>

constexpr uint8_t TRIG_PIN = 13;  // D7 on NodeMCU ESP8266
constexpr uint8_t ECHO_PIN = 16;  // D0 on NodeMCU ESP8266
constexpr unsigned long ECHO_TIMEOUT_US = 45000;
constexpr unsigned long PASSIVE_TIMEOUT_US = 750000;

void reportPulse(const char* mode, unsigned long echoUs) {
  Serial.print(mode);
  if (echoUs == 0) {
    Serial.println(" NO ECHO");
    return;
  }

  const float distanceCm = echoUs / 58.0f;
  Serial.print(" ECHO ");
  Serial.print(echoUs);
  Serial.print(" us | ");
  if (distanceCm < 25.0f || distanceCm > 600.0f) {
    Serial.println("OUT OF RANGE");
    return;
  }
  Serial.print("Distance ");
  Serial.print(distanceCm, 1);
  Serial.println(" cm");
}

void checkLoopback() {
  // Disconnect the sensor and bridge D7 to D0 before sending L.
  pinMode(ECHO_PIN, INPUT_PULLDOWN_16);
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(100);
  const bool sawLow = digitalRead(ECHO_PIN) == LOW;
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(100);
  const bool sawHigh = digitalRead(ECHO_PIN) == HIGH;
  digitalWrite(TRIG_PIN, LOW);
  pinMode(ECHO_PIN, INPUT);
  Serial.printf("LOOPBACK %s | D0 at LOW: %d | D0 at HIGH: %d\n",
                sawLow && sawHigh ? "PASS" : "FAIL", !sawLow, sawHigh);
}

void setup() {
  pinMode(TRIG_PIN, OUTPUT);
  digitalWrite(TRIG_PIN, LOW);
  pinMode(ECHO_PIN, INPUT);
  Serial.begin(115200);
  Serial.println("WARIRAK SONAR DIAGNOSTIC | L: D7 to D0 with sensor disconnected");
}

void loop() {
  while (Serial.available()) {
    const int command = Serial.read();
    if (command == 'L' || command == 'l') {
      checkLoopback();
      delay(500);
      return;
    }
  }

  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(25);
  digitalWrite(TRIG_PIN, LOW);

  const unsigned long echoUs = pulseIn(ECHO_PIN, HIGH, ECHO_TIMEOUT_US);
  reportPulse("TRIG", echoUs);
  if (echoUs == 0) {
    Serial.printf("D0 idle %s\n", digitalRead(ECHO_PIN) == HIGH ? "HIGH" : "LOW");
    // Listen with TRIG held LOW for modules that emit pulses periodically.
    reportPulse("LISTEN", pulseIn(ECHO_PIN, HIGH, PASSIVE_TIMEOUT_US));
  }
  delay(500);
}
