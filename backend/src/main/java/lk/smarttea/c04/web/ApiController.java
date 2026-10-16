package lk.smarttea.c04.web;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import java.time.LocalDate;
import java.time.LocalDateTime;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import lk.smarttea.c04.model.ActionDone;
import lk.smarttea.c04.model.Block;
import lk.smarttea.c04.model.Estate;
import lk.smarttea.c04.model.ForecastSnapshot;
import lk.smarttea.c04.model.Reading;
import lk.smarttea.c04.model.Recommendation;
import lk.smarttea.c04.repo.ActionDoneRepository;
import lk.smarttea.c04.repo.BlockRepository;
import lk.smarttea.c04.repo.EstateRepository;
import lk.smarttea.c04.repo.ReadingRepository;
import lk.smarttea.c04.repo.RecommendationRepository;
import lk.smarttea.c04.service.ForecastService;
import lk.smarttea.c04.service.MlClient;
import lk.smarttea.c04.service.NotFoundException;
import lk.smarttea.c04.service.RecommendationService;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/** Public API used by the React dashboard (and, for POST /api/readings, by the future IoT device). */
@RestController
@RequestMapping("/api")
public class ApiController {
    private final EstateRepository estates;
    private final BlockRepository blocks;
    private final ActionDoneRepository actionsDone;
    private final ReadingRepository readings;
    private final RecommendationRepository recommendations;
    private final RecommendationService recommender;
    private final ForecastService forecasts;
    private final MlClient ml;

    public ApiController(EstateRepository estates, BlockRepository blocks, ActionDoneRepository actionsDone,
                         ReadingRepository readings,
                         RecommendationRepository recommendations, RecommendationService recommender,
                         ForecastService forecasts, MlClient ml) {
        this.estates = estates;
        this.blocks = blocks;
        this.actionsDone = actionsDone;
        this.readings = readings;
        this.recommendations = recommendations;
        this.recommender = recommender;
        this.forecasts = forecasts;
        this.ml = ml;
    }

    /** System status for the dashboard header: database counts and the ML service (models + scores). */
    @GetMapping("/status")
    public Map<String, Object> status() {
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("database", Map.of("estates", estates.count(), "blocks", blocks.count(),
                "readings", readings.count(), "recommendations", recommendations.count()));
        try {
            s.put("ml_service", ml.health());
        } catch (Exception e) {
            s.put("ml_service", Map.of("status", "down", "error", e.getMessage()));
        }
        return s;
    }

    @GetMapping("/estates")
    public List<Estate> estates() {
        return estates.findAll(Sort.by("estateId"));
    }

    @GetMapping("/blocks")
    public List<Block> blocks(@RequestParam(required = false) String estateId) {
        return estateId == null ? blocks.findAll(Sort.by("blockId")) : blocks.findByEstateIdOrderByBlockId(estateId);
    }

    @GetMapping("/blocks/{id}")
    public Block block(@PathVariable String id) {
        return blocks.findById(id).orElseThrow(() -> new NotFoundException("unknown block " + id));
    }

    /**
     * IoT / manual entry. Stores the reading, then re-runs the recommendation for its block.
     * If the ML service fails, the reading is still saved and the error is returned.
     */
    @PostMapping("/readings")
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> addReading(@Valid @RequestBody Reading reading,
                                          @RequestParam(required = false) String whatIf) {
        if (!blocks.existsById(reading.blockId())) {
            throw new NotFoundException("unknown block " + reading.blockId());
        }
        Reading saved = readings.save(reading.stamped());
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("reading", saved);
        // whatIf (demo only) = "dry" / "wet": labelled simulated weather. The reading JSON itself is unchanged.
        boolean live = whatIf == null || whatIf.isBlank() || whatIf.equals("live");
        try {
            out.put("recommendation", recommender.run(saved.blockId(),
                    live ? "new_reading" : "new_reading (what-if: " + whatIf + ")", null, live ? null : whatIf));
        } catch (Exception e) {
            out.put("recommendation_error", e.getMessage());
        }
        return out;
    }

    /** Demo / testing: remove a block's readings and recommendations so a scenario starts clean. */
    @DeleteMapping("/blocks/{id}/data")
    public Map<String, Object> clearBlock(@PathVariable String id) {
        if (!blocks.existsById(id)) {
            throw new NotFoundException("unknown block " + id);
        }
        readings.deleteByBlockId(id);
        recommendations.deleteByBlockId(id);
        actionsDone.deleteByBlockId(id);
        return Map.of("block_id", id, "cleared", true);
    }

    /** What the user marked as done for a block (latest first). */
    @GetMapping("/blocks/{id}/actions-done")
    public List<ActionDone> actionsDone(@PathVariable String id) {
        return actionsDone.findByBlockIdOrderByDateDescCreatedAtDesc(id);
    }

    /** "Mark as done": type = fertilizer | irrigation | dolomite | fungicide; date defaults to today. */
    public record DoneRequest(@NotBlank String type, LocalDate date, Double amount, String unit, String product) {
    }

    @PostMapping("/blocks/{id}/actions-done")
    @ResponseStatus(HttpStatus.CREATED)
    public ActionDone markDone(@PathVariable String id, @Valid @RequestBody DoneRequest r) {
        if (!blocks.existsById(id)) {
            throw new NotFoundException("unknown block " + id);
        }
        if (!List.of("fertilizer", "irrigation", "dolomite", "fungicide").contains(r.type())) {
            throw new IllegalArgumentException("type must be fertilizer, irrigation, dolomite or fungicide");
        }
        return actionsDone.save(new ActionDone(null, id, r.type(), r.date() == null ? LocalDate.now() : r.date(),
                r.amount(), r.unit(), r.product(), LocalDateTime.now()));
    }

    /** Undo a "Mark as done" (a mistaken click). */
    @DeleteMapping("/actions-done/{actionId}")
    public Map<String, Object> undoDone(@PathVariable String actionId) {
        if (!actionsDone.existsById(actionId)) {
            throw new NotFoundException("unknown action " + actionId);
        }
        actionsDone.deleteById(actionId);
        return Map.of("id", actionId, "removed", true);
    }

    @GetMapping("/readings")
    public List<Reading> readings(@RequestParam String blockId, @RequestParam(defaultValue = "20") int limit) {
        return readings.findByBlockIdOrderByTimestampDesc(blockId, PageRequest.of(0, limit));
    }

    @GetMapping("/blocks/{id}/recommendation")
    public Recommendation latest(@PathVariable String id) {
        return recommendations.findFirstByBlockIdOrderByCreatedAtDesc(id)
                .orElseThrow(() -> new NotFoundException("no recommendation for " + id + " yet"));
    }

    /**
     * Re-run now (e.g. after the forecast changed); min_ae optionally overrides the pick-rule threshold;
     * whatIf = "dry" or "wet" runs on a labelled simulated weather instead of the live forecast.
     */
    @PostMapping("/blocks/{id}/recommendation")
    public Recommendation refresh(@PathVariable String id, @RequestParam(required = false) Double minAe,
                                  @RequestParam(required = false) String whatIf) {
        boolean live = whatIf == null || whatIf.isBlank() || whatIf.equals("live");
        return recommender.run(id, live ? "manual" : "manual (what-if: " + whatIf + ")", minAe, live ? null : whatIf);
    }

    @GetMapping("/blocks/{id}/recommendations")
    public List<Recommendation> history(@PathVariable String id, @RequestParam(defaultValue = "20") int limit) {
        return recommendations.findByBlockIdOrderByCreatedAtDesc(id, PageRequest.of(0, limit));
    }

    @GetMapping("/forecast/{estateId}")
    public ForecastSnapshot forecast(@PathVariable String estateId, @RequestParam(defaultValue = "false") boolean refresh) {
        return forecasts.get(estateId, refresh);
    }
}
