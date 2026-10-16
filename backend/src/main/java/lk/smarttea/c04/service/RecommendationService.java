package lk.smarttea.c04.service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lk.smarttea.c04.model.Block;
import lk.smarttea.c04.model.Reading;
import lk.smarttea.c04.model.Recommendation;
import lk.smarttea.c04.repo.ActionDoneRepository;
import lk.smarttea.c04.repo.BlockRepository;
import lk.smarttea.c04.repo.ReadingRepository;
import lk.smarttea.c04.repo.RecommendationRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.query.Query;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

/**
 * Builds the ML request (block + its recent readings + fertilizer history + the estate forecast), calls the ML
 * service and stores the recommendation. Runs when a reading arrives, on demand, and every hour.
 */
@Service
public class RecommendationService {
    private static final Logger log = LoggerFactory.getLogger(RecommendationService.class);
    private static final TypeReference<List<Map<String, Object>>> LIST_OF_MAPS = new TypeReference<>() { };

    private final BlockRepository blocks;
    private final ActionDoneRepository actionsDone;
    private final ReadingRepository readings;
    private final RecommendationRepository recommendations;
    private final ForecastService forecasts;
    private final MlClient ml;
    private final MongoTemplate mongo;
    private final ObjectMapper json;

    public RecommendationService(BlockRepository blocks, ActionDoneRepository actionsDone, ReadingRepository readings,
                                 RecommendationRepository recommendations, ForecastService forecasts, MlClient ml,
                                 MongoTemplate mongo, ObjectMapper json) {
        this.blocks = blocks;
        this.actionsDone = actionsDone;
        this.readings = readings;
        this.recommendations = recommendations;
        this.forecasts = forecasts;
        this.ml = ml;
        this.mongo = mongo;
        this.json = json;
    }

    public Recommendation run(String blockId, String trigger, Double minAe) {
        return run(blockId, trigger, minAe, null);
    }

    /** whatIf (demo only): null = live forecast, "dry" or "wet" = labelled simulated weather (see the ML service). */
    public Recommendation run(String blockId, String trigger, Double minAe, String whatIf) {
        Block block = blocks.findById(blockId).orElseThrow(() -> new NotFoundException("unknown block " + blockId));
        List<Reading> recent = readings.findByBlockIdOrderByTimestampDesc(blockId, PageRequest.of(0, 60));
        if (recent.isEmpty()) {
            throw new NotFoundException("no readings for " + blockId + ": enter one first");
        }
        // fertilizer history = the distinct last_fertilizer entries reported with the readings
        Map<String, Reading.LastFertilizer> fert = new LinkedHashMap<>();
        for (Reading r : recent) {
            if (r.lastFertilizer() != null) {
                fert.putIfAbsent(r.lastFertilizer().date().toString(), r.lastFertilizer());
            }
        }
        Map<String, Object> req = new HashMap<>();
        req.put("block_id", blockId);
        req.put("readings", json.convertValue(recent, LIST_OF_MAPS));
        req.put("fertilizer_history", json.convertValue(new ArrayList<>(fert.values()), LIST_OF_MAPS));
        req.put("action_history", json.convertValue(actionsDone.findByBlockIdOrderByDateDescCreatedAtDesc(blockId), LIST_OF_MAPS));
        req.put("forecast", forecasts.get(block.estateId(), false).data());
        if (minAe != null) {
            req.put("min_ae", minAe);
        }
        if (whatIf != null) {
            req.put("what_if", whatIf);
        }
        Map<String, Object> result = ml.recommend(req);
        return recommendations.save(new Recommendation(null, blockId, LocalDateTime.now(), trigger,
                recent.get(0).id(), result));
    }

    /** Hourly: refresh the forecast and re-run every block that has readings (the forecast may have changed). */
    @Scheduled(cron = "${smarttea.hourly-cron}")
    public void hourly() {
        List<String> ids = mongo.findDistinct(new Query(), "blockId", Reading.class, String.class);
        log.info("hourly job: {} blocks with readings", ids.size());
        ids.stream().map(id -> blocks.findById(id).map(Block::estateId).orElse(null))
                .filter(Objects::nonNull).distinct().forEach(e -> {
                    try {
                        forecasts.get(e, true);
                    } catch (Exception ex) {
                        log.warn("hourly job: forecast for {} failed: {}", e, ex.getMessage());
                    }
                });
        for (String id : ids) {
            try {
                // a block showing a what-if demo keeps that weather until someone re-runs it on the live forecast,
                // so the hourly job does not silently replace a demonstration with a live result
                Object w = recommendations.findFirstByBlockIdOrderByCreatedAtDesc(id)
                        .map(r -> r.result().get("what_if")).orElse(null);
                String whatIf = w instanceof String s && !s.isBlank() ? s : null;
                run(id, whatIf == null ? "hourly" : "hourly (what-if: " + whatIf + ")", null, whatIf);
            } catch (Exception ex) {
                log.warn("hourly job: {} failed: {}", id, ex.getMessage());
            }
        }
    }
}
