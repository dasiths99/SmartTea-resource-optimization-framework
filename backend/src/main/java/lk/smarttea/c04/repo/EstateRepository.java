package lk.smarttea.c04.repo;

import lk.smarttea.c04.model.Estate;
import org.springframework.data.mongodb.repository.MongoRepository;

public interface EstateRepository extends MongoRepository<Estate, String> {
}
