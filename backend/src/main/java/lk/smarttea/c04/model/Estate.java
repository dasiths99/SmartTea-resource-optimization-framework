package lk.smarttea.c04.model;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

/** One of the 5 real tea-growing locations (the forecast is fetched for its lat/lon). */
@Document("estates")
public record Estate(@Id String estateId, String estateName, String region, String agroZone,
                     double latitude, double longitude) {
}
