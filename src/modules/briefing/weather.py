"""Weather from Open-Meteo (https://open-meteo.com), free for non-commercial use without an
API key, licensed CC BY 4.0. DayOS shows "Weather data by Open-Meteo.com" wherever the data
appears, fetches at most once per refresh interval (or on Refresh), and caches the result.

Only values the service actually returned are shown: a missing value stays missing.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field

from src.services import http

ATTRIBUTION = "Weather data by Open-Meteo.com"
ATTRIBUTION_URL = "https://open-meteo.com/"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# WMO weather interpretation codes (as documented by Open-Meteo) -> (text, icon)
WMO = {
    0: ("Clear sky", "sun"), 1: ("Mainly clear", "sun"), 2: ("Partly cloudy", "cloud"), 3: ("Overcast", "cloud"),
    45: ("Fog", "cloud"), 48: ("Freezing fog", "cloud"),
    51: ("Light drizzle", "rain"), 53: ("Drizzle", "rain"), 55: ("Heavy drizzle", "rain"),
    56: ("Freezing drizzle", "rain"), 57: ("Heavy freezing drizzle", "rain"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Heavy freezing rain", "rain"),
    71: ("Light snow", "cloud"), 73: ("Snow", "cloud"), 75: ("Heavy snow", "cloud"), 77: ("Snow grains", "cloud"),
    80: ("Light showers", "rain"), 81: ("Showers", "rain"), 82: ("Violent showers", "rain"),
    85: ("Snow showers", "cloud"), 86: ("Heavy snow showers", "cloud"),
    95: ("Thunderstorm", "rain"), 96: ("Thunderstorm with hail", "rain"), 99: ("Thunderstorm with heavy hail", "rain"),
}


def describe(code) -> tuple[str, str]:
    try:
        return WMO.get(int(code), ("Unknown conditions", "cloud"))
    except (TypeError, ValueError):
        return "Unknown conditions", "cloud"


@dataclass
class Place:
    name: str
    lat: float
    lon: float
    region: str = ""
    country: str = ""
    timezone: str = ""

    @property
    def label(self) -> str:
        return ", ".join(x for x in (self.name, self.region, self.country) if x)

    def to_setting(self) -> dict:
        return {"name": self.name[:80], "region": self.region[:80], "country": self.country[:80],
                "lat": f"{self.lat:.4f}", "lon": f"{self.lon:.4f}", "timezone": self.timezone[:80]}

    @classmethod
    def from_setting(cls, data: dict | None) -> "Place | None":
        if not data:
            return None
        try:
            return cls(data["name"], float(data["lat"]), float(data["lon"]), data.get("region", ""),
                       data.get("country", ""), data.get("timezone", ""))
        except (KeyError, TypeError, ValueError):
            return None


def search_places(query: str) -> list[Place]:
    query = query.strip()
    if len(query) < 2:
        return []
    url = GEOCODE_URL + "?" + urllib.parse.urlencode({"name": query[:80], "count": 8, "language": "en",
                                                      "format": "json"})
    data = http.get_json(url)
    out = []
    for r in data.get("results") or []:
        try:
            out.append(Place(r["name"], float(r["latitude"]), float(r["longitude"]), r.get("admin1", ""),
                             r.get("country", ""), r.get("timezone", "")))
        except (KeyError, TypeError, ValueError):
            continue
    return out


@dataclass
class DayForecast:
    date: str
    code: int | None
    high: float | None
    low: float | None
    rain_chance: int | None


@dataclass
class WeatherReport:
    place: str
    observed: str  # local time of the observation, as reported
    units: str
    code: int | None = None
    temperature: float | None = None
    feels_like: float | None = None
    humidity: int | None = None
    rain_chance: int | None = None
    precipitation: float | None = None
    wind_speed: float | None = None
    wind_direction: int | None = None
    is_day: bool = True
    days: list[DayForecast] = field(default_factory=list)

    @property
    def temp_unit(self) -> str:
        return "°F" if self.units == "imperial" else "°C"

    @property
    def wind_unit(self) -> str:
        return "mph" if self.units == "imperial" else "km/h"

    def to_cache(self) -> dict:
        data = dict(self.__dict__)
        data["days"] = [d.__dict__ for d in self.days]
        return data

    @classmethod
    def from_cache(cls, data: dict) -> "WeatherReport":
        days = [DayForecast(**d) for d in data.get("days", [])]
        fields = {k: v for k, v in data.items() if k != "days" and k in cls.__dataclass_fields__}
        return cls(**fields, days=days)


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def compass(degrees: int | None) -> str:
    if degrees is None:
        return ""
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((degrees % 360) / 45 + 0.5) % 8]


def forecast_url(place: Place, units: str) -> str:
    params = {
        "latitude": f"{place.lat:.4f}", "longitude": f"{place.lon:.4f}",
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,"
                   "wind_speed_10m,wind_direction_10m,is_day",
        "hourly": "precipitation_probability",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto", "forecast_days": 4,
    }
    if units == "imperial":
        params.update(temperature_unit="fahrenheit", wind_speed_unit="mph", precipitation_unit="inch")
    return FORECAST_URL + "?" + urllib.parse.urlencode(params)


def parse_forecast(data: dict, place: Place, units: str) -> WeatherReport:
    current = data.get("current")
    if not isinstance(current, dict) or "time" not in current:
        raise http.HttpError("http", "The weather service didn't include current conditions.")
    report = WeatherReport(place.label, str(current["time"]), units,
                           code=_num(current.get("weather_code")), temperature=_num(current.get("temperature_2m")),
                           feels_like=_num(current.get("apparent_temperature")),
                           humidity=_num(current.get("relative_humidity_2m")),
                           precipitation=_num(current.get("precipitation")),
                           wind_speed=_num(current.get("wind_speed_10m")),
                           wind_direction=_num(current.get("wind_direction_10m")),
                           is_day=bool(current.get("is_day", 1)))
    hourly = data.get("hourly") or {}
    times, chances = hourly.get("time") or [], hourly.get("precipitation_probability") or []
    hour = str(current["time"])[:13]
    for t, chance in zip(times, chances):
        if str(t)[:13] == hour:
            report.rain_chance = _num(chance)
            break
    daily = data.get("daily") or {}
    for i, day in enumerate(daily.get("time") or []):
        def pick(key):
            values = daily.get(key) or []
            return _num(values[i]) if i < len(values) else None

        report.days.append(DayForecast(str(day), pick("weather_code"), pick("temperature_2m_max"),
                                       pick("temperature_2m_min"), pick("precipitation_probability_max")))
    return report


def fetch(place: Place, units: str = "metric") -> WeatherReport:
    """One request to Open-Meteo (call from a worker thread)."""
    return parse_forecast(http.get_json(forecast_url(place, units)), place, units)
