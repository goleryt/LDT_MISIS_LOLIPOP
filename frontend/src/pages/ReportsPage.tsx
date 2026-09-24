import { useState } from "react";
import { apiFetch } from "../api/session";
import { API_BASE_URL } from "../api/config";
export default function ReportsPage() {
  const today = new Date().toISOString().slice(0,10);
  const [kind,setKind] = useState("observations");
  const [start,setStart] = useState(today.slice(0,8)+"01");
  const [end,setEnd] = useState(today);
  const [busy,setBusy] = useState(false);
  const [message,setMessage] = useState("");
  async function download(format: "xlsx" | "pdf") {
    setBusy(true); setMessage("");
    try {
      const params = new URLSearchParams({date_from:start,date_to:end,format});
      const response = await apiFetch(`${API_BASE_URL}/api/v1/reports/${kind}?${params}`);
      if (!response.ok) throw new Error("Не удалось сформировать отчёт. Проверьте период (не более года).");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href=url; link.download=`report-${kind}-${start}.${format}`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage(response.headers.get("X-Report-Truncated")==="true" ? "Достигнут лимит 5000 строк. Сузьте период." : "Отчёт сформирован.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Ошибка отчёта"); }
    finally { setBusy(false); }
  }
  return <section className="operations-page"><h1>Фактические отчёты</h1>
    <p>Наблюдения и история заявок. Прогнозные показатели не рассчитываются.</p>
    <div className="prediction-detail"><fieldset disabled={busy}><legend>Параметры отчёта</legend>
      <label>Данные<select value={kind} onChange={e=>setKind(e.target.value)}><option value="observations">Наблюдения датчиков</option><option value="repairs">История заявок</option></select></label>
      <label>С<input type="date" value={start} onChange={e=>setStart(e.target.value)} /></label>
      <label>По<input type="date" value={end} onChange={e=>setEnd(e.target.value)} /></label>
      <button disabled={!start || !end || start>end} onClick={()=>download("xlsx")}>Скачать XLSX</button>
      <button disabled={!start || !end || start>end} onClick={()=>download("pdf")}>Скачать PDF</button>
    </fieldset></div>{message && <p role="status">{message}</p>}
  </section>;
}
