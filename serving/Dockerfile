# Multi-stage build: the wrapper (mvnw) downloads its pinned Maven at build
# time, so only a JDK is assumed here — same contract as running it on a
# laptop. Tests are NOT run in this build (they boot Dev Services containers,
# which would mean Docker-in-Docker); `mvn verify` already gates every PR in
# CI before an image is ever built from the merged commit.
FROM eclipse-temurin:21-jdk AS build
WORKDIR /build
COPY mvnw pom.xml ./
COPY .mvn .mvn
COPY src src
RUN ./mvnw -B package -DskipTests

# Quarkus's default "fast-jar" package layout: quarkus-run.jar plus three
# directories it expects to find beside it (app/lib/quarkus-app split so
# unchanged dependency layers can be cached, though this single-stage COPY
# doesn't yet exploit that — see BUILD_LOG if that becomes worth doing).
FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /build/target/quarkus-app/lib/ ./lib/
COPY --from=build /build/target/quarkus-app/*.jar ./
COPY --from=build /build/target/quarkus-app/app/ ./app/
COPY --from=build /build/target/quarkus-app/quarkus/ ./quarkus/

EXPOSE 8080
ENTRYPOINT ["java", "-jar", "quarkus-run.jar"]
