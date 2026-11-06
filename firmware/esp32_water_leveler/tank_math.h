/**
 * tank_math.h - Tank Geometry & Volumetric Calculation Library
 */

#ifndef TANK_MATH_H
#define TANK_MATH_H

#include <Arduino.h>
#include "config.h"

struct TankMetrics {
    float distance_cm;
    float water_level_cm;
    float water_percentage;
    float water_litres;
    bool is_valid;
};

class TankMath {
public:
    TankMath();

    TankMetrics calculate(float distance_cm,
                          float tank_height_cm = TANK_HEIGHT_CM,
                          float sensor_offset_cm = SENSOR_OFFSET_CM,
                          float total_capacity_litres = TOTAL_CAPACITY_LITRES);
};

#endif // TANK_MATH_H

