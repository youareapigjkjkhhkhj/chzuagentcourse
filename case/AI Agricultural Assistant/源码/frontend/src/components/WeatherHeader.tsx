import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  Sun,
  Cloud,
  CloudRain,
  Wind,
  Droplets,
  Thermometer,
  MapPin,
} from "lucide-react";
import { format } from "date-fns";

interface WeatherData {
  temp: number;
  condition: "sunny" | "cloudy" | "rainy";
  humidity: number;
  wind: number;
  location: string;
}

const API_BASE =
  import.meta.env.VITE_API_BASE_URL?.trim() || "http://localhost:8000";

const WeatherHeader = () => {
  const [currentTime, setCurrentTime] = useState(new Date());
  const [weather, setWeather] = useState<WeatherData | null>(null);

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 60000);

    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const { latitude, longitude } = pos.coords;
          const res = await fetch(
            `${API_BASE}/weather/current?lat=${latitude}&lon=${longitude}`
          );
          const data = await res.json();
          if (!data?.error) setWeather(data);
        } catch {
          console.warn("Weather fetch failed");
        }
      },
      () => console.warn("Location permission denied")
    );

    return () => clearInterval(timer);
  }, []);

  const getWeatherIcon = () => {
    switch (weather?.condition) {
      case "cloudy":
        return <Cloud className="w-5 h-5 text-muted-foreground" />;
      case "rainy":
        return <CloudRain className="w-5 h-5 text-farm-sky" />;
      default:
        return <Sun className="w-5 h-5 text-farm-sun" />;
    }
  };


  if (!weather) {
    return (
      <div className="w-full py-2 px-4">
        <div className="max-w-6xl mx-auto">
          <div className="h-10 w-80 rounded-2xl bg-muted/40 animate-pulse" />
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className="w-full py-2 px-4"
    >
      <div className="max-w-6xl mx-auto">
        <motion.div
          whileHover={{ scale: 1.02 }}
          transition={{ type: "spring", stiffness: 250 }}
          className="
            inline-flex flex-wrap items-center gap-4
            px-5 py-2.5
            rounded-2xl
            bg-card/80 backdrop-blur-md
            border border-border/50
            shadow-sm
          "
        >

          <div className="flex items-center gap-1.5 text-xs text-muted-foreground pr-4 border-r border-border/50">
            <MapPin className="w-3.5 h-3.5" />
            <span className="font-medium">{weather.location}</span>
          </div>

          <div className="text-xs text-muted-foreground pr-4 border-r border-border/50">
            {format(currentTime, "EEE, MMM d")}
          </div>

          <div className="flex items-center gap-2">
            {getWeatherIcon()}
            <div className="flex items-center gap-1">
              <Thermometer className="w-4 h-4 text-destructive/70" />
              <span className="text-sm font-semibold text-foreground">
                {weather.temp}°C
              </span>
            </div>
          </div>

          <div className="hidden sm:flex items-center gap-1.5">
            <Droplets className="w-4 h-4 text-farm-sky" />
            <span className="text-xs font-medium text-muted-foreground">
              {weather.humidity}%
            </span>
          </div>

          <div className="hidden md:flex items-center gap-1.5">
            <Wind className="w-4 h-4 text-muted-foreground" />
            <span className="text-xs font-medium text-muted-foreground">
              {weather.wind} km/h
            </span>
          </div>
        </motion.div>
      </div>
    </motion.div>
  );
};

export default WeatherHeader;
