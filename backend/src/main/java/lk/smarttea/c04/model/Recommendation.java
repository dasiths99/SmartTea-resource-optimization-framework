package lk.smarttea.c04.model;

import java.time.LocalDateTime;
import java.util.Map;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;

/**
 * A recommendation returned by the ML service, stored as is (result), with when and why it was made.
 * trigger: "new_reading" | "hourly" | "manual".
 */
@Document("recommendations")
public record Recommendation(@Id String id, @Indexed String blockId, LocalDateTime createdAt, String trigger,
                             String readingId, Map<String, Object> result) {
}
