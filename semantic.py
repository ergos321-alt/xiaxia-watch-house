def classify_battery(values):
    level = values.get("batteryLevel")

    if not isinstance(level, (int, float)):
        return None

    if level >= 0.75:
        state = "high"
    elif level >= 0.40:
        state = "normal"
    elif level >= 0.20:
        state = "low"
    else:
        state = "critical"

    return {
        "level_percent": round(level * 100),
        "state": state,
        "charging": values.get("batteryState") in ("charging", "full"),
        "battery_state": values.get("batteryState"),
        "low_power_mode": values.get("lowPowerMode")
    }


def classify_light(values):
    lux = values.get("lux")

    if not isinstance(lux, (int, float)):
        return None

    if lux < 10:
        state = "dark"
    elif lux < 50:
        state = "dim"
    elif lux < 200:
        state = "normal"
    elif lux < 1000:
        state = "bright"
    else:
        state = "very_bright"

    return {
        "lux": round(lux, 1),
        "state": state
    }


def classify_microphone(values):
    dbfs = values.get("dBFS")

    if not isinstance(dbfs, (int, float)):
        return None

    if dbfs <= -50:
        state = "very_quiet"
    elif dbfs <= -35:
        state = "quiet"
    elif dbfs <= -20:
        state = "moderate"
    else:
        state = "loud"

    return {
        "dbfs": round(dbfs, 1),
        "relative_sound_level": state,
        "note": "Relative microphone level only; this is not calibrated dB SPL."
    }


def classify_activity(values):
    activity = values.get("activity")

    if not isinstance(activity, str):
        return None

    known = {
        "stationary": "stationary",
        "walking": "walking",
        "running": "running",
        "cycling": "cycling",
        "automotive": "in_vehicle"
    }

    return {
        "state": known.get(activity.lower(), activity.lower())
    }


def classify_network(values):
    connected = values.get("isConnected")
    reachable = values.get("internetReachable")
    network_type = values.get("type")
    strength = values.get("strength")

    if connected is False or reachable is False:
        return {
            "state": "offline",
            "type": network_type
        }

    quality = None

    if isinstance(strength, (int, float)):
        if strength >= 70:
            quality = "strong"
        elif strength >= 40:
            quality = "medium"
        else:
            quality = "weak"

    return {
        "state": "online",
        "type": network_type,
        "quality": quality,
        "strength": strength,
        "ssid": values.get("ssid")
    }


def classify_barometer(values):
    pressure = values.get("pressure")
    relative_altitude = values.get("relativeAltitude")

    if not isinstance(pressure, (int, float)):
        pressure = None

    if not isinstance(relative_altitude, (int, float)):
        relative_altitude = None

    if pressure is None and relative_altitude is None:
        return None

    return {
        "pressure_hpa": round(pressure, 1) if pressure is not None else None,
        "relative_altitude_m": (
            round(relative_altitude, 1)
            if relative_altitude is not None
            else None
        )
    }


def classify_location(values):
    latitude = values.get("latitude")
    longitude = values.get("longitude")

    if not isinstance(latitude, (int, float)):
        return None

    if not isinstance(longitude, (int, float)):
        return None

    result = {
        "available": True,
        "latitude": latitude,
        "longitude": longitude
    }

    horizontal_accuracy = values.get("horizontalAccuracy")
    speed = values.get("speed")

    if isinstance(horizontal_accuracy, (int, float)):
        result["accuracy_m"] = round(horizontal_accuracy, 1)

    if isinstance(speed, (int, float)):
        result["speed_m_s"] = round(speed, 2)

    return result


def classify_pedometer(values):
    steps = values.get("steps")

    if not isinstance(steps, (int, float)):
        return None

    return {
        "steps": int(steps)
    }


CLASSIFIERS = {
    "battery": classify_battery,
    "light": classify_light,
    "microphone": classify_microphone,
    "activity": classify_activity,
    "network": classify_network,
    "barometer": classify_barometer,
    "location": classify_location,
    "pedometer": classify_pedometer
}


def build_semantic_context(sensors):
    semantic = {}

    for sensor_name, sensor_data in sensors.items():

        # 过期的数据不能冒充“当前现实”
        if sensor_data.get("freshness") != "fresh":
            continue

        classifier = CLASSIFIERS.get(sensor_name)

        if classifier is None:
            continue

        values = sensor_data.get("values", {})
        interpreted = classifier(values)

        if interpreted is not None:
            semantic[sensor_name] = interpreted

    return semantic
