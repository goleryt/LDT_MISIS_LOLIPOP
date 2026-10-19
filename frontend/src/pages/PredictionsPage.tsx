import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { canWrite, jsonRequest } from "../api/session";
import { useMediaQuery } from "../hooks/useMediaQuery";
type Prediction = { id: number; object_id: number; channel_id?: number | null; incident_type: string; probability: number;
  horizon_hours: number; calculated_at: string; model_version: string; recommendation: string | null;
  ml_metadata?: { window_start: string; window_end_exclusive: string; as_of_date: string; reference_at: string;
    maintenance_context: string; evidence_level: string; decision_status: string; target_code: string; revision: number } | null;
  status: string; revision: number; actual_outcome: string | null; request_id: number | null };
type Decision = { actor: string; decision: string; reason: string; notes: string | null; actual_outcome: string | null; created_at: string };
// Тип из ответа ML-пакета — наблюдаемое событие в журнале, а не пожар.
const TYPE_LABELS: Record<string, string> = { gas_threshold_cross: "Пересечение газом 1 % CH4 (proxy)" };
const STATUS_LABELS: Record<string, string> = { new: "Новый", monitoring: "Мониторинг", confirmed: "Подтверждено", false_alarm: "Ложное срабатывание", dispatch: "Выезд бригады", closed: "Закрыт", pending: "Ожидает", running: "Выполняется", completed: "Завершён", failed: "Ошибка" };
function scoreLabel(value: number) { return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "Нет оценки"; }
function moscowTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : `${new Intl.DateTimeFormat("ru-RU", {dateStyle:"short", timeStyle:"short", timeZone:"Europe/Moscow"}).format(date)} МСК`;
}
function boundary(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value.split("-").reverse().join(".")} 00:00` : moscowTime(value).replace(/ МСК$/, "");
}
function forecastWindow(row: Prediction) {
  return row.ml_metadata ? `${boundary(row.ml_metadata.window_start)} — ${boundary(row.ml_metadata.window_end_exclusive)} МСК (конец не включается)` : `${row.horizon_hours} ч`;
}
export default function PredictionsPage() {
  const isMobile = useMediaQuery("(max-width: 800px)");
  const detailPanel = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [params, setParams] = useSearchParams();
  const [detailVersion, setDetailVersion] = useState(0);
  const [detailLoading, setDetailLoading] = useState(false);
  const [feedback, setFeedback] = useState("");
  const lastDetailId = useRef<number | null>(null);
  const [loading, setLoading] = useState(true);
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
  useEffect(() => {
    if (isMobile && selected) {
      detailPanel.current?.scrollIntoView({block:"start"});
      detailPanel.current?.focus({preventScroll:true});
    }
  }, [isMobile, selected]);
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
  useEffect(() => { void refresh().catch(e => setError(e.message)).finally(() => setLoading(false)); }, []);
  useEffect(() => {
    const id=Number(params.get("predictionId"));
    setSelected(null); setHistory([]);
    if (lastDetailId.current!==id) setFeedback("");
    lastDetailId.current=id;
    if (!Number.isSafeInteger(id) || id<=0) { setDetailLoading(false); return; }
    const controller=new AbortController();
    setDetailLoading(true); setError("");
    jsonRequest<Prediction & { decisions: Decision[] }>(`/api/v1/predictions/${id}`,{signal:controller.signal})
      .then(detail=>{
        if (controller.signal.aborted) return;
        setSelected(detail); setHistory(detail.decisions); setNotes(""); setOutcome(detail.actual_outcome ?? "");
        setDecision(["monitoring","confirmed","false_alarm","dispatch","closed"].includes(detail.status) ? detail.status : "monitoring");
      })
      .catch(e=>{if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Не удалось загрузить прогноз");})
      .finally(()=>{if (!controller.signal.aborted) setDetailLoading(false);});
    return ()=>controller.abort();
  },[params,detailVersion]);
  function select(row: Pick<Prediction,"id">) {
    setParams(current=>{const next=new URLSearchParams(current);next.set("predictionId",String(row.id));return next;});
  }
  async function save() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      await jsonRequest<Prediction>(`/api/v1/predictions/${selected.id}/decision`, {
        method: "PATCH", body: JSON.stringify({ revision: selected.revision, decision, reason, notes, actual_outcome: outcome || null }),
      });
      await refresh(); setDetailVersion(v=>v+1); setFeedback(`Решение по прогнозу №${selected.id} сохранено`);
    } catch (e) { setError(e instanceof Error ? e.message : "Ошибка сохранения"); }
    finally { setBusy(false); }
  }
  async function createRequest() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      await jsonRequest(`/api/v1/predictions/${selected.id}/request`, { method: "POST" });
      await refresh(); setDetailVersion(v=>v+1);
    } catch (e) { setError(e instanceof Error ? e.message : "Ошибка создания заявки"); }
    finally { setBusy(false); }
  }
  return <section className="operations-page predictions-page"><h1 ref={heading} tabIndex={-1}>Журнал прогнозов</h1><p className="status-notice">{message}</p>
    {error && <p role="alert">{error} <button onClick={() => { setError(""); setLoading(true); void refresh().catch(e => setError(e.message)).finally(() => setLoading(false)); }}>Повторить загрузку</button></p>}
    {loading && <p role="status">Загрузка прогнозов…</p>}
    {detailLoading && <p role="status">Загрузка прогноза…</p>}
    {feedback && <p role="status">{feedback}</p>}
    <details><summary>Журнал суточных расчётов</summary>{runs.length ? runs.map(run => <p key={run.id}>{run.as_of_date} · ревизия {run.revision} · {STATUS_LABELS[run.state] ?? run.state}{run.error_code ? ` · ${run.error_code}` : ""}</p>) : <p>Запусков пока нет. Нужны проверенные исходные данные и отметка завершения суток.</p>}</details>
    {!loading && !error && !rows.length && <p>Прогнозов нет. Текущие срабатывания доступны в разделе «Тревоги».</p>}
    {rows.length > 0 && <div className="prediction-table-wrap"><table><thead><tr><th>Объект</th><th>Тип</th><th>Оценка (proxy)</th><th>Окно прогноза</th><th>Статус</th><th>Просмотр</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.id}><td>{row.object_id}</td><td>{TYPE_LABELS[row.incident_type] ?? row.incident_type}</td><td>{scoreLabel(row.probability)}</td>
        <td>{forecastWindow(row)}</td><td>{STATUS_LABELS[row.status] ?? row.status}</td><td><button disabled={busy} onClick={() => select(row)}>Открыть</button></td></tr>)}</tbody></table></div>}
    {rows.length > 0 && <div className="prediction-mobile-list" aria-label="Прогнозы по объектам">
      {rows.map(row => <article className="prediction-mobile-card" key={row.id}>
        <h2>Объект №{row.object_id}</h2>
        <dl>
          {row.channel_id != null && <div><dt>Канал</dt><dd>№{row.channel_id}</dd></div>}
          <div><dt>Тип прогноза</dt><dd>{TYPE_LABELS[row.incident_type] ?? row.incident_type}</dd></div>
          <div><dt>Оценка (proxy)</dt><dd className="prediction-score">{scoreLabel(row.probability)}</dd></div>
          <div><dt>Окно прогноза</dt><dd>{forecastWindow(row)}</dd></div>
          <div><dt>Статус</dt><dd>{STATUS_LABELS[row.status] ?? row.status}</dd></div>
          {row.ml_metadata && <div><dt>Данные на конец суток</dt><dd>{row.ml_metadata.as_of_date}</dd></div>}
          <div><dt>Рассчитано</dt><dd>{moscowTime(row.calculated_at)}</dd></div>
        </dl>
        <button disabled={busy} onClick={() => select(row)}>Открыть</button>
      </article>)}
    </div>}
    {hasMore && <button disabled={busy} onClick={loadMore}>Загрузить ещё прогнозы</button>}
    {selected && <article className="prediction-detail" ref={detailPanel} tabIndex={-1}><header className="prediction-heading"><h2>Прогноз №{selected.id}</h2>
      <button disabled={busy} onClick={()=>{
        setParams(current=>{const next=new URLSearchParams(current);next.delete("predictionId");return next;});
        if (isMobile) { heading.current?.scrollIntoView({block:"start"}); heading.current?.focus({preventScroll:true}); }
      }}>Закрыть прогноз</button>
      </header>
      <section className="prediction-card" aria-label="Сводка прогноза"><h3>Сохранённая оценка</h3><dl className="prediction-summary">
        <div><dt>Объект</dt><dd>№{selected.object_id}</dd></div>
        <div><dt>Оценка (proxy)</dt><dd>{scoreLabel(selected.probability)}</dd></div>
        <div><dt>Горизонт</dt><dd>{selected.horizon_hours} ч</dd></div>
        <div><dt>Тип</dt><dd>{TYPE_LABELS[selected.incident_type] ?? selected.incident_type}</dd></div>
      </dl><p>Shadow/proxy оценка не является подтверждённой вероятностью реального инцидента.</p></section>
      <section className="prediction-card"><h3>Контекст расчёта</h3>
      <p>Модель: {selected.model_version} · Расчёт: {moscowTime(selected.calculated_at)}</p>
      {selected.ml_metadata && <p>Данные на {selected.ml_metadata.as_of_date} · ревизия {selected.ml_metadata.revision} · {selected.ml_metadata.evidence_level}. Контекст: {selected.ml_metadata.maintenance_context === "possible_recent_silence" ? "Возможно, после ТО/поверки; требуется проверка журнала работ" : selected.ml_metadata.maintenance_context === "verified_schedule" ? "Подтверждённое окно ППР" : "Сведения о ТО отсутствуют"}. Горизонт {selected.horizon_hours} ч отсчитывается от завершения суток данных. Автоматические действия отключены.</p>}
      </section><section className="prediction-card"><h3>Рекомендация для проверки</h3>
      <p>{selected.recommendation ?? "Рекомендация не предоставлена моделью"}</p>
      {selected.request_id ? <Link to={`/requests?requestId=${selected.request_id}`}>Открыть заявку · №{selected.request_id}</Link> :
        <button disabled={busy || !canWrite("predictions") || !selected.recommendation || ["closed", "false_alarm"].includes(selected.status)} onClick={createRequest}>Создать черновик заявки</button>}
      {!selected.request_id && (!canWrite("predictions") || !selected.recommendation || ["closed","false_alarm"].includes(selected.status)) && <p className="prediction-hint">
        {!canWrite("predictions") ? "Создание черновика доступно диспетчеру, аналитику или администратору." : !selected.recommendation ? "Без рекомендации создать связанный черновик нельзя." : "Для закрытого или ложного прогноза создание черновика недоступно."}
      </p>}</section>
      {selected.status === "closed" && <p className="prediction-hint">Прогноз закрыт: изменение решения недоступно.</p>}
      <fieldset disabled={busy || !canWrite("predictions") || selected.status === "closed"}><legend>Решение диспетчера</legend>
        <label>Действие<select value={decision} onChange={e => setDecision(e.target.value)}>
          <option value="monitoring">Мониторинг</option><option value="confirmed">Подтверждено</option><option value="false_alarm">Ложное срабатывание</option>
          <option value="dispatch">Выезд бригады</option><option value="closed">Закрыть</option></select></label>
        <label>Причина<select value={reason} onChange={e => setReason(e.target.value)}>{Object.entries(reasons).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>
        <label>Комментарий<textarea maxLength={4000} value={notes} onChange={e => setNotes(e.target.value)} /></label>
        <label>Фактический исход<textarea maxLength={4000} value={outcome} onChange={e => setOutcome(e.target.value)} /></label>
        <button onClick={save}>Сохранить решение</button>
      </fieldset><section className="prediction-card"><h3>История решений</h3>{history.length ? history.map((entry, index) => <p key={index}>{moscowTime(entry.created_at)} · {entry.actor} · {STATUS_LABELS[entry.decision] ?? entry.decision} · {reasons[entry.reason] ?? entry.reason} · {entry.notes} · {entry.actual_outcome}</p>) : <p>Решений пока нет.</p>}</section>
    </article>}
  </section>;
}
