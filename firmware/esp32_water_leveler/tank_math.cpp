/**
 * tank_math.cpp - Volumetric & Level Equations Implementation
 */

#include "tank_math.h"
#include <algorithm>

TankMath::TankMath() {}

TankMetrics TankMath::calculate(float distance_cm,
                                float tank_height_cm,
                                float sensor_offset_cm,
                                float total_capacity_litres) {
    TankMetrics m;
    m.distance_cm = distance_cm;
    m.is_valid = (distance_cm >= 0.0f);

    if (!m.is_valid) {
        m.water_level_cm = 0.0f;
        m.water_percentage = 0.0f;
        m.water_litres = 0.0f;
        return m;
    }

    // Physics model:
    // Sensor mounted at (tank_height_cm + sensor_offset_cm)
    // Effective air gap = max(0.0, distance_cm - sensor_offset_cm)
    float airGap = distance_cm - sensor_offset_cm;
    if (airGap < 0.0f) {
        airGap = 0.0f;
    }

    // water_level_cm = max(0.0, min(tank_height_cm, tank_height_cm - airGap))
    float level = tank_height_cm - airGap;
    if (level < 0.0f) level = 0.0f;
    if (level > tank_height_cm) level = tank_height_cm;
    m.water_level_cm = level;

    // water_percentage = (water_level_cm / tank_height_cm) * 100.0
    float pct = (tank_height_cm > 0.0f) ? ((level / tank_height_cm) * 100.0f) : 0.0f;
    if (pct < 0.0f) pct = 0.0f;
    if (pct > 100.0f) pct = 100.0f;
    m.water_percentage = pct;

    // water_litres = (water_percentage / 100.0) * total_capacity_litres
    m.water_litres = (pct / 100.0f) * total_capacity_litres;
    if (m.water_litres < 0.0f) m.water_litres = 0.0f;

    return m;
}

