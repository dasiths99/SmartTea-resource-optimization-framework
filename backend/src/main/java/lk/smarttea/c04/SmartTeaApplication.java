package lk.smarttea.c04;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.web.client.RestClient;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * SmartTea-LK Component 04 backend (public API).
 * React -> this service -> MongoDB, and this service -> Python ML service (Tier 1-3) over HTTP/JSON.
 */
@SpringBootApplication
@EnableScheduling
public class SmartTeaApplication {

    public static void main(String[] args) {
        SpringApplication.run(SmartTeaApplication.class, args);
    }

    @Bean
    RestClient restClient() {
        SimpleClientHttpRequestFactory f = new SimpleClientHttpRequestFactory();
        f.setConnectTimeout(10_000);
        f.setReadTimeout(120_000);   // the NSGA-II run takes a few seconds per block
        return RestClient.builder().requestFactory(f).build();
    }

    @Bean
    WebMvcConfigurer cors(@Value("${smarttea.cors-origins}") String[] origins) {
        return new WebMvcConfigurer() {
            @Override
            public void addCorsMappings(CorsRegistry registry) {
                registry.addMapping("/api/**").allowedOriginPatterns(origins).allowedMethods("GET", "POST", "PUT", "DELETE");
            }
        };
    }
}
