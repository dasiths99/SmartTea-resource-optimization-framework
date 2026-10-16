package lk.smarttea.c04.web;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Demo scenarios for the viva. The dashboard clears the scenario block (DELETE /api/blocks/{id}/data), fills the
 * Enter-reading form with the scenario's values, and the user presses "Save reading and get recommendation",
 * which is the normal POST /api/readings. whatIf: null = live Open-Meteo forecast; "dry" = the coming days set dry;
 * "wet" = the past week set wet and cloudy. What-if results are labelled as such in the dashboard.
 *
 * Every scenario starts from the same healthy baseline: P 20 ppm, K 120 ppm, soil 22 °C, 42,000 lux, 5 h sun
 * (the dashboard adds these; a scenario changes only what it needs).
 */
@RestController
@RequestMapping("/api/demo")
public class DemoController {

    public record Scenario(String key, String title, String shows, String blockId, double soilMoisturePct,
                           double soilPh, @JsonProperty("soil_n_ppm") double soilNPpm, int lastFertilizerDaysAgo,
                           String whatIf, String expected) {
    }

    // healthy baseline: moisture 33 %, pH 5.0, N 25 ppm
    private static final List<Scenario> SCENARIOS = List.of(
            new Scenario("healthy", "1. Healthy block", "Normal readings: the AI finds nothing worth doing",
                    "E03-B01", 33, 5.0, 25, 100, null, "No action (each reason explained)"),
            new Scenario("low-n-live", "2. Low nitrogen, live weather", "Fertilizer is needed; Tier 3 checks today's real forecast",
                    "E05-B09", 33, 5.0, 5, 100, null, "Delay fertilizer if rain is forecast, else Apply + time window"),
            new Scenario("low-n-dry", "3. Low nitrogen, dry days ahead", "Same block and reading, with a dry forecast",
                    "E05-B09", 33, 5.0, 5, 100, "dry", "Apply fertilizer + amount + time window"),
            new Scenario("acidic", "4. Acidic soil", "pH rule: dolomite is decided by an agronomic rule, not the AI",
                    "E01-B05", 33, 4.2, 25, 100, null, "Apply dolomite + time window"),
            new Scenario("combo", "5. Low nitrogen + acidic soil", "Several actions in one recommendation",
                    "E05-B09", 33, 4.2, 5, 100, "dry", "Apply fertilizer + Apply dolomite, each with a window"),
            new Scenario("recent-fert", "6. Fertilized 10 days ago", "Hard rule: at least 45 days between applications",
                    "E05-B09", 33, 5.0, 5, 10, null, "No action, reason: last fertilizer 10 days ago (min 45)"),
            new Scenario("dry-soil-live", "7. Dry soil, live weather", "Irrigation rule with today's real forecast",
                    "E05-B09", 24, 5.0, 25, 30, null, "Skip irrigation if rain is coming, else Irrigate"),
            new Scenario("dry-soil-dry", "8. Dry soil, dry days ahead", "Irrigation when no rain is coming",
                    "E05-B09", 24, 5.0, 25, 30, "dry", "Irrigate + time window"),
            new Scenario("blight", "9. Wet, cloudy week (blight weather)", "Fungicide rule from the blister-blight risk",
                    "E01-B05", 33, 5.0, 25, 30, "wet", "Spray fungicide + time window"));

    @GetMapping("/scenarios")
    public List<Scenario> scenarios() {
        return SCENARIOS;
    }
}
