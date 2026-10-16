package lk.smarttea.c04.service;

import java.time.LocalDateTime;
import java.util.Map;

import lk.smarttea.c04.model.Estate;
import lk.smarttea.c04.model.ForecastSnapshot;
import lk.smarttea.c04.repo.EstateRepository;
import lk.smarttea.c04.repo.ForecastRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * Live weather from the Open-Meteo forecast API (free, no key): hourly rain, rain probability, temperature,
 * humidity and wind for the next 5 days, plus the last 31 days (daily) that the models need as recent weather.
 * Cached in MongoDB for smarttea.forecast-cache-minutes.
 */
@Service
public class ForecastService {
    private static final Logger log = LoggerFactory.getLogger(ForecastService.class);
    private static final String HOURLY = "precipitation,precipitation_probability,temperature_2m,relative_humidity_2m,wind_speed_10m";
    private static final String DAILY = "precipitation_sum,temperature_2m_mean,relative_humidity_2m_mean,"
            + "et0_fao_evapotranspiration,sunshine_duration,shortwave_radiation_sum";

    private final RestClient http;
    private final EstateRepository estates;
    private final ForecastRepository forecasts;
    private final String url;
    private final long cacheMinutes;

    public ForecastService(RestClient http, EstateRepository estates, ForecastRepository forecasts,
                           @Value("${smarttea.forecast-url}") String url,
                           @Value("${smarttea.forecast-cache-minutes}") long cacheMinutes) {
        this.http = http;
        this.estates = estates;
        this.forecasts = forecasts;
        this.url = url;
        this.cacheMinutes = cacheMinutes;
    }

    public ForecastSnapshot get(String estateId, boolean refresh) {
        Estate e = estates.findById(estateId).orElseThrow(() -> new NotFoundException("unknown estate " + estateId));
        ForecastSnapshot cached = forecasts.findById(estateId).orElse(null);
        if (!refresh && cached != null && cached.fetchedAt().isAfter(LocalDateTime.now().minusMinutes(cacheMinutes))) {
            return cached;
        }
        String uri = UriComponentsBuilder.fromHttpUrl(url)
                .queryParam("latitude", e.latitude()).queryParam("longitude", e.longitude())
                .queryParam("hourly", HOURLY).queryParam("daily", DAILY)
                .queryParam("past_days", 31).queryParam("forecast_days", 5)
                .queryParam("wind_speed_unit", "ms").queryParam("timezone", "Asia/Colombo")
                .build().toUriString();
        try {
            Map<String, Object> data = http.get().uri(uri).retrieve().body(new ParameterizedTypeReference<>() { });
            return forecasts.save(new ForecastSnapshot(estateId, LocalDateTime.now(), data));
        } catch (RuntimeException ex) {
            if (cached != null) {   // Open-Meteo busy or offline: keep using the last forecast
                log.warn("Open-Meteo failed for {} ({}); using the forecast from {}", estateId, ex.getMessage(), cached.fetchedAt());
                return cached;
            }
            throw ex;
        }
    }
}
