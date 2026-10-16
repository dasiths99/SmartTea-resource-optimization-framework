package lk.smarttea.c04.repo;

import java.util.List;

import lk.smarttea.c04.model.ActionDone;
import org.springframework.data.mongodb.repository.MongoRepository;

public interface ActionDoneRepository extends MongoRepository<ActionDone, String> {
    List<ActionDone> findByBlockIdOrderByDateDescCreatedAtDesc(String blockId);

    void deleteByBlockId(String blockId);
}
