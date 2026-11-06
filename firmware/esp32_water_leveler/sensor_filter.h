/**
 * sensor_filter.h - 5-Stage Ultrasonic Digital Noise Filtering Pipeline
 */

#ifndef SENSOR_FILTER_H
#define SENSOR_FILTER_H

#include <Arduino.h>
#include "config.h"

class SensorFilter {
public:
    SensorFilter();

    void init(uint8_t trigPin, uint8_t echoPin);
    float measureFilteredDistance(float ambientTempC = AMBIENT_TEMPERATURE_C);
    void resetEMA();

private:
    uint8_t _trigPin;
    uint8_t _echoPin;
    float _emaDistance;
    bool _emaInitialized;

    float rawPingDistance(float speedOfSoundCmPerUs);
    void sortAscending(float arr[], int size);
};

#endif // SENSOR_FILTER_H

