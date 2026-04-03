# Related Work Notes

## MQTT QoS Semantics

MQTT 3.1.1 defines three delivery levels, with QoS 1 providing at-least-once delivery rather than exactly-once delivery [@mqtt311]. That makes duplicate handling a downstream concern for gateways that rely on message identifiers or replay metadata. In Agrasandhani, this is why exact duplicate suppression is treated as a gateway policy rather than as a guarantee delegated to the broker.

## Pub/Sub Positioning

Kafka's original design centers on high-throughput log processing, durable retention, replayability, and partitioned consumer groups [@kreps2011kafka]. That is a different operating point from the lightweight sensor-ingest path in this repo, where the concern is interactive visualization over a local MQTT feed rather than durable distributed log storage.

The Kafka-versus-RabbitMQ comparison by Dobbelaere and Esmaili is useful as framing because it emphasizes that pub/sub systems are not interchangeable even when they share the label [@dobbelaere2017kafka]. For the final report, that is enough context: MQTT is the lightweight edge-facing protocol in this project, while Kafka and RabbitMQ provide the broader pub/sub systems backdrop for discussing throughput, retention, routing flexibility, and operational tradeoffs.

## Senselet-Style Inspiration

SENSELET++ is relevant less as a direct implementation template and more as a project-framing reference [@tian2021senseletpp]. It pairs IoT sensing infrastructure with analysis and visualization for a scientific-lab environment, which is close to the "sensor pipeline plus operator-facing display" framing used here. Agrasandhani is much smaller in scope, but the comparison helps justify why a reproducible data path and a live demo both matter in the final deliverable set.

## Dataset Notes

The Intel Berkeley Lab page documents the 54-sensor deployment, the 31-second collection cadence, and the published schema used by the preprocessor in this repo [@intelLabData]. The AoT validation data in this project is grounded in the Illinois Data Bank archive for reproducible urban sensing analytics [@aotCyberGIS].
