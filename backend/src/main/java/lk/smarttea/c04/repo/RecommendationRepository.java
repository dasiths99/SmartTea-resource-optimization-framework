package lk.smarttea.c04.repo;

import java.util.List;
import java.util.Optional;

import lk.smarttea.c04.model.Recommendation;
import org.springframework.data.domain.Pageable;
import org.springframework.data.mongodb.repository.MongoRepository;

public interface RecommendationRepository extends MongoRepository<Recommendation, String> {
    Optional<Recommendation> findFirstByBlockIdOrderByCreatedAtDesc(String blockId);

    List<Recommendation> findByBlockIdOrderByCreatedAtDesc(String blockId, Pageable page);

    void deleteByBlockId(String blockId);
}
