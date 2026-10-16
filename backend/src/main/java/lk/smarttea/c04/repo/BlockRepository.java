package lk.smarttea.c04.repo;

import java.util.List;

import lk.smarttea.c04.model.Block;
import org.springframework.data.mongodb.repository.MongoRepository;

public interface BlockRepository extends MongoRepository<Block, String> {
    List<Block> findByEstateIdOrderByBlockId(String estateId);
}
