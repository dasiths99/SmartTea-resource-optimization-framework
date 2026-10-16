package lk.smarttea.c04.model;

import java.time.LocalDateTime;
import java.util.Map;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

/** The latest Open-Meteo forecast for an estate (raw JSON), refreshed at most once an hour. */
@Document("forecasts")
public record ForecastSnapshot(@Id String estateId, LocalDateTime fetchedAt, Map<String, Object> data) {
}
