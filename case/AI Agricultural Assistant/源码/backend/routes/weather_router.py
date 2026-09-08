from fastapi import APIRouter, Query
from backend.services.weather_service import get_current_weather

router = APIRouter(prefix="/weather", tags=["Weather"])

@router.get("/current")
def current_weather(
    lat: float = Query(...),
    lon: float = Query(...)
):
    return get_current_weather(lat, lon)
