# Technical Specification - Working Summary

> **Purpose:** compact, source-grounded reference for the team and agents. It summarizes
> `docs/8. ДЖКХ.pdf` (15 content pages plus cover) and is not a replacement for the source.
> **Source date:** 2026-09-11 (PDF metadata). **Last reviewed:** 2026-09-16.
> **Reliability rule:** items marked **Open** are not facts and require organizer confirmation
> or evidence in supplied data before they guide modeling or implementation.

## 1. Product intent

Build a standalone predictive-analytics service for Moscow engineering collectors, operated by
ODС dispatchers, maintenance personnel, and operating-unit managers. The service analyzes
historical and current monitoring data, predicts incidents, presents probability, horizon and
location, and recommends preventive actions. It supports, but does not replace, dispatcher
judgement.

The intended outcomes are earlier risk detection, fewer false alarm call-outs, condition-based
maintenance, safer infrastructure, and lower operating cost.

## 2. Required capability and boundaries

### The service must

- Predict risks at least **24 hours** ahead, including probability, incident type, and the
  location of at-risk equipment.
- Analyze historical/current sensor data, ODS dispatcher logs, and equipment registers.
- Perform incident pattern/scenario analysis; send preventive notifications; recommend
  maintenance/repair actions.
- Offer a web dashboard, interactive infrastructure map, forecast journal/history and outcome
  tracking, and critical-incident notifications.
- Expose REST API for external-system interaction; read monitoring-system data and synchronize
  the equipment register.

### The service must not

- Replace dispatchers or make final incident decisions.
- Directly control equipment or perform repair work.

### Incident scope stated in the specification

- Sensor and engineering-system failures.
- Fire risk.
- Flooding risk.
- Decision support for verifying unauthorized-access facts.

**Working-project scope differs:** the repository README currently selects *sensor failure* and
*unauthorized access*. This is a team choice, not a confirmed reduction of the specification;
whether fire and flooding are mandatory is **Open**.

## 3. Data and integration contract

| Source / interface | TЗ expectation | Known constraints |
| --- | --- | --- |
| СМВУ monitoring system | Contact, motion, temperature, smoke and gas sensor data; near-real-time | Read-only internal integration; API or message queue stated, exact endpoint/schema not supplied. |
| ODS journals | Trigger records and incident history, at least 12 years | API upload is stated; label/event semantics are not defined. |
| Equipment register | Construction assets (hatches, ventilation shafts, chambers), pumps, fans, sensors | Digital format; synchronization with customer records; join keys and availability are **Open**. |
| Work-order system | Obtain work-order statuses | Whether creation/submission of new work orders is required is **Open**. |
| Meteorological service | Temperature, humidity, precipitation, atmospheric pressure | Open API; relevant mainly to flooding scenario. |
| Geodata | GeoJSON or WKT | Coordinates/geometries and map granularity are **Open**. |

Supported file exchange is CSV/XLSX; APIs may use JSON/XML; database connectivity should support
PostgreSQL (or the customer's alternative DBMS). Data must be obfuscated/anonymized **by the
source system** before transfer. Internal integrations are explicitly read-only.

### Appendix 1: supplied example schema only

The PDF gives an illustrative technological-event journal, not a complete production schema:

- Journal fields: `ИД записи журнала`, `ИД канала данных`, `ИД типа канала данных`,
  `Текущее значение`, `Дата записи`.
- Channel register: `ИД канала данных`, `Тег в дереве объектов`.
- Sensor-type register: `ИД типа канала датчика`, `Название`, `Диспетчерское название`.
- Object/system tree: `ИД записи`, `ИД системы`, `Диспетчерское название`, `Название`.
- Example channel types include `contact-unlock-norm`, `switch`, `smoke`, `movement`, `gas`,
  `pump`, `fan`, `phase`, `temperature`.

Do not infer a target, entity mapping, time-zone convention, or feature availability from this
example. Preserve exact delivered column names in any later data contract.

## 4. ML and evaluation guardrails

- The TЗ requires predictive modeling from historical data, but it does **not** define target
  labels, positive-class events, labeling windows, train/test split, or a primary metric.
- Precision and Recall targets are to be set during design based on the quality of supplied data;
  the PDF does not set numeric thresholds.
- Evaluation at final review includes comparison of forecasts with real values/data and the
  credibility of recommendations under actual conditions.
- Treat target, event timestamp, and feature-availability time as separate facts. No supervised
  target or leakage-safe feature may be claimed until data evidence or organizer confirmation.
- Suggested future capability, not an unqualified baseline requirement: retraining on new data,
  historical repair reports, seasonal analytics, false-positive explanations, and PDF/XLSX
  analytical reports. These are explicitly subject to agreement with the customer.

## 5. UX and operating workflow

Required views/features: dashboard with risk levels, map with problem zones, forecast journal
with handling results, and real-time alerts for critical incidents. The interface should be
accessible, intuitive, and contain only elements needed for a user task.

The specification's example workflows (fire and flooding) follow the same sequence:

1. Compare current signals with historical patterns and relevant context (planned work for fire;
   weather and pump activity for flooding).
2. Calculate risk probability and create an alert.
3. Show probability, horizon, and location to the dispatcher.
4. Dispatcher verifies, potentially using external evidence such as cameras.
5. Dispatcher records a decision and a reason from a reference list.
6. Save the outcome for later analysis and possible retraining.

These are illustrative scenarios; neither required fields nor the external verification systems
are fully specified.

## 6. Non-functional requirements

| Area | Requirement |
| --- | --- |
| Forecast latency | No more than 5 minutes / 300 seconds per object. |
| Stream latency | Near real time, no more than 5 minutes / 300 seconds. |
| Concurrency | At least 20 simultaneous users without degradation. |
| Recovery | Restore service within 4 hours after failure; automatic backups. |
| Security | TLS 1.2+, LDAP/AD integration support, RBAC, audit logging of all user actions. |
| Platform | Linux server; current Google Chrome and Yandex Browser; PostgreSQL 12+. |

Availability is tied to the customer's information-system operating regulations; no numeric SLA is
provided.

## 7. Deliverables and judging

Required submission links: code repository, presentation, usable prototype, and supporting
documentation (`.docx` or `.pdf`). Presentation format: PPTX or PDF.

The solution must provide open, unobfuscated source code; describe methods, constraints,
libraries/components, build/install instructions, functional architecture, and component
architecture. Complex technical/logical details should be commented.

Judging emphasizes: idea/originality/technology, code quality and integration potential,
performance, demonstrable calculations and forecast reliability, recommendations aligned with
actual conditions, configurable parameters, readable/truthful charts, UX usability, documentation,
and the pitch.

## 8. Open questions that can block a defensible implementation

1. Which incident directions are mandatory at final evaluation: all four stated directions, or
   the team's selected sensor-failure and unauthorized-access subset?
2. What records establish each positive event (sensor failure, unauthorized access, fire,
   flooding), and at what timestamp?
3. How are sensor channels linked to equipment, collector objects, locations, and geodata?
4. Which source datasets, registers, work-order records, and APIs are actually available during
   the hackathon? Is the journal example training data, format-only material, or protected test
   data?
5. What exactly is required for preventive work orders: fields, lifecycle, storage, and external
   submission versus a local draft?
6. What evaluation split, main metric, thresholds, and comparison procedure will organizers use?
7. What map geometry and risk aggregation level are expected (sensor, equipment, object, or
   collector section)?

The living organizer-question register is the authoritative place for question status and answers:
<https://docs.google.com/document/d/1Gj6WUhaqzryn1ydpDr2pRR-iFTzQswHVmNn-4EK0paA>.

## 9. Implementation defaults until answers arrive

- Keep raw inputs immutable and use a read-only audit before transformations.
- Store all source field names exactly as received; document lineage and availability time.
- Do not claim external integration, labels, map accuracy, or metric compliance without evidence.
- Build the prototype so it can show a clearly labeled demo/synthetic path separately from any
  real supplied data.
- Record decisions and organizer answers in the question register, then update this summary only
  when they change an established requirement or constraint.
