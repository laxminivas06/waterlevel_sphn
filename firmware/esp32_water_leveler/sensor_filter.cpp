/**
 * sensor_filter.cpp - 5-Stage Ultrasonic Filtering Implementation
 */

#include "sensor_filter.h"
#include <math.h>

SensorFilter::SensorFilter() 
    : _trigPin(PIN_TRIGGER), _echoPin(PIN_ECHO), _emaDistance(0.0f), _emaInitialized(false) {}

void SensorFilter::init(uint8_t trigPin, uint8_t echoPin) {
    _trigPin = trigPin;
    _echoPin = echoPin;
    pinMode(_trigPin, OUTPUT);
    digitalWrite(_trigPin, LOW);
    pinMode(_echoPin, INPUT);
    _emaInitialized = false;
}

void SensorFilter::resetEMA() {
    _emaInitialized = false;
    _emaDistance = 0.0f;
}

float SensorFilter::rawPingDistance(float speedOfSoundCmPerUs) {
    digitalWrite(_trigPin, LOW);
    delayMicroseconds(4);
    digitalWrite(_trigPin, HIGH);
    delayMicroseconds(10);
    digitalWrite(_trigPin, LOW);

    // Timeout: 30000 us (~5 meters roundtrip)
    unsigned long durationUs = pulseIn(_echoPin, HIGH, 30000UL);
    if (durationUs == 0) {
        return -1.0f; // Timeout / no echo
    }

    return (durationUs * speedOfSoundCmPerUs) / 2.0f;
}

void SensorFilter::sortAscending(float arr[], int size) {
    for (int i = 0; i < size - 1; ++i) {
        for (int j = 0; j < size - i - 1; ++j) {
            if (arr[j] > arr[j + 1]) {
                float tmp = arr[j];
                arr[j] = arr[j + 1];
                arr[j + 1] = tmp;
            }
        }
    }
}

float SensorFilter::measureFilteredDistance(float ambientTempC) {
    // Speed of sound: v = 331.3 + 0.606 * T (m/s) -> cm/us
    float speedOfSound = (331.3f + (0.606f * ambientTempC)) / 10000.0f;

    // Stage 1 & 2: Burst sampling with physical screening
    float samples[BURST_SAMPLE_COUNT];
    int validCount = 0;

    for (int i = 0; i < BURST_SAMPLE_COUNT; ++i) {
        float dist = rawPingDistance(speedOfSound);
        if (dist >= SENSOR_MIN_DISTANCE_CM && dist <= SENSOR_MAX_DISTANCE_CM) {
            samples[validCount++] = dist;
        }
        delay(BURST_SAMPLE_DELAY_MS);
    }

    if (validCount == 0) {
        // Fallback: If no valid pings, retain previous EMA or return max
        return _emaInitialized ? _emaDistance : -1.0f;
    }

    // Stage 3: Statistical Median Filter
    sortAscending(samples, validCount);
    float medianDist = samples[validCount / 2];

    // Stage 4: Delta Outlier Pruning
    float sumPruned = 0.0f;
    int prunedCount = 0;
    for (int i = 0; i < validCount; ++i) {
        if (fabsf(samples[i] - medianDist) <= OUTLIER_DELTA_MAX_CM) {
            sumPruned += samples[i];
            prunedCount++;
        }
    }

    float burstDistance = (prunedCount > 0) ? (sumPruned / prunedCount) : medianDist;

    // Stage 5: Inter-Cycle Exponential Moving Average (EMA)
    if (!_emaInitialized) {
        _emaDistance = burstDistance;
        _emaInitialized = true;
    } else {
        _emaDistance = (EMA_ALPHA * burstDistance) + ((1.0f - EMA_ALPHA) * _emaDistance);
    }

    return _emaDistance;
}

