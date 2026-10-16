package lk.smarttea.c04.model;

import java.time.LocalDate;
import java.time.LocalDateTime;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;

/**
 * One sensor reading for a block. This is EXACTLY the JSON the future IoT device will send to POST /api/readings
 * (snake_case), so adding real sensors later only changes where the data comes from. Keep it stable.
 *
 * <pre>
 * {"device_id":"manual-entry","block_id":"E03-B07","timestamp":"2026-10-15T08:00:00",
 *  "soil_moisture_pct":34.2,"soil_ph":5.1,"soil_n_ppm":18.5,"soil_p_ppm":20.1,"soil_k_ppm":120,
 *  "soil_temp_c":21.3,"light_lux":42000,"sunshine_hours":5.2,
 *  "last_fertilizer":{"product_code":"NPK_BAL","amount_kg_per_ha":240,"date":"2026-08-20"}}
 * </pre>
 */
@Document("readings")
public record Reading(
        @Id String id,
        String deviceId,
        @NotBlank @Indexed String blockId,
        LocalDateTime timestamp,
        @NotNull @DecimalMin("0") @DecimalMax("100") Double soilMoisturePct,
        @NotNull @DecimalMin("3") @DecimalMax("9") Double soilPh,
        @NotNull @DecimalMin("0") @JsonProperty("soil_n_ppm") Double soilNPpm,
        @NotNull @DecimalMin("0") @JsonProperty("soil_p_ppm") Double soilPPpm,
        @NotNull @DecimalMin("0") @JsonProperty("soil_k_ppm") Double soilKPpm,
        @NotNull @DecimalMin("-5") @DecimalMax("50") Double soilTempC,
        @DecimalMin("0") Double lightLux,
        @DecimalMin("0") @DecimalMax("14") Double sunshineHours,
        @Valid LastFertilizer lastFertilizer,
        LocalDateTime receivedAt) {

    /** The last fertilizer applied to the block (type, amount, date). */
    public record LastFertilizer(@NotBlank String productCode,
                                 @NotNull @DecimalMin("0") Double amountKgPerHa,
                                 @NotNull LocalDate date) {
    }

    /** Fills server-side fields: id, a missing timestamp (now), receivedAt, a missing device id. */
    public Reading stamped() {
        LocalDateTime now = LocalDateTime.now();
        return new Reading(null, deviceId == null ? "manual-entry" : deviceId, blockId,
                timestamp == null ? now : timestamp, soilMoisturePct, soilPh, soilNPpm, soilPPpm, soilKPpm,
                soilTempC, lightLux, sunshineHours, lastFertilizer, now);
    }
}
