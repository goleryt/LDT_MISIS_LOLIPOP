import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { canWrite, jsonRequest } from "../api/session";
type Prediction = { id: number; object_id: number; incident_type: string; probability: number;
  horizon_hours: number; calculated_at: string; model_version: string; recommendation: string | null;
  status: string; revision: number; actual_outcome: string | null; request_id: number | null };
type Decision = { actor: string; decision: string; reason: string; notes: string | null; actual_outcome: string | null; created_at: string };
export default function PredictionsPage() {
  const [rows, setRows] = useState<Prediction[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Prediction | null>(null);
  const [history, setHistory] = useState<Decision[]>([]);
  const [decision, setDecision] = useState("monitoring");
  const [reason, setReason] = useState("telemetry");
  const [notes, setNotes] = useState("");
  const [outcome, setOutcome] = useState("");
  const [busy, setBusy] = useState(false);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  async function refresh() {
    const [list, status, catalog] = await Promise.all([
      jsonRequest<Prediction[]>("/api/v1/predictions"),
      jsonRequest<{ message: string }>("/api/v1/predictions/status"),
      jsonRequest<Record<string, string>>("/api/v1/predictions/reasons"),
    ]);
    setRows(list); setMessage(status.message); setReasons(catalog);
  }
  useEffect(() => { void refresh().catch(e => setError(e.message)); }, []);
  async function select(row: Prediction) {
    try {
      const detail = await jsonRequest<Prediction & { decisions: Decision[] }>(`/api/v1/predictions/${row.id}`);
      setSelected(detail); setHistory(detail.decisions); setNotes(""); setOutcome(detail.actual_outcome ?? ""); setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось загрузить прогноз"); }
  }
  async function save() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      const updated = await jsonRequest<Prediction>(`/api/v1/predictions/${selected.id}/decision`, {
        method: "PATCH", body: JSON.stringify({ revision: selected.revision, decision, reason, notes, actual_outcome: outcome || null }),
      });
      await refresh(); await select(updated);
    } catch (e) { setError(e instanceof Error ? e.message : "Ошибка сохранения"); }
    finally { setBusy(false); }
  }
  async function createRequest() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      await jsonRequest(`/api/v1/predictions/${selected.id}/request`, { method: "POST" });
      await refresh(); await select(selected);
    } catch (e) { setError(e instanceof Error ? e.message : "Ошибка создания заявки"); }
    finally { setBusy(false); }
  }
  return <section className="operations-page"><h1>Журнал прогнозов</h1><p className="status-notice">{message}</p>
    {error && <p role="alert">{error}</p>}
    {!rows.length && <p>Прогнозов нет. Текущие срабатывания доступны в разделе «Тревоги».</p>}
    {rows.length > 0 && <table><thead><tr><th>Объект</th><th>Тип</th><th>Вероятность</th><th>Горизонт</th><th>Статус</th><th>Просмотр</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.id}><td>{row.object_id}</td><td>{row.incident_type}</td><td>{(row.probability * 100).toFixed(1)}%</td>
        <td>{row.horizon_hours} ч</td><td>{row.status}</td><td><button onClick={() => select(row)}>Открыть</button></td></tr>)}</tbody></table>}
    {selected && <article className="prediction-detail"><h2>Прогноз №{selected.id}</h2>
      <p>Модель: {selected.model_version} · Расчёт: {new Date(selected.calculated_at).toLocaleString("ru-RU")}</p>
      <p>{selected.recommendation ?? "Рекомендация не предоставлена моделью"}</p>
      {selected.request_id ? <Link to="/requests">Открыть заявки · №{selected.request_id}</Link> :
        <button disabled={busy || !canWrite("predictions") || !selected.recommendation || ["closed", "false_alarm"].includes(selected.status)} onClick={createRequest}>Создать заявку по рекомендации</button>}
      <fieldset disabled={busy || !canWrite("predictions") || selected.status === "closed"}><legend>Решение диспетчера</legend>
        <label>Действие<select value={decision} onChange={e => setDecision(e.target.value)}>
          <option value="monitoring">Мониторинг</option><option value="confirmed">Подтверждено</option><option value="false_alarm">Ложное срабатывание</option>
          <option value="dispatch">Выезд бригады</option><option value="closed">Закрыть</option></select></label>
        <label>Причина<select value={reason} onChange={e => setReason(e.target.value)}>{Object.entries(reasons).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>
        <label>Комментарий<textarea maxLength={4000} value={notes} onChange={e => setNotes(e.target.value)} /></label>
        <label>Фактический исход<textarea maxLength={4000} value={outcome} onChange={e => setOutcome(e.target.value)} /></label>
        <button onClick={save}>Сохранить решение</button>
      </fieldset><h3>История решений</h3>{history.map((entry, index) => <p key={index}>{new Date(entry.created_at).toLocaleString("ru-RU")} · {entry.actor} · {entry.decision} · {reasons[entry.reason]} · {entry.notes} · {entry.actual_outcome}</p>)}
    </article>}
  </section>;
}
