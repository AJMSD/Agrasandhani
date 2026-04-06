# PROJECT_CONTEXT.md

**Project Name:** Agrasandhini — MQTT-Based Smart Gateway for Sensor Visualization Under Network Impairments
**Course:** CS 537 – Multimedia Systems
**Project Type:** Systems + Networking + IoT Research Project
**Date:** April 2026

---

# 1. Project Overview

Agrasandhini is a **smart gateway system for IoT sensor data visualization** that studies how **MQTT-based sensor pipelines behave under network impairments** such as:

* Packet loss
* Network delay
* Bandwidth limitations
* Temporary network outages

The project builds a **full end-to-end system** and evaluates **reliability, latency, throughput, and dashboard frame rate** under different system configurations (batching levels) and network conditions.

This is not just an IoT dashboard — it is a **systems research project** focused on **reliability and performance of MQTT pipelines under impaired networks**.

---

# 2. Final System Architecture

## Architecture (Final Version After Professor Feedback)

```
Sensors / Dataset Simulator
            ↓
        MQTT Publisher
            ↓
        MQTT Broker
            ↓
    Impairment Harness
   (loss, delay, outage)
            ↓
        Smart Gateway
   (processing + batching)
            ↓
        WebSocket Server
            ↓
        Dashboard (Grafana / Web UI)
```

---

# 3. Key Design Decisions

## 3.1 MQTT is Used For

* Communication between **Sensors → MQTT Broker → Smart Gateway**
* Lightweight, reliable pub/sub protocol
* Supports QoS levels
* Suitable for IoT streaming

## 3.2 WebSockets Are Used For

* Communication between **Smart Gateway → Dashboard**
* Needed for **real-time visualization**
* Better for browser dashboards than MQTT

## 3.3 Smart Gateway Responsibilities

The Smart Gateway is the **core system component** and performs:

* MQTT subscription
* Message buffering
* Batching
* Aggregation
* Processing
* Forwarding to dashboard via WebSockets
* Handling network impairment effects
* Recovery after outages

The **backend and smart gateway are merged** into a single component.

---

# 4. Research Goals

The main research goal:

> Study how an MQTT-based smart gateway pipeline behaves under network impairments and how batching and gateway design improve reliability and visualization continuity.

---

# 5. Experiment Variables

## 5.1 System Variants (Batching Levels)

| Variant | Description                                  |
| ------- | -------------------------------------------- |
| V0      | No batching (send every message immediately) |
| V2      | Medium batching                              |
| V4      | High batching                                |

Batching affects:

* Reliability
* Latency
* Throughput
* Dashboard frame rate
* Recovery after outage

---

## 5.2 Network Impairments

The impairment harness introduces:

| Impairment      | Description                              |
| --------------- | ---------------------------------------- |
| Packet Loss     | Random packet drops                      |
| Delay           | Added latency                            |
| Bandwidth Limit | Throttled network                        |
| Outage          | Complete connection drop for time window |

Impairments are applied **between MQTT Broker and Smart Gateway**.

---

# 6. Metrics Collected

The system measures the following metrics:

1. **End-to-End Latency**

   * Sensor → Dashboard time

2. **Packet Delivery Ratio**

   * Messages received / messages sent

3. **Throughput**

   * Messages per second delivered

4. **Dashboard Frame Rate**

   * Frames per second displayed on dashboard

5. **Recovery Time After Outage**

   * Time for system to return to normal after outage

---

# 7. Main Figure of the Paper

The **primary evaluation figure** is:

> **Downstream Frame Rate Over Time During Outage: V0 vs V2 vs V4**

This figure shows:

* Time vs Dashboard Frame Rate
* Outage period marked
* Comparison between batching strategies
* Shows which system maintains visualization best during outages

This is the **main result** of the paper.

---

# 8. Datasets Used

Two real-world datasets are used to simulate IoT sensors, and both are implemented in preprocessing, replay, and report evidence paths.

## Dataset 1 — Array of Things (Chicago)

* Environmental sensors
* Temperature
* Humidity
* Air quality
* Pressure
* Light
* Noise

Used as a portability and validation dataset in the final evaluation pipeline.

## Dataset 2 — Intel Berkeley Lab Deployment Data

A second real-world dataset is used as the primary workload for the final matrix:

* Intel Lab sensor deployment readings
* Time-series telemetry replayed through the same normalized simulator schema
* Used for the primary clean and impairment scenario matrix

Both datasets are **preprocessed and replayed through a sensor simulator** that publishes MQTT messages.

No additional temperature-only dataset is used in the tracked final evidence.

---

# 9. System Components Already Implemented

The following components are already built:

| Component                         | Status               |
| --------------------------------- | -------------------- |
| Dataset preprocessing             | Done                 |
| Sensor simulator                  | Done                 |
| MQTT publisher                    | Done                 |
| MQTT broker                       | Done                 |
| Smart gateway                     | Done                 |
| WebSocket dashboard pipeline      | Done                 |
| Impairment harness                | Done                 |
| Outage simulation                 | Done                 |
| Automated experiment sweep runner | Done                 |
| Metrics collection                | Done                 |
| Analysis pipeline                 | Done                 |
| Plot generation                   | Done                 |
| Live demo harness                 | Done                 |
| Automated test suite              | Done                 |
| Reproducibility documentation     | Done                 |
| Final experiment runs             | Done (April 3, 2026) |

This means the project is in **final research / paper polishing stage**, not development stage.

---

# 10. Experiment Methodology

Each experiment run:

1. Start MQTT broker
2. Start impairment harness
3. Start smart gateway
4. Start dashboard
5. Start sensor simulator
6. Apply impairment (loss / delay / bandwidth / outage)
7. Run for fixed duration
8. Log:

   * Sent messages
   * Received messages
   * Latency
   * Frame rate
   * Throughput
9. Repeat for:

   * V0
   * V2
   * V4
10. Automated sweep runs all combinations
11. Analysis pipeline generates plots

---

# 11. Related Systems (For Paper Discussion)

The project also studies other pub/sub systems conceptually for related work:

| System                | Type                          |
| --------------------- | ----------------------------- |
| MQTT                  | Lightweight IoT pub/sub       |
| Kafka                 | Distributed event streaming   |
| RabbitMQ              | Message broker                |
| Senselet / Senselet++ | Sensor architecture reference |

These are **not fully implemented**, but discussed in **Related Work** section of the paper.

---

# 12. Emulation / Impairment System

The impairment harness simulates bad network conditions by:

* Dropping packets randomly
* Adding delay
* Limiting bandwidth
* Creating outage periods
* Delaying MQTT messages before reaching gateway

This allows controlled experiments.

---

# 13. What This Project Is (Important)

This project is a combination of:

| Area                | Contribution                |
| ------------------- | --------------------------- |
| IoT                 | Sensor data pipeline        |
| Networking          | Impairments and reliability |
| Distributed Systems | Pub/Sub architecture        |
| Multimedia Systems  | Real-time visualization     |
| Systems Research    | Performance evaluation      |

This is **not just a dashboard**.
This is **a reliability and performance study of an IoT streaming system**.

---

# 14. Repository Expectations

The repository should contain:

```
/datasets
/preprocessing
/simulator
/mqtt
/gateway
/websocket
/dashboard
/impairment
/experiments
/analysis
/paper
/figures
/tests
/reproducibility
README.md
PROJECT_CONTEXT.md
PRD.md
```

---

# 15. Reproducibility Requirements

The project must be reproducible by running:

1. Dataset preprocessing
2. Start broker
3. Start impairment harness
4. Start gateway
5. Run experiment sweep
6. Generate plots
7. Build paper figures

Scripts should be provided for:

* Running experiments
* Generating figures
* Reproducing paper results

---

# 16. Final Deliverables

The final deliverables are:

| Deliverable                   | Description                   |
| ----------------------------- | ----------------------------- |
| Working system                | End-to-end pipeline           |
| Experiment results            | Metrics and plots             |
| Main figure                   | Frame rate during outage      |
| Research paper                | Describing system and results |
| Reproducibility documentation | How to rerun experiments      |
| Demo                          | Live dashboard                |

---

# 17. One-Sentence Project Summary

> Agrasandhini is a smart gateway system that uses MQTT to stream IoT sensor data to a real-time dashboard, and this project evaluates how batching and gateway design affect reliability and visualization performance under network impairments such as packet loss, delay, bandwidth limits, and outages.

---.
