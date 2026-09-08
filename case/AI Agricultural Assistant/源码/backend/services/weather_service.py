import requests
from backend.core.config import settings

OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"

def get_current_weather(lat: float, lon: float) -> dict:
    if not settings.OPENWEATHER_API_KEY:
        return {"error": "Weather service not configured"}

    params = {
        "lat": lat,
        "lon": lon,
        "appid": settings.OPENWEATHER_API_KEY,
        "units": "metric",
    }

    try:
        res = requests.get(OPENWEATHER_URL, params=params, timeout=5)
        data = res.json()

        if res.status_code != 200:
            return {"error": "Unable to fetch weather"}

        weather_list = data.get("weather") or []
        if not weather_list or not isinstance(weather_list[0], dict):
            return {"error": "Invalid weather response"}

        condition_raw = str(weather_list[0].get("main", "clear")).lower()

        condition = (
            "rainy" if "rain" in condition_raw else
            "cloudy" if "cloud" in condition_raw else
            "sunny"
        )

        main = data.get("main") or {}
        wind = data.get("wind") or {}
        return {
            "location": data.get("name", "Your Location"),
            "temp": round(float(main.get("temp", 0))),
            "humidity": int(main.get("humidity", 0)),
            "wind": round(float(wind.get("speed", 0)) * 3.6),
            "condition": condition,
        }

    except Exception:
        return {"error": "Weather API unavailable"}
