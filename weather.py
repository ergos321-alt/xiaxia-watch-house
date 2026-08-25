import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_CACHE_TTL_SECONDS = 300

_weather_cache = {}

CURRENT_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "is_day",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "pressure_msl",
    "surface_pressure",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
]


def weather_condition_from_code(code):
    mapping = {
        0: "clear",
        1: "mainly_clear",
        2: "partly_cloudy",
        3: "overcast",
        45: "fog",
        48: "rime_fog",
        51: "light_drizzle",
        53: "drizzle",
        55: "heavy_drizzle",
        56: "light_freezing_drizzle",
        57: "heavy_freezing_drizzle",
        61: "light_rain",
        63: "rain",
        65: "heavy_rain",
        66: "light_freezing_rain",
        67: "heavy_freezing_rain",
        71: "light_snow",
        73: "snow",
        75: "heavy_snow",
        77: "snow_grains",
        80: "light_rain_showers",
        81: "rain_showers",
        82: "heavy_rain_showers",
        85: "light_snow_showers",
        86: "heavy_snow_showers",
        95: "thunderstorm",
        96: "thunderstorm_with_light_hail",
        99: "thunderstorm_with_heavy_hail",
    }

    return mapping.get(code, "unknown")


def _cache_key(latitude, longitude):
    return (
        round(float(latitude), 3),
        round(float(longitude), 3),
    )


def fetch_current_weather(latitude, longitude):
    key = _cache_key(latitude, longitude)
    now = time.time()

    cached = _weather_cache.get(key)

    if cached and now - cached["cached_at"] <= WEATHER_CACHE_TTL_SECONDS:
        result = dict(cached["data"])
        result["cache"] = "hit"
        return result

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": ",".join(CURRENT_FIELDS),
        "timezone": "auto",
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }

    url = f"{OPEN_METEO_URL}?{urlencode(params)}"

    request = Request(
        url,
        headers={
            "User-Agent": "Xiaxia-Sense/0.3"
        },
    )

    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))

        current = payload.get("current")

        if not isinstance(current, dict):
            return {
                "available": False,
                "reason": "missing_current_weather"
            }

        weather_code = current.get("weather_code")

        result = {
            "available": True,
            "source": "open-meteo",
            "observed_at": current.get("time"),
            "timezone": payload.get("timezone"),
            "utc_offset_seconds": payload.get("utc_offset_seconds"),

            "temperature_c": current.get("temperature_2m"),
            "apparent_temperature_c": current.get("apparent_temperature"),
            "humidity_percent": current.get("relative_humidity_2m"),

            "is_day": current.get("is_day") == 1,

            "precipitation_mm": current.get("precipitation"),
            "weather_code": weather_code,
            "condition": weather_condition_from_code(weather_code),

            "cloud_cover_percent": current.get("cloud_cover"),

            "pressure_msl_hpa": current.get("pressure_msl"),
            "surface_pressure_hpa": current.get("surface_pressure"),

            "wind_speed_kmh": current.get("wind_speed_10m"),
            "wind_direction_deg": current.get("wind_direction_10m"),
            "wind_gusts_kmh": current.get("wind_gusts_10m"),

            "cache": "miss"
        }

        _weather_cache[key] = {
            "cached_at": now,
            "data": result
        }

        return result

    except (
        HTTPError,
        URLError,
        TimeoutError,
        ValueError,
        json.JSONDecodeError
    ):
        return {
            "available": False,
            "reason": "weather_request_failed"
        }


def build_weather_context(semantic):
    location = semantic.get("location")

    if not isinstance(location, dict):
        return {
            "available": False,
            "reason": "no_fresh_location"
        }

    latitude = location.get("latitude")
    longitude = location.get("longitude")

    if not isinstance(latitude, (int, float)):
        return {
            "available": False,
            "reason": "invalid_location"
        }

    if not isinstance(longitude, (int, float)):
        return {
            "available": False,
            "reason": "invalid_location"
        }

    return fetch_current_weather(
        latitude,
        longitude
    )
