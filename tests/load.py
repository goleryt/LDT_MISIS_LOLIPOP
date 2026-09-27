"""Authenticated HTTP load test. Supply a disposable test account through environment variables."""
import concurrent.futures
import json
import os
import statistics
import time
from pathlib import Path
import httpx

URL = os.environ.get("BASE_URL", "http://127.0.0.1:8080")
USERS = int(os.environ.get("LOAD_USERS", "20"))
ROUNDS = int(os.environ.get("LOAD_ROUNDS", "10"))
INTERVAL = float(os.environ.get("LOAD_INTERVAL_SECONDS", "0"))
if INTERVAL < 0:
    raise SystemExit("LOAD_INTERVAL_SECONDS must be nonnegative")
PATHS = ("/api/v1/map/objects", "/api/v1/objects/1/sensors", "/api/v1/alarms",
         "/api/v1/events?limit=100", "/api/v1/requests", "/api/v1/notifications")

def session():
    client = httpx.Client(base_url=URL, timeout=60, trust_env=False)
    response = client.post("/api/v1/auth/login", json={"username":os.environ["TEST_USERNAME"],"password":os.environ["TEST_PASSWORD"]})
    response.raise_for_status()
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client

def run(client, offset=0):
    latencies=[]
    try:
        time.sleep(offset)
        for _ in range(ROUNDS):
            for path in PATHS:
                started=time.perf_counter()
                response=client.get(path)
                response.raise_for_status()
                latencies.append((time.perf_counter()-started)*1000)
                if INTERVAL:
                    time.sleep(max(0, INTERVAL-(time.perf_counter()-started)))
    finally:
        client.post("/api/v1/auth/logout")
        client.close()
    return latencies

def p95(values):
    return sorted(values)[min(len(values)-1,int(len(values)*.95))]

if __name__=="__main__":
    baseline=run(session())
    # Establish sessions before starting traffic so login throttling is not mistaken for application latency.
    clients=[session() for _ in range(USERS)]
    started=time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=USERS) as pool:
        batches=list(pool.map(lambda pair: run(pair[1], pair[0]*INTERVAL/USERS), enumerate(clients)))
    elapsed=time.perf_counter()-started
    values=[value for batch in batches for value in batch]
    ratio=p95(values)/p95(baseline)
    report={"users":USERS,"requests":len(values),"errors":0,"duration_seconds":round(elapsed,3),
            "profile":"paced_sessions" if INTERVAL else "unpaced_stress",
            "request_interval_seconds":INTERVAL,
            "p50_ms":round(statistics.median(values),3),"p95_ms":round(p95(values),3),
            "baseline_p95_ms":round(p95(baseline),3),"p95_ratio":round(ratio,2),
            "acceptance_p95_ms":2000,"acceptance_ratio":5,
            "passed":p95(values)<2000 and ratio<5}
    print(json.dumps(report,indent=2))
    destination=Path(os.environ.get("LOAD_REPORT", "test-results/load.json"))
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,indent=2),encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(1)
