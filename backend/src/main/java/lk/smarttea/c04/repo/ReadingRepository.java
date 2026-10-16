package lk.smarttea.c04.repo;

import java.util.List;

import lk.smarttea.c04.model.Reading;
import org.springframework.data.domain.Pageable;
import org.springframework.data.mongodb.repository.MongoRepository;

public interface ReadingRepository extends MongoRepository<Reading, String> {
    List<Reading> findByBlockIdOrderByTimestampDesc(String blockId, Pageable page);

    void deleteByBlockId(String blockId);
}
