import os
import httpx
with httpx.Client(base_url=os.environ.get("BASE_URL","http://127.0.0.1:8080"),trust_env=False) as client:
    assert client.get("/health").status_code==200
    assert client.get("/ready").status_code==200
    assert client.get("/api/v1/events").status_code==401
    result=client.post("/api/v1/auth/login",json={"username":os.environ["TEST_USERNAME"],"password":os.environ["TEST_PASSWORD"]})
    result.raise_for_status()
    client.headers["X-CSRF-Token"]=result.json()["csrf_token"]
    for path in ("/events","/map/objects","/alarms","/requests","/imports","/predictions","/notifications"):
        result=client.get("/api/v1"+path)
        result.raise_for_status()
    assert client.get("/api/v1/predictions/status").json()["available"] is False
    client.post("/api/v1/auth/logout").raise_for_status()
    print("Smoke passed")
