import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { canWrite, jsonRequest } from "../api/session";
type Prediction = { id: number; object_id: number; incident_type: string; probability: number;
  horizon_hours: number; calculated_at: string; model_version: string; recommendation: string | null;
  ml_metadata?: { window_start: string; window_end_exclusive: string; as_of_date: string; reference_at: string;
    maintenance_context: string; evidence_level: string; decision_status: string; target_code: string; revision: number } | null;
  status: string; revision: number; actual_outcome: string | null; request_id: number | null };
type Decision = { actor: string; decision: string; reason: string; notes: string | null; actual_outcome: string | null; created_at: string };
// Тип из ответа ML-пакета — наблюдаемое событие в журнале, а не пожар.
const TYPE_LABELS: Record<string, string> = { gas_threshold_cross: "Пересечение газом 1 % CH4 (proxy)" };
export default function PredictionsPage() {
  const [rows, setRows] = useState<Prediction[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Prediction | null>(null);
  const [history, setHistory] = useState<Decision[]>([]);
  const [decision, setDecision] = useState("monitoring");
  const [reason, setReason] = useState("telemetry");
  const [notes, setNotes] = useState("");
  const [outcome, setOutcome] = useState("");
  const [busy, setBusy] = useState(false);
  const [runs, setRuns] = useState<{ id: number; as_of_date: string; revision: number; state: string; error_code: string | null }[]>([]);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  async function refresh() {
    const [list, status, catalog, recentRuns] = await Promise.all([
      jsonRequest<Prediction[]>("/api/v1/predictions"),
      jsonRequest<{ message: string; stale?: boolean }>("/api/v1/predictions/status"),
      jsonRequest<Record<string, string>>("/api/v1/predictions/reasons"),
      jsonRequest<typeof runs>("/api/v1/predictions/runs"),
    ]);
    setRows(list); setHasMore(list.length === 100); setMessage(status.message + (status.stale ? " Расчёт устарел: проверьте журнал запусков." : "")); setReasons(catalog); setRuns(recentRuns);
  }
  async function loadMore() {
    setBusy(true); setError("");
    try {
      const next = await jsonRequest<Prediction[]>(`/api/v1/predictions?after_id=${rows.at(-1)?.id ?? 0}`);
      setRows(previous => [...previous, ...next]); setHasMore(next.length === 100);
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось загрузить историю"); }
    finally { setBusy(false); }
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
    <details><summary>Журнал суточных расчётов</summary>{runs.length ? runs.map(run => <p key={run.id}>{run.as_of_date} · ревизия {run.revision} · {run.state}{run.error_code ? ` · ${run.error_code}` : ""}</p>) : <p>Запусков пока нет. Нужны проверенные исходные данные и отметка завершения суток.</p>}</details>
    {!rows.length && <p>Прогнозов нет. Текущие срабатывания доступны в разделе «Тревоги».</p>}
    {rows.length > 0 && <table><thead><tr><th>Объект</th><th>Тип</th><th>Оценка (proxy)</th><th>Окно прогноза</th><th>Статус</th><th>Просмотр</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.id}><td>{row.object_id}</td><td>{TYPE_LABELS[row.incident_type] ?? row.incident_type}</td><td>{(row.probability * 100).toFixed(1)}%</td>
        <td>{row.ml_metadata ? `${row.ml_metadata.window_start} — ${row.ml_metadata.window_end_exclusive} (не включая)` : `${row.horizon_hours} ч`}</td><td>{row.status}</td><td><button onClick={() => select(row)}>Открыть</button></td></tr>)}</tbody></table>}
    {hasMore && <button disabled={busy} onClick={loadMore}>Загрузить ещё прогнозы</button>}
    {selected && <article className="prediction-detail"><h2>Прогноз №{selected.id}</h2>
      <p>Модель: {selected.model_version} · Расчёт: {new Date(selected.calculated_at).toLocaleString("ru-RU")}</p>
      {selected.ml_metadata && <p>Данные на {selected.ml_metadata.as_of_date} · ревизия {selected.ml_metadata.revision} · {selected.ml_metadata.evidence_level}. Контекст: {selected.ml_metadata.maintenance_context === "possible_recent_silence" ? "Возможно, после ТО/поверки; требуется проверка журнала работ" : selected.ml_metadata.maintenance_context === "verified_schedule" ? "Подтверждённое окно ППР" : "Сведения о ТО отсутствуют"}. Горизонт {selected.horizon_hours} ч отсчитывается от завершения суток данных. Автоматические действия отключены.</p>}
      <p>{selected.recommendation ?? "Рекомендация не предоставлена моделью"}</p>
      {selected.request_id ? <Link to="/requests">Открыть заявки · №{selected.request_id}</Link> :
        <button disabled={busy || !canWrite("predictions") || !selected.recommendation || ["closed", "false_alarm"].includes(selected.status)} onClick={createRequest}>Создать заявку вручную</button>}
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
