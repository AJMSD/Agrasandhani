# context.md

## Agrasandhani — Project Context

**Project:** Agrasandhani  
**Course:** CS 537 — Multimedia Systems  
**Project Type:** Solo research-oriented systems project  
**Student:** Aman Jain

---

## 1. What this project is trying to do

Agrasandhani is a research project about how to make **IoT sensor visualization more stable and interpretable under imperfect network conditions**.

The core idea is simple:

- IoT sensors often produce frequent, bursty streams of updates.
- A dashboard that naively forwards and displays every update can become unstable, bandwidth-heavy, and hard to interpret.
- Network issues such as **loss, delay, jitter, bandwidth caps, and outages** make this worse.
- A **smart gateway** placed between the sensor stream and the dashboard can summarize, stabilize, and manage what gets shown to the user.

So the project is not just about building a dashboard or brokered sensor pipeline. It is about studying the **trade-offs** introduced by gateway policies such as batching, compaction, and state retention, and asking:

> How should a gateway transform sensor streams so that a dashboard remains useful and stable when the network is imperfect?

That framing comes directly from the proposal’s emphasis on end-to-end dashboard semantics, MQTT reliability behavior, and user-visible stability under degraded last-hop conditions. :contentReference[oaicite:0]{index=0}

---

## 2. The motivating problem

The project starts from a practical systems problem:

### Naive forwarding is fragile
If every sensor message is forwarded end-to-end without any shaping or summarization:

- bandwidth usage can grow quickly,
- dashboards can flicker or update too frequently,
- retransmissions or duplicates can distort state,
- temporary network degradation can cause visible instability,
- users may see stale, delayed, or apparently erratic information.

In human-facing monitoring systems, what matters is not only whether a message eventually arrives, but whether the **displayed state remains timely, stable, and understandable**.

The proposal explicitly frames this as a gap in many existing reduction techniques: they often optimize traffic volume, but they do not always make **dashboard-oriented semantics** first-class, especially under MQTT reliability modes and degraded network paths. :contentReference[oaicite:1]{index=1}

---

## 3. The core concept of Agrasandhani

Agrasandhani is a **smart gateway for sensor visualization**.

Its role is to sit between incoming sensor traffic and the dashboard, and to decide **how** updates should be represented to the visualization layer.

Conceptually, it does four things:

1. **Cleans the stream**
   - handles duplicate or redundant updates

2. **Summarizes the stream**
   - groups or compacts rapid updates instead of exposing every raw message

3. **Responds to network conditions**
   - changes its behavior when the downstream path degrades

4. **Maintains dashboard continuity**
   - preserves last-known values so the UI remains informative during disruption

This makes the gateway more than a relay. It becomes the system component that defines the relationship between:
- raw sensor traffic,
- network reliability,
- and user-visible dashboard behavior.

---

## 4. Original proposal direction

The proposal defines Agrasandhani as an **MQTT-based smart gateway** that studies how sensor streams should be cleaned and summarized before delivery to a dashboard. The proposed design includes:

- hybrid time/size batching,
- message-ID deduplication,
- latest-per-sensor compaction within batches,
- adaptive publish-rate control,
- and last-known-good dashboard semantics with freshness/age indicators and TTL. :contentReference[oaicite:2]{index=2}

The proposal also defines an evaluation structure based on:
- multiple gateway variants,
- MQTT QoS modes,
- deterministic impairment scenarios,
- and metrics such as latency, bandwidth usage, message rate, data loss, freshness, and update jitter. :contentReference[oaicite:3]{index=3}

In other words, the proposal is already clearly a **systems evaluation project**, not just an application build.

---

## 5. Changes after professor feedback

After discussion with the professor, the project direction became more focused and more consistent with a clean systems architecture.

### 5.1 MQTT should remain between sensors and the smart gateway
The notes make it clear that MQTT should stay on the **sensor side** of the architecture:

- sensors publish through an MQTT broker,
- the smart gateway subscribes and processes those updates.

This preserves MQTT as the ingest protocol and keeps the project grounded in IoT/pub-sub semantics.

### 5.2 The dashboard path should use WebSockets, not MQTT
The professor suggested that the path from the smart gateway to the dashboard should use **WebSockets instead of MQTT**.

That changes the project in an important way:
- the dashboard no longer directly participates in the MQTT stream,
- the gateway becomes the entity that transforms and presents data to the visualization layer.

This shift makes the dashboard more clearly a **consumer of processed, visualization-oriented state**, not a raw MQTT subscriber.

### 5.3 The smart gateway and backend should be merged
The notes also indicate that the “smart gateway” and the “backend” should effectively be treated as one combined component.

This means the project should be understood as a unified system where the gateway:
- ingests MQTT sensor traffic,
- performs stream shaping / analysis,
- and serves processed output to the dashboard.

### 5.4 The project should use realistic sensor sources
The meeting notes suggest using:
- **Array of Things** data,
- and another environmental/temperature-oriented dataset.

This pushes the project away from being purely synthetic and toward a more credible replay-based study using realistic sensor traces.

### 5.5 The paper should include broader pub/sub context
The professor explicitly suggested reading and discussing:
- **Kafka**
- **RabbitMQ**
- and architectures like **Senselet++**

This does **not** mean implementing those systems. It means the project should position MQTT and Agrasandhani within a broader message-system and sensor-platform context.

### 5.6 Emulation should be explicit
The meeting notes suggest placing some kind of process/thread/emulation layer in the data path to:
- delay messages,
- drop messages,
- and induce behavior.

This reinforces that the project should not merely mention impairment abstractly, but should treat it as a deliberate and controlled part of the evaluation methodology.

---

## 6. The final conceptual architecture

At the level of project understanding, the final architecture is:

**Sensor source / dataset replay → MQTT broker → smart gateway → WebSocket-based dashboard**

That architecture captures the professor’s changes and the proposal’s core goals:

- MQTT is still central to the ingest path,
- the gateway is the research object,
- and the dashboard receives processed data in a form suited for real-time visualization.

The gateway is therefore the bridge between:
- **raw pub/sub telemetry**
and
- **user-facing visual state**

For the evaluated impairment runs, degradations are injected primarily on the **gateway-to-dashboard last hop** through the impairment proxy (with optional host-level `tc netem` shaping in the same last-hop context). The bandwidth and frame-count evidence in the report comes from proxy downstream metrics, not from impairment injected on the broker-to-gateway ingest link.

---

## 7. What the project is evaluating

The project is ultimately about evaluating **how gateway policies affect user-visible behavior** under normal and degraded conditions.

### The main comparison structure
The proposal defines an ablation ladder of variants:
- naive forwarding,
- batching,
- batching plus compaction/deduplication,
- adaptive publish-rate control,
- and last-known-good dashboard semantics. :contentReference[oaicite:4]{index=4}

This is important because the project is not only asking:
> “Does the full system work?”

It is also asking:
> “Which mechanism actually contributes to which outcome?”

### The main dimensions of evaluation
The project studies trade-offs among:
- communication volume,
- latency,
- dashboard update behavior,
- freshness/staleness,
- and resilience under degraded conditions.

### The intended degradation scenarios
The proposal and meeting notes together make clear that the system should be studied under conditions such as:
- packet loss,
- delay,
- jitter,
- bandwidth caps,
- short outages.

These are not edge cases in the project. They are central to what the project is about.

---

## 8. The user-facing perspective of the project

One of the most important parts of Agrasandhani is that it takes the dashboard seriously as a **human-facing system**.

The proposal emphasizes that many existing approaches optimize traffic reduction or protocol behavior but do not fully account for:
- how stable the display feels,
- how old the shown value becomes,
- how often the view changes,
- and what the user actually experiences when the last hop degrades. :contentReference[oaicite:5]{index=5}

That means the project should always be interpreted through two lenses at once:

### Systems lens
- pub/sub reliability,
- batching,
- stream shaping,
- controlled impairment,
- protocol behavior.

### Human-visible lens
- stable display,
- freshness,
- continuity during outages,
- reduced flicker / overload,
- better interpretability of the shown state.

This dual framing is a major part of what makes the project appropriate for CS 537 rather than just a general networking or backend systems assignment.

---

## 9. The intended datasets and why they matter

The meeting notes specifically mention:
- **Array of Things**
- and another temperature/environment-style source

The earlier context also identifies:
- **Array of Things (Chicago)** as an environmental dataset,
- and **Intel Berkeley Lab sensor data** as a second real-world telemetry source.

The important contextual point is not the exact preprocessing pipeline, but **why** these datasets matter:

- They make the project more realistic than using entirely fabricated traffic.
- They give the sensor stream natural variation and heterogeneity.
- They support the argument that Agrasandhani is being evaluated on plausible IoT-style workloads.

So the project should be understood as working with **real-world inspired or real-world replayed sensor data**, not only toy message streams.

---

## 10. What this project is not

To avoid future confusion, Agrasandhani should **not** be understood as any of the following:

### Not just a dashboard project
The dashboard is part of the evaluation surface, but the main contribution is the **gateway behavior under impairment**.

### Not just an MQTT demo
MQTT is the protocol context, but the research question is not merely “how to use MQTT.”

### Not a Kafka or RabbitMQ implementation project
Those systems belong in related work and conceptual comparison, not as implementation targets.

### Not a generic bandwidth-reduction-only project
The original intuition may have involved traffic reduction, but the true project scope is broader:
- communication shaping,
- stability,
- freshness,
- and reliability/continuity under degradation.

### Not a pure protocol paper
The project is end-to-end and includes what the dashboard ultimately sees, not only broker or transport behavior.

---

## 11. What the final paper should feel like

The final report should read like a **small systems paper** centered on a gateway design and its trade-offs.

It should communicate:

1. **The problem**
   - naive sensor forwarding is fragile for real-time dashboards

2. **The system idea**
   - a smart MQTT-based gateway that reshapes the stream before visualization

3. **The architectural refinement**
   - MQTT on the ingest side, WebSockets on the dashboard side

4. **The comparison structure**
   - variants that isolate batching, compaction, adaptation, and state retention

5. **The evaluation setting**
   - realistic sensor traces and controlled network impairments

6. **The core trade-offs**
   - timeliness vs stability
   - communication volume vs visualization continuity
   - freshness vs graceful degradation

7. **The broader context**
   - where MQTT fits relative to pub/sub systems like Kafka and RabbitMQ
   - how this work relates to edge/fog data reduction and sensor architectures like Senselet++

---

## 12. Working project summary

Agrasandhani is a **research project on smart gateway behavior for IoT sensor visualization**.

It studies how an MQTT-based gateway can reshape bursty sensor streams before they reach a real-time dashboard, with a focus on:
- batching,
- deduplication/compaction,
- adaptive behavior,
- state retention,
- and controlled impairment scenarios such as loss, delay, bandwidth limits, and outages.

The project’s defining question is not simply whether data can be delivered, but how the **displayed sensor state remains stable, timely, and interpretable** when the network is imperfect.

That is the central context any future agent should preserve.