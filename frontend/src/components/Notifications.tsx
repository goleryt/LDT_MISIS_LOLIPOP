import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { jsonRequest } from "../api/session";
type Notice = { id: number; message: string; kind: string; reference_id: number | null; object_id: number | null; channel_id?: number | null; created_at?: string };
export default function Notifications() {
  const [items, setItems] = useState<Notice[]>([]);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const readIds = useRef(new Set<number>());
  const pending = useRef(new Set<number>());
  const [reading, setReading] = useState(new Set<number>());
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const data = await jsonRequest<Notice[]>("/api/v1/notifications?limit=20");
        if (!stopped) { setItems(data.filter(item => !readIds.current.has(item.id))); setFailed(false); }
      } catch { if (!stopped) setFailed(true); }
      finally { if (!stopped) setLoading(false); }
      if (!stopped) timer = setTimeout(poll, 15000);
    }
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, []);
  async function markRead(id: number) {
    if (pending.current.has(id)) return;
    pending.current.add(id); setReading(new Set(pending.current));
    try {
      await jsonRequest(`/api/v1/notifications/${id}/read`, { method: "POST" });
      readIds.current.add(id);
      setItems(value => value.filter(item => item.id !== id));
    } catch { setFailed(true); }
    finally { pending.current.delete(id); setReading(new Set(pending.current)); }
  }
  return <aside className="notification-panel" aria-label="Уведомления">
    <details><summary>Уведомления: {loading ? "загрузка…" : items.length}{failed ? " · связь потеряна" : ""}</summary>
      {!loading && !items.length && !failed && <p>Непрочитанных уведомлений нет.</p>}
      {items.map(item => <div key={item.id}><Link to={item.kind === "prediction" ? `/predictions?predictionId=${item.reference_id}` : item.object_id ? `/?objectId=${item.object_id}${item.channel_id ? `&channelId=${item.channel_id}` : ""}` : "/events"}>{item.message}</Link>
        {item.created_at && Number.isFinite(Date.parse(item.created_at)) && <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString("ru-RU")}</time>}
        <button disabled={reading.has(item.id)} onClick={() => markRead(item.id)} aria-label={`Прочитано: ${item.message}`}>{reading.has(item.id) ? "Сохранение…" : "Прочитано"}</button></div>)}
    </details>
  </aside>;
}
