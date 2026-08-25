def build_reality_context(
    semantic,
    weather,
    spatial=None
):
    """
    Build a compact, stable factual reality layer.

    This layer may describe:
    - device state
    - environment
    - network
    - location
    - weather
    - spatial scene
    - factual movement
    - personal place relations

    It must NOT infer:
    - user emotion
    - intention
    - desire
    - plans
    - needs
    - Xiaxia's reaction
    """

    if not isinstance(
        semantic,
        dict
    ):
        semantic = {}

    if not isinstance(
        weather,
        dict
    ):
        weather = {}

    if not isinstance(
        spatial,
        dict
    ):
        spatial = {}

    reality = {
        "user_state": {},
        "device": {},
        "environment": {},
        "network": {},
        "location": {},
        "weather": {},
        "spatial": {},
        "summary": {},
        "inferences": {
            "contexts": []
        }
    }

    summary = (
        reality[
            "summary"
        ]
    )

    contexts = (
        reality[
            "inferences"
        ][
            "contexts"
        ]
    )

    # =========================
    # Activity
    # =========================

    activity = (
        semantic.get(
            "activity"
        )
    )

    activity_state = None

    if isinstance(
        activity,
        dict
    ):
        activity_state = (
            activity.get(
                "state"
            )
        )

        if activity_state:
            reality[
                "user_state"
            ][
                "activity"
            ] = activity_state

    activity_mobility_map = {
        "stationary": "not_moving",
        "walking": "moving",
        "running": "moving",
        "cycling": "moving",
        "in_vehicle": "moving"
    }

    activity_mobility = (
        activity_mobility_map.get(
            activity_state
        )
    )

    if activity_mobility:
        summary[
            "activity_mobility"
        ] = activity_mobility

    # =========================
    # Battery
    # =========================

    battery = (
        semantic.get(
            "battery"
        )
    )

    if isinstance(
        battery,
        dict
    ):
        battery_percent = (
            battery.get(
                "level_percent"
            )
        )

        charging = (
            battery.get(
                "charging"
            )
        )

        battery_state = (
            battery.get(
                "state"
            )
        )

        low_power_mode = (
            battery.get(
                "low_power_mode"
            )
        )

        if battery_percent is not None:
            reality[
                "device"
            ][
                "battery_percent"
            ] = battery_percent

        if battery_state is not None:
            reality[
                "device"
            ][
                "battery_state"
            ] = battery_state

        if charging is not None:
            reality[
                "device"
            ][
                "charging"
            ] = charging

        if low_power_mode is not None:
            reality[
                "device"
            ][
                "low_power_mode"
            ] = low_power_mode

        if charging is True:
            summary[
                "device_power"
            ] = "charging"

            summary[
                "device_description"
            ] = "手机正在充电。"

        elif isinstance(
            battery_percent,
            (int, float)
        ):
            if battery_percent <= 10:
                summary[
                    "device_power"
                ] = "critical"

                summary[
                    "device_description"
                ] = "手机电量很低。"

            elif battery_percent <= 20:
                summary[
                    "device_power"
                ] = "low"

                summary[
                    "device_description"
                ] = "手机电量较低。"

            elif battery_percent >= 80:
                summary[
                    "device_power"
                ] = "high"

                summary[
                    "device_description"
                ] = "手机电量较充足。"

            else:
                summary[
                    "device_power"
                ] = "normal"

    # =========================
    # Light
    # =========================

    light = (
        semantic.get(
            "light"
        )
    )

    if isinstance(
        light,
        dict
    ):
        lux = (
            light.get(
                "lux"
            )
        )

        light_state = (
            light.get(
                "state"
            )
        )

        light_reality = {}

        if lux is not None:
            light_reality[
                "lux"
            ] = lux

        if light_state:
            light_reality[
                "state"
            ] = light_state

            summary[
                "ambient_light"
            ] = light_state

        if light_reality:
            reality[
                "environment"
            ][
                "light"
            ] = light_reality

    # =========================
    # Microphone
    # =========================

    microphone = (
        semantic.get(
            "microphone"
        )
    )

    if isinstance(
        microphone,
        dict
    ):
        sound_state = (
            microphone.get(
                "state"
            )
        )

        dbfs = (
            microphone.get(
                "dBFS"
            )
        )

        microphone_reality = {}

        if dbfs is not None:
            microphone_reality[
                "dBFS"
            ] = dbfs

        if sound_state:
            microphone_reality[
                "state"
            ] = sound_state

            summary[
                "ambient_sound"
            ] = sound_state

        if microphone_reality:
            reality[
                "environment"
            ][
                "microphone"
            ] = microphone_reality

    # =========================
    # Barometer
    # =========================

    barometer = (
        semantic.get(
            "barometer"
        )
    )

    if isinstance(
        barometer,
        dict
    ):
        barometer_reality = {}

        pressure = (
            barometer.get(
                "pressure_hpa"
            )
        )

        altitude = (
            barometer.get(
                "relative_altitude_m"
            )
        )

        if pressure is not None:
            barometer_reality[
                "pressure_hpa"
            ] = pressure

        if altitude is not None:
            barometer_reality[
                "relative_altitude_m"
            ] = altitude

        if barometer_reality:
            reality[
                "environment"
            ][
                "barometer"
            ] = barometer_reality

    # =========================
    # Network
    # =========================

    network = (
        semantic.get(
            "network"
        )
    )

    if isinstance(
        network,
        dict
    ):
        network_state = (
            network.get(
                "state"
            )
        )

        network_quality = (
            network.get(
                "quality"
            )
        )

        network_type = (
            network.get(
                "type"
            )
        )

        strength = (
            network.get(
                "strength"
            )
        )

        ssid = (
            network.get(
                "ssid"
            )
        )

        if network_state is not None:
            reality[
                "network"
            ][
                "state"
            ] = network_state

        if network_quality is not None:
            reality[
                "network"
            ][
                "quality"
            ] = network_quality

        if network_type is not None:
            reality[
                "network"
            ][
                "type"
            ] = network_type

        if strength is not None:
            reality[
                "network"
            ][
                "strength"
            ] = strength

        if ssid:
            reality[
                "network"
            ][
                "ssid"
            ] = ssid

        if network_state == "online":
            if network_quality == "strong":
                summary[
                    "connectivity"
                ] = "online_strong"

                summary[
                    "connectivity_description"
                ] = "手机网络连接良好。"

            elif network_quality:
                summary[
                    "connectivity"
                ] = (
                    f"online_{network_quality}"
                )

                summary[
                    "connectivity_description"
                ] = "手机当前已联网。"

            else:
                summary[
                    "connectivity"
                ] = "online"

                summary[
                    "connectivity_description"
                ] = "手机当前已联网。"

        elif network_state == "offline":
            summary[
                "connectivity"
            ] = "offline"

            summary[
                "connectivity_description"
            ] = "手机当前没有网络连接。"

    # =========================
    # Location
    # =========================

    location = (
        semantic.get(
            "location"
        )
    )

    if isinstance(
        location,
        dict
    ):
        available = (
            location.get(
                "available"
            )
        )

        reality[
            "location"
        ][
            "available"
        ] = bool(
            available
        )

        for key in (
            "latitude",
            "longitude",
            "accuracy_m",
            "speed_m_s"
        ):
            value = (
                location.get(
                    key
                )
            )

            if value is not None:
                reality[
                    "location"
                ][
                    key
                ] = value

        accuracy_m = (
            location.get(
                "accuracy_m"
            )
        )

        if isinstance(
            accuracy_m,
            (int, float)
        ):
            if accuracy_m <= 25:
                summary[
                    "location_quality"
                ] = "good"

            elif accuracy_m <= 60:
                summary[
                    "location_quality"
                ] = "usable"

            elif accuracy_m <= 100:
                summary[
                    "location_quality"
                ] = "approximate"

            else:
                summary[
                    "location_quality"
                ] = "poor"

    # =========================
    # Weather
    # =========================

    if weather.get(
        "available"
    ):
        weather_reality = {
            "available": True
        }

        temperature = (
            weather.get(
                "temperature_c"
            )
        )

        feels_like = (
            weather.get(
                "apparent_temperature_c"
            )
        )

        if feels_like is None:
            feels_like = (
                weather.get(
                    "feels_like_c"
                )
            )

        humidity = (
            weather.get(
                "humidity_percent"
            )
        )

        precipitation = (
            weather.get(
                "precipitation_mm"
            )
        )

        condition = (
            weather.get(
                "condition"
            )
        )

        wind_speed = (
            weather.get(
                "wind_speed_kmh"
            )
        )

        wind_direction = (
            weather.get(
                "wind_direction_deg"
            )
        )

        cloud_cover = (
            weather.get(
                "cloud_cover_percent"
            )
        )

        pressure_hpa = (
            weather.get(
                "surface_pressure_hpa"
            )
        )

        if pressure_hpa is None:
            pressure_hpa = (
                weather.get(
                    "pressure_hpa"
                )
            )

        for key, value in {
            "temperature_c": temperature,
            "feels_like_c": feels_like,
            "humidity_percent": humidity,
            "precipitation_mm": precipitation,
            "condition": condition,
            "wind_speed_kmh": wind_speed,
            "wind_direction_deg": wind_direction,
            "cloud_cover_percent": cloud_cover,
            "pressure_hpa": pressure_hpa,
            "timezone": weather.get(
                "timezone"
            )
        }.items():
            if value is not None:
                weather_reality[
                    key
                ] = value

        reality[
            "weather"
        ] = weather_reality

        # =========================
        # Thermal factual summary
        # =========================

        thermal_reference = (
            feels_like
            if isinstance(
                feels_like,
                (int, float)
            )
            else temperature
        )

        if isinstance(
            thermal_reference,
            (int, float)
        ):
            if thermal_reference >= 40:
                thermal_feel = (
                    "extremely_hot"
                )

            elif thermal_reference >= 35:
                thermal_feel = (
                    "very_hot"
                )

            elif thermal_reference >= 30:
                thermal_feel = (
                    "hot"
                )

            elif thermal_reference <= 5:
                thermal_feel = (
                    "very_cold"
                )

            elif thermal_reference <= 12:
                thermal_feel = (
                    "cold"
                )

            else:
                thermal_feel = (
                    "comfortable"
                )

            summary[
                "thermal_feel"
            ] = thermal_feel

        if isinstance(
            precipitation,
            (int, float)
        ):
            if precipitation > 0:
                summary[
                    "precipitation"
                ] = "rain"

            else:
                summary[
                    "precipitation"
                ] = "none"

        weather_description_parts = []

        thermal_text_map = {
            "extremely_hot": (
                "体感非常炎热"
            ),

            "very_hot": (
                "体感很热"
            ),

            "hot": (
                "体感偏热"
            ),

            "comfortable": (
                "体感温度较为温和"
            ),

            "cold": (
                "体感偏冷"
            ),

            "very_cold": (
                "体感很冷"
            )
        }

        thermal_feel = (
            summary.get(
                "thermal_feel"
            )
        )

        if thermal_feel in (
            thermal_text_map
        ):
            weather_description_parts.append(
                thermal_text_map[
                    thermal_feel
                ]
            )

        precipitation_state = (
            summary.get(
                "precipitation"
            )
        )

        if precipitation_state == "rain":
            weather_description_parts.append(
                "当前有降水"
            )

        elif precipitation_state == "none":
            weather_description_parts.append(
                "目前没有降水"
            )

        if weather_description_parts:
            summary[
                "weather_description"
            ] = (
                "，".join(
                    weather_description_parts
                )
                + "。"
            )

    else:
        reality[
            "weather"
        ] = {
            "available": False
        }

    # =========================
    # Environment description
    # =========================

    surroundings_parts = []

    light_state = (
        summary.get(
            "ambient_light"
        )
    )

    light_text_map = {
        "dark": (
            "周围环境较暗"
        ),

        "dim": (
            "周围光线较暗"
        ),

        "normal": (
            "周围光线一般"
        ),

        "bright": (
            "周围光线较亮"
        ),

        "very_bright": (
            "周围光线很亮"
        )
    }

    if light_state in (
        light_text_map
    ):
        surroundings_parts.append(
            light_text_map[
                light_state
            ]
        )

    sound_state = (
        summary.get(
            "ambient_sound"
        )
    )

    sound_text_map = {
        "quiet": (
            "周围声音较安静"
        ),

        "moderate": (
            "周围环境声音一般"
        ),

        "loud": (
            "周围声音较吵"
        ),

        "very_loud": (
            "周围环境很吵"
        )
    }

    if sound_state in (
        sound_text_map
    ):
        surroundings_parts.append(
            sound_text_map[
                sound_state
            ]
        )

    if surroundings_parts:
        summary[
            "surroundings_description"
        ] = (
            "；".join(
                surroundings_parts
            )
            + "。"
        )

    # =========================
    # Spatial
    # =========================

    if spatial:
        reality[
            "spatial"
        ] = spatial

    movement = (
        spatial.get(
            "movement"
        )
        if isinstance(
            spatial,
            dict
        )
        else None
    )

    # =========================
    # Spatial movement
    # =========================

    spatial_movement = None

    if isinstance(
        movement,
        dict
    ) and movement.get(
        "available"
    ):
        spatial_movement = {}

        for key in (
            "trend",
            "confidence",
            "location_quality",
            "effective_net_displacement_m",
            "filtered_path_distance_m",
            "direction_consistency",
            "direction"
        ):
            value = (
                movement.get(
                    key
                )
            )

            if value is not None:
                spatial_movement[
                    key
                ] = value

        if spatial_movement:
            summary[
                "spatial_movement"
            ] = spatial_movement

        movement_trend = (
            movement.get(
                "trend"
            )
        )

        movement_confidence = (
            movement.get(
                "confidence"
            )
        )

        if movement_trend == "moving":
            summary[
                "mobility"
            ] = "moving"

            summary[
                "mobility_confidence"
            ] = (
                movement_confidence
            )

            direction = (
                movement.get(
                    "direction"
                )
            )

            if direction:
                summary[
                    "mobility_description"
                ] = (
                    f"手机的位置变化显示"
                    f"正在向{direction}方向移动。"
                )

            else:
                summary[
                    "mobility_description"
                ] = (
                    "手机的位置变化显示"
                    "当前正在移动。"
                )

        elif movement_trend == "stable":
            summary[
                "mobility"
            ] = "not_moving"

            summary[
                "mobility_confidence"
            ] = (
                movement_confidence
            )

            summary[
                "mobility_description"
            ] = (
                "手机目前没有可靠证据"
                "显示正在移动。"
            )

        elif movement_trend == "uncertain":
            summary[
                "mobility"
            ] = "uncertain"

            summary[
                "mobility_confidence"
            ] = (
                movement_confidence
            )

            summary[
                "mobility_description"
            ] = (
                "当前定位数据不足以可靠判断"
                "是否正在移动。"
            )

    # 如果 spatial 没有足够运动信息，
    # 再使用 Activity 作为后备事实层
    if (
        "mobility"
        not in summary
        and activity_mobility
    ):
        summary[
            "mobility"
        ] = activity_mobility

        if activity_mobility == "moving":
            summary[
                "mobility_description"
            ] = (
                "手机活动状态显示当前正在移动。"
            )

        elif activity_mobility == "not_moving":
            summary[
                "mobility_description"
            ] = (
                "手机活动状态显示当前没有移动。"
            )

    # =========================
    # Scene
    # =========================

    scene = (
        spatial.get(
            "scene"
        )
        if isinstance(
            spatial,
            dict
        )
        else None
    )

    primary_scene = None

    if isinstance(
        scene,
        dict
    ):
        primary_scene = (
            scene.get(
                "primary_scene"
            )
        )

        secondary_scenes = (
            scene.get(
                "secondary_scenes",
                []
            )
        )

        scene_confidence = (
            scene.get(
                "confidence"
            )
        )

        if primary_scene:
            summary[
                "spatial_scene"
            ] = primary_scene

        if scene_confidence:
            summary[
                "spatial_scene_confidence"
            ] = scene_confidence

        if isinstance(
            secondary_scenes,
            list
        ) and secondary_scenes:
            summary[
                "spatial_secondary_scenes"
            ] = (
                secondary_scenes[:3]
            )

        if primary_scene:
            contexts.append({
                "value": (
                    f"{primary_scene}_environment"
                ),

                "confidence": (
                    scene_confidence
                    or "medium"
                ),

                "basis": [
                    "nearby_poi_distribution"
                ]
            })

    # =========================
    # Personal Places
    # =========================

    personal_relations = (
        spatial.get(
            "personal_place_relations",
            []
        )
        if isinstance(
            spatial,
            dict
        )
        else []
    )

    if not isinstance(
        personal_relations,
        list
    ):
        personal_relations = []

    summary[
        "personal_place_count"
    ] = len(
        personal_relations
    )

    nearest_place = (
        spatial.get(
            "nearest_personal_place"
        )
        if isinstance(
            spatial,
            dict
        )
        else None
    )

    if isinstance(
        nearest_place,
        dict
    ):
        normalized_nearest = {}

        for key in (
            "name",
            "kind",
            "distance_m",
            "radius_m",
            "inside",
            "status"
        ):
            value = (
                nearest_place.get(
                    key
                )
            )

            if value is not None:
                normalized_nearest[
                    key
                ] = value

        if normalized_nearest:
            summary[
                "nearest_personal_place"
            ] = normalized_nearest

    current_places = (
        spatial.get(
            "current_personal_places",
            []
        )
        if isinstance(
            spatial,
            dict
        )
        else []
    )

    normalized_current_places = []

    if isinstance(
        current_places,
        list
    ):
        for place in current_places:
            if not isinstance(
                place,
                dict
            ):
                continue

            normalized = {}

            for key in (
                "name",
                "kind",
                "distance_m",
                "radius_m",
                "status"
            ):
                value = (
                    place.get(
                        key
                    )
                )

                if value is not None:
                    normalized[
                        key
                    ] = value

            if normalized:
                normalized_current_places.append(
                    normalized
                )

    if normalized_current_places:
        summary[
            "current_personal_places"
        ] = normalized_current_places

        first_place = (
            normalized_current_places[
                0
            ]
        )

        place_name = (
            first_place.get(
                "name"
            )
        )

        if place_name:
            contexts.append({
                "value": (
                    "inside_personal_place"
                ),

                "confidence": "high",

                "basis": [
                    f"place:{place_name}"
                ]
            })

    # =========================
    # Personal Place Trends
    # =========================

    place_trends = (
        spatial.get(
            "personal_place_trends",
            []
        )
        if isinstance(
            spatial,
            dict
        )
        else []
    )

    normalized_trends = []

    if isinstance(
        place_trends,
        list
    ):
        meaningful_trends = (
            "entered",
            "left",
            "approaching",
            "moving_away",
            "inside"
        )

        for item in place_trends:
            if not isinstance(
                item,
                dict
            ):
                continue

            trend = (
                item.get(
                    "trend"
                )
            )

            if trend not in (
                meaningful_trends
            ):
                continue

            normalized = {}

            for key in (
                "name",
                "kind",
                "trend",
                "current_distance_m",
                "distance_change_m",
                "current_inside",
                "current_boundary_state",
                "trend_uncertainty_m",
                "entered_at",
                "left_at"
            ):
                value = (
                    item.get(
                        key
                    )
                )

                if value is not None:
                    normalized[
                        key
                    ] = value

            if normalized:
                normalized_trends.append(
                    normalized
                )

    if normalized_trends:
        summary[
            "personal_place_trends"
        ] = (
            normalized_trends[:10]
        )

    # =========================
    # Spatial description
    #
    # 注意：
    # spatial.description 本身已经包含 Personal Place。
    # 所以 overall_description 不再额外重复拼接
    # personal_place_description。
    # =========================

    spatial_description = (
        spatial.get(
            "description"
        )
        if isinstance(
            spatial,
            dict
        )
        else None
    )

    if spatial_description:
        summary[
            "spatial_description"
        ] = spatial_description

    # =========================
    # 独立 Personal Place description
    #
    # 这个字段保留给 GPT 精确读取，
    # 但不会再和 spatial_description
    # 一起重复进入 overall_description。
    # =========================

    personal_description_parts = []

    if normalized_current_places:
        if len(
            normalized_current_places
        ) == 1:
            place_name = (
                normalized_current_places[
                    0
                ].get(
                    "name"
                )
            )

            if place_name:
                personal_description_parts.append(
                    f"当前位于个人地点"
                    f"“{place_name}”范围内"
                )

        else:
            names = [
                item.get(
                    "name"
                )
                for item in (
                    normalized_current_places
                )
                if item.get(
                    "name"
                )
            ]

            if names:
                personal_description_parts.append(
                    "当前位置同时位于个人地点"
                    + "、".join(
                        f"“{name}”"
                        for name in names
                    )
                    + "范围内"
                )

    elif isinstance(
        nearest_place,
        dict
    ):
        nearest_name = (
            nearest_place.get(
                "name"
            )
        )

        nearest_distance = (
            nearest_place.get(
                "distance_m"
            )
        )

        nearest_status = (
            nearest_place.get(
                "status"
            )
        )

        if (
            nearest_name
            and isinstance(
                nearest_distance,
                (int, float)
            )
        ):
            if nearest_status == "nearby":
                personal_description_parts.append(
                    f"当前在个人地点"
                    f"“{nearest_name}”附近，"
                    f"直线距离约"
                    f"{round(nearest_distance)}米"
                )

            elif nearest_status == "away":
                personal_description_parts.append(
                    f"当前最近的个人地点是"
                    f"“{nearest_name}”，"
                    f"直线距离约"
                    f"{round(nearest_distance)}米"
                )

    # 趋势只添加真正有变化意义的内容
    for item in normalized_trends[:5]:
        trend = (
            item.get(
                "trend"
            )
        )

        name = (
            item.get(
                "name"
            )
        )

        distance = (
            item.get(
                "current_distance_m"
            )
        )

        if not name:
            continue

        if trend == "entered":
            personal_description_parts.append(
                f"短期位置历史显示"
                f"已进入个人地点"
                f"“{name}”范围"
            )

        elif trend == "left":
            personal_description_parts.append(
                f"短期位置历史显示"
                f"已离开个人地点"
                f"“{name}”范围"
            )

        elif trend == "approaching":
            if isinstance(
                distance,
                (int, float)
            ):
                personal_description_parts.append(
                    f"短期位置历史显示"
                    f"正在接近个人地点"
                    f"“{name}”，"
                    f"目前约"
                    f"{round(distance)}米"
                )

            else:
                personal_description_parts.append(
                    f"短期位置历史显示"
                    f"正在接近个人地点"
                    f"“{name}”"
                )

        elif trend == "moving_away":
            personal_description_parts.append(
                f"短期位置历史显示"
                f"正在远离个人地点"
                f"“{name}”"
            )

    if personal_description_parts:
        # 去重，保持原顺序
        seen = set()
        unique_parts = []

        for part in (
            personal_description_parts
        ):
            if part in seen:
                continue

            seen.add(
                part
            )

            unique_parts.append(
                part
            )

        summary[
            "personal_place_description"
        ] = (
            "；".join(
                unique_parts
            )
            + "。"
        )

    # =========================
    # Factual contexts
    # =========================

    thermal_feel = (
        summary.get(
            "thermal_feel"
        )
    )

    if thermal_feel in (
        "hot",
        "very_hot",
        "extremely_hot"
    ):
        contexts.append({
            "value": (
                "hot_environment"
            ),

            "confidence": "high",

            "basis": [
                thermal_feel
            ]
        })

    precipitation_state = (
        summary.get(
            "precipitation"
        )
    )

    if precipitation_state == "rain":
        contexts.append({
            "value": (
                "rainy_environment"
            ),

            "confidence": "high",

            "basis": [
                "precipitation_detected"
            ]
        })

    mobility = (
        summary.get(
            "mobility"
        )
    )

    if mobility == "moving":
        contexts.append({
            "value": (
                "moving_environment"
            ),

            "confidence": (
                summary.get(
                    "mobility_confidence"
                )
                or "medium"
            ),

            "basis": [
                "spatial_movement"
            ]
        })

    elif (
        mobility
        == "not_moving"
    ):
        contexts.append({
            "value": (
                "resting_environment"
            ),

            "confidence": (
                summary.get(
                    "mobility_confidence"
                )
                or "medium"
            ),

            "basis": [
                "spatial_movement"
            ]
        })

    # =========================
    # Overall description
    #
    # Personal Place 不再单独追加，
    # 因为 spatial_description 已包含它。
    # =========================

    description_parts = []

    for key in (
        "weather_description",
        "surroundings_description",
        "mobility_description",
        "device_description",
        "connectivity_description",
        "spatial_description"
    ):
        value = (
            summary.get(
                key
            )
        )

        if not value:
            continue

        cleaned = str(
            value
        ).strip()

        if not cleaned:
            continue

        cleaned = cleaned.rstrip(
            "。； "
        )

        if cleaned:
            description_parts.append(
                cleaned
            )

    # 再做一层完整片段去重
    seen_descriptions = set()
    unique_descriptions = []

    for item in description_parts:
        if item in (
            seen_descriptions
        ):
            continue

        seen_descriptions.add(
            item
        )

        unique_descriptions.append(
            item
        )

    if unique_descriptions:
        summary[
            "overall_description"
        ] = (
            "；".join(
                unique_descriptions
            )
            + "。"
        )

    return reality
