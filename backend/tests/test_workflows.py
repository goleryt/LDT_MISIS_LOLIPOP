import io
import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
from openpyxl import Workbook
from sqlalchemy import func, select
from app.core.security import password_hash, verify_password, permitted
from app.db.models import EventsJournal, DataImport
from app.db.platform import AuditEntry, Notification, Prediction, IntegrationRecord
from app.db.session import SessionLocal
from app.ingestion.formats import decode_records
from app.ingestion.csv_loader import parse_sensor_value
from app.api.v1.geo import LocationInput, parse_location

def row(event_id=1):
    return {"ид_события": str(event_id), "ид_канала_данных": "1", "дата": "2026-09-01",
            "время": "10:00:00", "тревожное": "true", "значение_датчика": "25,1"}

def count(model):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))

def test_anonymous_denied_and_audited(client):
    assert client.get("/api/v1/events").status_code == 401
    assert count(AuditEntry) == 1
    assert client.get("/health").status_code == 200

def test_login_csrf_logout(login):
    c = login()
    cookie = c.cookies.get("ldt_session")
    c.headers.pop("X-CSRF-Token")
    assert c.post("/api/v1/requests", json={"object_id": 1, "title": "Проверка"}).status_code == 403
    csrf = c.get("/api/v1/auth/me").json()["csrf_token"]
    c.headers["X-CSRF-Token"] = csrf
    assert c.post("/api/v1/auth/logout").status_code == 200
    c.cookies.set("ldt_session", cookie)
    assert c.get("/api/v1/events").status_code == 401

def test_login_origin_and_rate_limit(client):
    data = {"username": "missing", "password": "invalid"}
    assert client.post("/api/v1/auth/login", json=data, headers={"origin": "https://evil.example"}).status_code == 403
    for _ in range(10):
        assert client.post("/api/v1/auth/login", json=data).status_code == 401
    assert client.post("/api/v1/auth/login", json=data).status_code == 429

@pytest.mark.parametrize("role,code", [("manager",403),("analyst",403),("technician",200),("dispatcher",200),("admin",200)])
def test_request_rbac(login, role, code):
    c=login(role)
    assert c.post("/api/v1/requests",json={"object_id":1,"title":"Проверить датчик"}).status_code == code

@pytest.mark.parametrize("field", ["title", "priority", "status"])
def test_request_null_rejected(login, field):
    c=login()
    item=c.post("/api/v1/requests",json={"object_id":1,"channel_id":1,"title":"Проверка"}).json()
    response=c.patch(f"/api/v1/requests/{item['id']}",json={field:None})
    assert response.status_code == 422, response.text

def test_request_completion_cannot_reopen(login):
    c=login()
    item=c.post("/api/v1/requests",json={"object_id":1,"title":"Проверка"}).json()
    path=f"/api/v1/requests/{item['id']}"
    assert c.patch(path,json={"status":"completed"}).status_code == 200
    assert c.patch(path,json={"status":"new"}).status_code == 409

def file_content(format):
    record=row()
    if format=="json":
        return json.dumps([record],ensure_ascii=False).encode()
    if format=="xml":
        return ("<records><record>"+ "".join(f"<{k}>{v}</{k}>" for k,v in record.items())+"</record></records>").encode()
    if format=="csv":
        import csv
        out=io.StringIO()
        writer=csv.DictWriter(out,fieldnames=list(record))
        writer.writeheader(); writer.writerow(record)
        return out.getvalue().encode("utf-8-sig")
    workbook=Workbook()
    workbook.active.append(list(record))
    workbook.active.append(list(record.values()))
    output=io.BytesIO(); workbook.save(output)
    return output.getvalue()

@pytest.mark.parametrize("format",["csv","xlsx","json","xml"])
def test_file_formats_and_idempotency(login,format):
    c=login()
    body=file_content(format)
    for _ in range(2):
        result=c.post("/api/v1/imports/events",files={"file":(f"test.{format}",body)})
        assert result.status_code == 200,result.text
    assert count(EventsJournal)==1
    assert count(DataImport)==1
    assert count(Notification)==0  # historical file uploads do not page dispatchers
    assert c.get("/api/v1/sensors/1/history").json()["returned_events"]==1
    assert c.get("/api/v1/alarms").status_code==200
    assert c.get("/api/v1/map/objects").status_code==200

def test_invalid_file_is_atomic(login):
    c=login()
    records=[row(i) for i in range(1,2002)]
    records.append({**row(3000),"тревожное":"not-a-boolean"})
    response=c.post("/api/v1/imports/events",files={"file":("invalid.json",json.dumps(records).encode())})
    assert response.status_code == 400,response.text
    assert count(EventsJournal)==0
    with SessionLocal() as db:
        assert db.scalar(select(DataImport)).status=="failed"

def test_catalogue_import(login):
    c=login()
    objects=[{"ид_объект":"2","иерархия_уровень":"1","родитель":"","вид_объекта":"Коллектор","диспетчерское_название_объекта":"Новый"}]
    response=c.post("/api/v1/imports/events?kind=objects",files={"file":("objects.json",json.dumps(objects).encode())})
    assert response.status_code==200,response.text
    assert c.get("/api/v1/objects/2/sensors").status_code==200

def test_xml_entities_rejected():
    with pytest.raises(Exception):
        decode_records(b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><records><record><a>&x;</a></record></records>',"xml")

def test_nonfinite_values_are_not_numeric():
    assert parse_sensor_value("NaN")== (None,"NaN")
    assert parse_sensor_value("inf")== (None,"inf")

def test_real_geo_and_schematic_fallback(login):
    c=login()
    response=c.put("/api/v1/geo/objects/1",json={"wkt":"POINT (37.61 55.75)"})
    assert response.status_code==200,response.text
    features=c.get("/api/v1/geo/objects").json()["features"]
    assert features[0]["geometry"]["coordinates"]==[37.61,55.75]
    rows=c.get("/api/v1/map/objects").json()
    assert rows[0]["geometry_is_synthetic"] is False
    assert rows[0]["geometry"]["coordinates"]==[37.61,55.75]

@pytest.mark.parametrize("wkt",["POINT (181 0)","LINESTRING (0 0, 1 1)","POINT (NaN 0)"])
def test_bad_geo(wkt):
    with pytest.raises(ValueError):
        parse_location(LocationInput(wkt=wkt))

def telemetry():
    return {"external_id":"sensor-1","observed_at":datetime.now(timezone.utc).isoformat(),
            "channel_id":1,"event_id":101,"alarm":True,"value":"25"}

def test_stream_retry_notifications_and_conflict(login):
    c=login("admin")
    message=telemetry()
    first=c.post("/api/v1/integrations/telemetry",json=[message])
    assert first.status_code==200,first.text
    assert first.json()["within_300_seconds"]
    assert c.post("/api/v1/integrations/telemetry",json=[message]).json()["duplicates"]==1
    assert c.post("/api/v1/integrations/telemetry",json=[{**message,"value":"30"}]).status_code==422
    assert count(EventsJournal)==count(Notification)==count(IntegrationRecord)==1
    notice=c.get("/api/v1/notifications").json()[0]
    assert c.post(f"/api/v1/notifications/{notice['id']}/read").status_code==200
    assert c.get("/api/v1/notifications").json()==[]

def test_mock_disabled_and_unknown_channel(login):
    c=login("admin")
    assert c.post("/api/v1/integrations/telemetry",json=[{**telemetry(),"mock":True}]).status_code==422
    assert c.post("/api/v1/integrations/telemetry",json=[{**telemetry(),"channel_id":999}]).status_code==422
    assert count(IntegrationRecord)==0

def test_no_fabricated_predictions(login):
    c=login()
    assert c.get("/api/v1/predictions").json()==[]
    status=c.get("/api/v1/predictions/status").json()
    assert status["available"] is False
    response=c.post("/api/v1/predictions/inference",json={"object_id":1})
    assert response.status_code==503,response.text
    assert response.json()["detail"]["code"]=="model_not_configured"
    assert count(Prediction)==count(Notification)==0

def test_all_monitoring_routes(login):
    c=login()
    for path in ("/objects/1/sensors","/map/objects","/alarms","/events","/sensors/1/history","/requests","/imports"):
        response=c.get("/api/v1"+path)
        assert response.status_code==200,(path,response.text)

def test_audit_does_not_contain_password(login):
    c=login("admin")
    rows=c.get("/api/v1/audit").json()
    assert rows
    assert "test-only-password" not in json.dumps(rows)
