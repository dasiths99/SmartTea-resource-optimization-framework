package lk.smarttea.c04.service;

import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/** HTTP client for the internal Python ML service (FastAPI). */
@Component
public class MlClient {
    private final RestClient http;
    private final String base;

    public MlClient(RestClient http, @Value("${smarttea.ml-url}") String base) {
        this.http = http;
        this.base = base;
    }

    public Map<String, Object> recommend(Map<String, Object> request) {
        return http.post().uri(base + "/ml/recommend").contentType(MediaType.APPLICATION_JSON).body(request)
                .retrieve().body(new ParameterizedTypeReference<>() { });
    }

    public Map<String, Object> health() {
        return http.get().uri(base + "/ml/health").retrieve().body(new ParameterizedTypeReference<>() { });
    }
}
