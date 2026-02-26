"""
Weather & Marine service — uses Open-Meteo (free, no API key needed).

Open-Meteo provides:
- Geocoding: port name → lat/lon
- Weather forecast: temp, wind, precip, humidity, UV
- Marine forecast: hourly wave height, swell, wave period

All endpoints are completely free with no registration required.
"""

import httpx
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

MAX_FORECAST_DAYS = 16


def fetch_delivery_environment(port_name: str, country_name: str, delivery_date_str: str, db=None) -> dict:
    """Fetch weather + marine data for a port on a delivery date. No API key needed."""

    location = f"{port_name}, {country_name}"

    # 1. Geocode port name → coordinates
    lat, lon = _geocode(port_name, country_name)

    # 2. Check if date is within forecast range (~16 days)
    try:
        delivery_date = date.fromisoformat(delivery_date_str)
    except ValueError:
        delivery_date = date.today()
    days_ahead = (delivery_date - date.today()).days

    if days_ahead > MAX_FORECAST_DAYS:
        # Date is beyond forecast range — return early with notice
        return {
            "location": location,
            "date": delivery_date_str,
            "coordinates": {"lat": lat, "lon": lon},
            "tides": [],
            "weather": {},
            "marine": {"max_wave_height_m": None, "max_wave_period_s": None, "hourly_waves": []},
            "ai_summary": "",
            "forecast_available": False,
            "days_until_available": days_ahead - MAX_FORECAST_DAYS,
            "fetched_at": datetime.utcnow().isoformat(),
            "source": "open-meteo.com",
        }

    # 3. Fetch weather forecast
    weather = _fetch_weather(lat, lon, delivery_date_str)

    # 4. Fetch marine / wave data
    marine = _fetch_marine(lat, lon, delivery_date_str)

    # 5. AI summary
    summary = _generate_summary(location, delivery_date_str, weather, marine)

    return {
        "location": location,
        "date": delivery_date_str,
        "coordinates": {"lat": lat, "lon": lon},
        "tides": [],
        "weather": weather,
        "marine": marine,
        "ai_summary": summary,
        "forecast_available": True,
        "fetched_at": datetime.utcnow().isoformat(),
        "source": "open-meteo.com",
    }


def _geocode(port_name: str, country_name: str) -> tuple[float, float]:
    """Geocode port name to (lat, lon).

    Strategy: try Open-Meteo geocoding first (fast, free).
    If that fails, ask LLM for coordinates (handles any port name format).
    """
    # 1. Quick try: direct geocoding with port name
    result = _geocode_openmeteo(port_name)
    if result:
        return result

    # 2. Fallback: LLM knows where ports are
    logger.info("Open-Meteo geocode failed for '%s', falling back to LLM", port_name)
    return _geocode_llm(port_name, country_name)


def _geocode_openmeteo(query: str) -> tuple[float, float] | None:
    """Try Open-Meteo geocoding API. Returns None if not found."""
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(GEOCODING_URL, params={"name": query, "count": 3})
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                r = results[0]
                logger.info("Geocoded '%s' → %s, %s (%.4f, %.4f)",
                            query, r.get("name"), r.get("country"), r["latitude"], r["longitude"])
                return r["latitude"], r["longitude"]
    except Exception as e:
        logger.warning("Open-Meteo geocode error: %s", e)
    return None


def _geocode_llm(port_name: str, country_name: str) -> tuple[float, float]:
    """Ask LLM for port coordinates. LLMs reliably know major port locations."""
    import json as _json
    from services.pdf_analyzer import _get_model

    prompt = (
        f"港口: {port_name}, {country_name}\n"
        f"请返回该港口的经纬度坐标，仅返回 JSON，格式: {{\"lat\": 数字, \"lon\": 数字}}"
    )
    try:
        model = _get_model()
        resp = model.generate_content([prompt])
        text = resp.text.strip().strip("`").removeprefix("json").strip()
        data = _json.loads(text)
        lat, lon = float(data["lat"]), float(data["lon"])
        logger.info("LLM geocoded '%s, %s' → (%.4f, %.4f)", port_name, country_name, lat, lon)
        return lat, lon
    except Exception as e:
        raise ValueError(f"Could not geocode: {port_name}, {country_name} — {e}")


def _fetch_weather(lat: float, lon: float, date_str: str) -> dict:
    """Fetch daily weather forecast from Open-Meteo.
    Returns empty dict if the date is beyond forecast range (~16 days).
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(FORECAST_URL, params={
                "latitude": lat,
                "longitude": lon,
                "daily": ",".join([
                    "temperature_2m_max", "temperature_2m_min",
                    "apparent_temperature_max", "apparent_temperature_min",
                    "precipitation_sum", "wind_speed_10m_max",
                    "wind_gusts_10m_max", "uv_index_max",
                    "weather_code",
                ]),
                "start_date": date_str,
                "end_date": date_str,
                "timezone": "auto",
            })
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning("Weather fetch failed (HTTP %d) — date %s may be beyond forecast range",
                        e.response.status_code, date_str)
        return {}

    daily = data.get("daily", {})
    if not daily.get("time"):
        return {}

    # WMO weather code → description
    wmo_code = daily.get("weather_code", [None])[0]
    condition = _wmo_to_text(wmo_code) if wmo_code is not None else ""

    return {
        "condition": condition,
        "temp_c": None,  # Open-Meteo doesn't provide avg, use min/max
        "max_temp_c": _safe_first(daily.get("temperature_2m_max")),
        "min_temp_c": _safe_first(daily.get("temperature_2m_min")),
        "max_wind_kph": _safe_first(daily.get("wind_speed_10m_max")),
        "max_wind_gusts_kph": _safe_first(daily.get("wind_gusts_10m_max")),
        "total_precip_mm": _safe_first(daily.get("precipitation_sum")),
        "avg_vis_km": None,  # Not available in Open-Meteo daily
        "avg_humidity": None,  # Not available in Open-Meteo daily
        "uv": _safe_first(daily.get("uv_index_max")),
    }


def _fetch_marine(lat: float, lon: float, date_str: str) -> dict:
    """Fetch hourly marine/wave data from Open-Meteo Marine API."""
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(MARINE_URL, params={
                "latitude": lat,
                "longitude": lon,
                "hourly": ",".join([
                    "wave_height", "wave_direction", "wave_period",
                    "swell_wave_height", "swell_wave_period",
                ]),
                "daily": "wave_height_max,wave_period_max",
                "start_date": date_str,
                "end_date": date_str,
                "timezone": "auto",
            })
            resp.raise_for_status()
            data = resp.json()

        daily = data.get("daily", {})
        hourly = data.get("hourly", {})

        # Build hourly wave data for chart
        hourly_waves = []
        times = hourly.get("time", [])
        heights = hourly.get("wave_height", [])
        for i, t in enumerate(times):
            h = heights[i] if i < len(heights) else None
            if h is not None:
                # Extract HH:MM from ISO datetime
                time_part = t.split("T")[1] if "T" in t else t
                hourly_waves.append({
                    "time": time_part[:5],
                    "wave_height_m": round(h, 2),
                })

        return {
            "max_wave_height_m": _safe_first(daily.get("wave_height_max")),
            "max_wave_period_s": _safe_first(daily.get("wave_period_max")),
            "hourly_waves": hourly_waves,
        }
    except Exception as e:
        logger.warning("Marine data fetch failed (non-fatal): %s", e)
        return {"max_wave_height_m": None, "max_wave_period_s": None, "hourly_waves": []}


def _generate_summary(location: str, date_str: str, weather: dict, marine: dict) -> str:
    """Generate AI delivery condition summary via Gemini."""
    from services.pdf_analyzer import _get_model

    weather_desc = (
        f"天气: {weather.get('condition', 'N/A')}, "
        f"温度: {weather.get('min_temp_c', '?')}~{weather.get('max_temp_c', '?')}°C, "
        f"最大风速: {weather.get('max_wind_kph', '?')}km/h, "
        f"阵风: {weather.get('max_wind_gusts_kph', '?')}km/h, "
        f"降水: {weather.get('total_precip_mm', '?')}mm, "
        f"UV指数: {weather.get('uv', '?')}"
    ) if weather else "无天气数据"

    marine_desc = ""
    if marine and marine.get("max_wave_height_m") is not None:
        marine_desc = (
            f"海洋: 最大浪高 {marine['max_wave_height_m']}m, "
            f"最大波周期 {marine.get('max_wave_period_s', '?')}s"
        )
    else:
        marine_desc = "无海洋数据"

    prompt = f"""你是邮轮供应链物流专家。根据以下港口环境数据，写一段简短的中文送货条件分析（3-5句话）。

港口: {location}
日期: {date_str}
{weather_desc}
{marine_desc}

要点：
1. 浪高和海况对码头靠泊和装卸作业的影响
2. 天气（风速、降水）对运输和作业安全的影响
3. 如有不利条件，给出注意事项
4. 语言简洁专业，适合物流人员阅读"""

    try:
        model = _get_model()
        response = model.generate_content([prompt])
        return response.text.strip()
    except Exception as e:
        logger.warning("AI summary generation failed: %s", e)
        return ""


def _safe_first(lst: list | None):
    """Safely get first element of a list."""
    if lst and len(lst) > 0:
        return lst[0]
    return None


# WMO Weather Code → Chinese description
_WMO_CODES = {
    0: "晴天",
    1: "大部晴朗", 2: "局部多云", 3: "多云",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "中毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    77: "雪粒",
    80: "小阵雨", 81: "中阵雨", 82: "强阵雨",
    85: "小阵雪", 86: "强阵雪",
    95: "雷暴", 96: "雷暴伴冰雹", 99: "强雷暴伴冰雹",
}


def _wmo_to_text(code: int) -> str:
    return _WMO_CODES.get(code, f"WMO {code}")
