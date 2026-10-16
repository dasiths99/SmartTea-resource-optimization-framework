package lk.smarttea.c04.model;

import java.time.LocalDate;
import java.time.LocalDateTime;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;

/**
 * An action the user marked as done ("Mark as done" on a recommendation): fertilizer, irrigation, dolomite or
 * fungicide. The ML service uses the log to enforce the gaps between repeats (dolomite 730 days, sprays 7 days,
 * irrigation 3 days) and to count a fertilizer toward the 45-day rule. The IoT reading format is unchanged.
 */
@Document("actions_done")
public record ActionDone(@Id String id, @Indexed String blockId, String type, LocalDate date, Double amount,
                         String unit, String product, LocalDateTime createdAt) {
}
