package lk.smarttea.c04.service;

import java.io.InputStream;
import java.util.List;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lk.smarttea.c04.model.Block;
import lk.smarttea.c04.model.Estate;
import lk.smarttea.c04.repo.BlockRepository;
import lk.smarttea.c04.repo.EstateRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.CommandLineRunner;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

/** On first start, loads the 5 estates and 50 blocks (seed JSON made by python -m src.api.export_seed). */
@Component
public class DataSeeder implements CommandLineRunner {
    private static final Logger log = LoggerFactory.getLogger(DataSeeder.class);
    private final EstateRepository estates;
    private final BlockRepository blocks;
    private final ObjectMapper json;

    public DataSeeder(EstateRepository estates, BlockRepository blocks, ObjectMapper json) {
        this.estates = estates;
        this.blocks = blocks;
        this.json = json;
    }

    @Override
    public void run(String... args) throws Exception {
        if (estates.count() == 0) {
            estates.saveAll(read("seed/estates.json", new TypeReference<List<Estate>>() { }));
        }
        if (blocks.count() == 0) {
            blocks.saveAll(read("seed/blocks.json", new TypeReference<List<Block>>() { }));
        }
        log.info("MongoDB ready: {} estates, {} blocks", estates.count(), blocks.count());
    }

    private <T> T read(String path, TypeReference<T> type) throws Exception {
        try (InputStream in = new ClassPathResource(path).getInputStream()) {
            return json.readValue(in, type);
        }
    }
}
