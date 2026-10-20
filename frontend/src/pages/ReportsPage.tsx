import { useState } from "react";
import { apiFetch, responseError } from "../api/session";
import { API_BASE_URL } from "../api/config";
export default function ReportsPage() {
  const now = new Date();
  // Date controls select a calendar day in the user's browser timezone.
  // ISO serialization would select yesterday just after Moscow midnight.
  const today = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}-${String(now.getDate()).padStart(2,"0")}`;
  const [kind,setKind] = useState("observations");
  const [start,setStart] = useState(today.slice(0,8)+"01");
  const [end,setEnd] = useState(today);
  const [busy,setBusy] = useState(false);
  const [message,setMessage] = useState("");
  const invalidPeriod = !start || !end ? "Укажите начало и конец периода." : start > end ? "Начало периода не может быть позже конца." : "";
  async function download(format: "xlsx" | "pdf") {
    setBusy(true); setMessage("");
    try {
      const params = new URLSearchParams({date_from:start,date_to:end,format});
      const response = await apiFetch(`${API_BASE_URL}/api/v1/reports/${kind}?${params}`);
      if (!response.ok) throw responseError(response);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href=url; link.download=`report-${kind}-${start}.${format}`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage(response.headers.get("X-Report-Truncated")==="true" ? "Достигнут лимит 5000 строк. Сузьте период." : "Отчёт сформирован.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Ошибка отчёта"); }
    finally { setBusy(false); }
  }
  return <section className="operations-page reports-page"><h1>Фактические отчёты</h1>
    <p>Наблюдения и история заявок. Прогнозные показатели не рассчитываются.</p>
    <div className="prediction-detail reports-detail"><fieldset disabled={busy}><legend>Параметры отчёта</legend>
      <label className="reports-field-wide">Данные<select value={kind} onChange={e=>setKind(e.target.value)}><option value="observations">Наблюдения датчиков</option><option value="repairs">История локальных заявок</option></select></label>
      <label>С<input type="date" aria-invalid={!!invalidPeriod} aria-describedby={invalidPeriod ? "report-period-error" : undefined} value={start} onChange={e=>setStart(e.target.value)} /></label>
      <label>По<input type="date" aria-invalid={!!invalidPeriod} aria-describedby={invalidPeriod ? "report-period-error" : undefined} value={end} onChange={e=>setEnd(e.target.value)} /></label>
      {invalidPeriod && <p id="report-period-error" className="reports-field-wide" role="alert">{invalidPeriod}</p>}
      <div className="reports-actions">
        <button className="primary-button" disabled={!!invalidPeriod} onClick={()=>download("xlsx")}>Скачать XLSX</button>
        <button className="primary-button" disabled={!!invalidPeriod} onClick={()=>download("pdf")}>Скачать PDF</button>
      </div>
    </fieldset></div>{busy && <p role="status">Формирование отчёта…</p>}{message && <p role="status">{message}</p>}
  </section>;
}
