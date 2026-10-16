package lk.smarttea.c04.repo;

import lk.smarttea.c04.model.ForecastSnapshot;
import org.springframework.data.mongodb.repository.MongoRepository;

public interface ForecastRepository extends MongoRepository<ForecastSnapshot, String> {
}
