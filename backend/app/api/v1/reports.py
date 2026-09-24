"""Factual reporting only. Export values are never inferred or forecast."""
import io
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape
from fastapi import APIRouter, HTTPException, Query, Response
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle
from sqlalchemy import func, select
from app.db.models import EventsJournal, PreventiveRequest
from app.db.session import SessionLocal

router = APIRouter(prefix="/reports", tags=["factual reports"])
pdfmetrics.registerFont(TTFont("NotoSans", str(Path(__file__).resolve().parents[2] / "assets" / "NotoSans-Regular.ttf")))
ROW_LIMIT = 5000

def neutralize_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value

def export(rows, columns, title, format, truncated):
    if format == "json":
        return {"title": title, "rows": rows, "truncated": truncated, "row_limit": ROW_LIMIT}
    output = io.BytesIO()
    if format == "xlsx":
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet("Отчёт")
        sheet.append([title])
        sheet.append(["Достигнут лимит строк; сузьте период" if truncated else "Все строки выбранного периода"])
        sheet.append([label for _, label in columns])
        for row in rows:
            sheet.append([neutralize_cell(row[key]) for key, _ in columns])
        workbook.save(output)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        style = ParagraphStyle("body", fontName="NotoSans", fontSize=8, leading=11)
        story = [Paragraph(escape(title), style), Spacer(1,12)]
        if truncated:
            story.append(Paragraph("Достигнут лимит строк. Сузьте период для полного отчёта.", style))
        data = [[Paragraph(escape(label), style) for _, label in columns]]
        data += [[Paragraph(escape(str(row[key] if row[key] is not None else "—")), style) for key, _ in columns] for row in rows]
        table = LongTable(data, repeatRows=1, colWidths=[750/len(columns)]*len(columns))
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e1edf2")),
                                   ("VALIGN",(0,0),(-1,-1),"TOP"),("GRID",(0,0),(-1,-1),.25,colors.lightgrey)]))
        story.append(table)
        SimpleDocTemplate(output,pagesize=landscape(A4),leftMargin=40,rightMargin=40,topMargin=35,bottomMargin=35).build(story)
        media = "application/pdf"
    return Response(output.getvalue(), media_type=media,
                    headers={"Content-Disposition":f'attachment; filename="factual-report.{format}"',"X-Report-Truncated":str(truncated).lower()})

@router.get("/{kind}")
def report(kind: Literal["observations","repairs"], date_from: date, date_to: date,
           format: Literal["json","xlsx","pdf"]="json"):
    if date_to < date_from or (date_to-date_from).days > 366:
        raise HTTPException(422,"Choose an ordered period of at most 367 calendar days")
    start=datetime.combine(date_from,time.min)
    end=datetime.combine(date_to+timedelta(days=1),time.min)
    if kind=="observations":
        query=select(func.date(EventsJournal.d_event_time).label("day"),
                     func.count().label("observations"),
                     func.count().filter(EventsJournal.d_alarm.is_(True)).label("alarms")).where(
                     EventsJournal.d_event_time>=start,EventsJournal.d_event_time<end).group_by("day").order_by("day")
        columns=[("day","Дата"),("observations","Наблюдения"),("alarms","Тревожные наблюдения")]
        title=f"Фактические наблюдения · {date_from} — {date_to}"
    else:
        query=select(PreventiveRequest.id,PreventiveRequest.object_id,PreventiveRequest.title,
                     PreventiveRequest.status,PreventiveRequest.created_at,PreventiveRequest.completed_at).where(
                     PreventiveRequest.created_at>=start.replace(tzinfo=timezone.utc),
                     PreventiveRequest.created_at<end.replace(tzinfo=timezone.utc)).order_by(PreventiveRequest.id)
        columns=[("id","Заявка"),("object_id","Объект"),("title","Тема"),("status","Статус"),
                 ("created_at","Создана UTC"),("completed_at","Завершена UTC")]
        title=f"История заявок (даты UTC) · {date_from} — {date_to}"
    with SessionLocal() as db:
        result=db.execute(query.limit(ROW_LIMIT+1)).mappings().all()
    truncated=len(result)>ROW_LIMIT
    rows=[{key:(value.isoformat() if isinstance(value,(date,datetime)) else value) for key,value in row.items()} for row in result[:ROW_LIMIT]]
    return export(rows,columns,title,format,truncated)
