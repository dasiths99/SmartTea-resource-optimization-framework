package lk.smarttea.c04.model;

import java.util.Map;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

/**
 * Static features of a tea block (from 01_block_master.csv).
 * typicalReadings: 2025 monthly mean sensor values ("1".."12"), used only to pre-fill the demo form.
 */
@Document("blocks")
public record Block(@Id String blockId, String estateId, String estateName, String region, String agroZone,
                    double areaHa, double elevationM, double slopePct, String soilType,
                    double fieldCapacityPct, double wiltingPointPct, String cultivar, int bushAgeYrs,
                    double shadeTreeCoverPct, int pruningCycleYrs, boolean irrigationAvailable,
                    double latitude, double longitude, Map<String, Map<String, Double>> typicalReadings) {
}
