import { useEffect, useState } from "react";
import { getSession, jsonRequest } from "../api/session";
import { updateRequest } from "../api/requests";
import type { PreventiveRequest, RequestPriority } from "../types/requests";

type Change = { id: number; actor: string; from_status: string | null; to_status: string; created_at: string; changed_fields: string[] };
const states: Record<string, string> = { draft: "Черновик", new: "Новая", in_progress: "В работе", completed: "Выполнена", cancelled: "Отменена" };
export default function RequestReview({ item, onSaved, onClose }: {
  item: PreventiveRequest; onSaved: (item: PreventiveRequest) => void; onClose: () => void;
}) {
  const [title, setTitle] = useState(item.title);
  const [description, setDescription] = useState(item.description ?? "");
  const [priority, setPriority] = useState(item.priority);
  const [history, setHistory] = useState<Change[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const canReview = item.status === "draft" && ["admin", "dispatcher"].includes(getSession()?.role ?? "");
  useEffect(() => {
    let active = true;
    jsonRequest<Change[]>(`/api/v1/requests/${item.id}/history`).then(rows => { if (active) setHistory(rows); })
      .catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [item]);
  async function save(confirm: boolean) {
    setBusy(true); setError("");
    try { onSaved(await updateRequest(item.id, { title: title.trim(), description: description.trim() || null, priority, ...(item.updated_at ? { expected_updated_at: item.updated_at } : {}), ...(confirm ? { status: "new" } : {}) })); }
    catch (e) { setError(e instanceof Error ? e.message : "Не удалось сохранить черновик"); }
    finally { setBusy(false); }
  }
  return <section className="requests-panel request-review" aria-label={`Проверка заявки ${item.id}`}>
    <h2>{item.status === "draft" ? "Черновик заявки" : "История заявки"} №{item.id}</h2>
    {item.status === "draft" && <p>Проверьте тему, описание и приоритет. Подтверждение переводит черновик в новую заявку.</p>}
    {error && <p role="alert">{error}</p>}
    {item.status === "draft" && <fieldset disabled={!canReview || busy}>
      <label>Тема черновика<input value={title} maxLength={200} onChange={e => setTitle(e.target.value)} /></label>
      <label>Описание черновика<textarea value={description} maxLength={4000} onChange={e => setDescription(e.target.value)} /></label>
      <label>Приоритет черновика<select value={priority} onChange={e => setPriority(e.target.value as RequestPriority)}>
        <option value="low">Низкий</option><option value="medium">Средний</option><option value="high">Высокий</option><option value="critical">Критический</option>
      </select></label>
      <button className="requests-secondary-button" disabled={!title.trim()} onClick={() => void save(false)}>Сохранить черновик</button>
      <button className="requests-primary-button" disabled={!title.trim()} onClick={() => void save(true)}>Подтвердить заявку</button>
    </fieldset>}
    <h3>История изменений</h3>
    {loading ? <p role="status">Загрузка истории…</p> : history.length ? history.map(row => <p key={row.id}>
      {new Date(row.created_at).toLocaleString("ru-RU")} · {row.actor} · {states[row.from_status ?? ""] ?? "Создание"} → {states[row.to_status] ?? row.to_status}
    </p>) : <p>Записей об изменениях нет. История ведётся с обновления октября 2026.</p>}
    <button className="requests-secondary-button" onClick={onClose}>Закрыть просмотр заявки</button>
  </section>;
}
