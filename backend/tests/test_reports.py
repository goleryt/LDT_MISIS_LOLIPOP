import io
from datetime import datetime, timezone
from openpyxl import load_workbook

def test_report_export_and_formula_safety(login):
    client=login()
    assert client.post("/api/v1/requests",json={"object_id":1,"title":"=1+1"}).status_code==200
    day=datetime.now(timezone.utc).date().isoformat()
    base=f"/api/v1/reports/repairs?date_from={day}&date_to={day}"
    data=client.get(base).json()
    assert data["rows"][0]["title"]=="=1+1"
    xlsx=client.get(base+"&format=xlsx")
    assert xlsx.status_code==200
    workbook=load_workbook(io.BytesIO(xlsx.content),data_only=False)
    assert workbook.active.cell(4,3).value=="'=1+1"
    assert workbook.active.cell(4,3).data_type=="s"
    pdf=client.get(base+"&format=pdf")
    assert pdf.status_code==200
    assert pdf.content.startswith(b"%PDF-")

def test_report_period_validation(login):
    client=login()
    assert client.get("/api/v1/reports/observations?date_from=2026-10-01&date_to=2026-09-01").status_code==422
