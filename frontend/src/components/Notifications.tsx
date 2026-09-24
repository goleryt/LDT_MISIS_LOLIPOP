import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { jsonRequest } from "../api/session";
type Notice = { id: number; message: string; kind: string; reference_id: number | null; object_id: number | null };
export default function Notifications() {
  const [items, setItems] = useState<Notice[]>([]);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const data = await jsonRequest<Notice[]>("/api/v1/notifications?limit=20");
        if (!stopped) { setItems(data); setFailed(false); }
      } catch { if (!stopped) setFailed(true); }
      if (!stopped) timer = setTimeout(poll, 15000);
    }
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, []);
  async function markRead(id: number) {
    try {
      await jsonRequest(`/api/v1/notifications/${id}/read`, { method: "POST" });
      setItems(value => value.filter(item => item.id !== id));
    } catch { setFailed(true); }
  }
  if (!items.length && !failed) return null;
  return <aside className="notification-panel" aria-label="Уведомления">
    <details><summary>Уведомления: {items.length}{failed ? " · связь потеряна" : ""}</summary>
      {items.map(item => <div key={item.id}><Link to={item.kind === "prediction" ? "/predictions" : "/alarms"}>{item.message}</Link>
        <button onClick={() => markRead(item.id)} aria-label={`Прочитано: ${item.message}`}>Прочитано</button></div>)}
    </details>
  </aside>;
}
