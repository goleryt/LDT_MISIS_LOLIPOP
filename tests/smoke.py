import os
import httpx
with httpx.Client(base_url=os.environ.get("BASE_URL","http://127.0.0.1:8080"),trust_env=False) as client:
    assert client.get("/health").status_code==200
    assert client.get("/ready").status_code==200
    assert client.get("/api/v1/events").status_code==401
    assert client.get("/openapi.json").status_code==401
    result=client.post("/api/v1/auth/login",json={"username":os.environ["TEST_USERNAME"],"password":os.environ["TEST_PASSWORD"]})
    result.raise_for_status()
    client.headers["X-CSRF-Token"]=result.json()["csrf_token"]
    schema = client.get("/openapi.json")
    schema.raise_for_status()
    assert "/api/v1/predictions/runs" in schema.json()["paths"]
    for path in ("/events","/map/objects","/alarms","/requests","/imports","/predictions","/notifications"):
        result=client.get("/api/v1"+path)
        result.raise_for_status()
    status = client.get("/api/v1/predictions/status")
    status.raise_for_status()
    assert isinstance(status.json()["available"], bool)
    client.post("/api/v1/auth/logout").raise_for_status()
    print("Smoke passed")
