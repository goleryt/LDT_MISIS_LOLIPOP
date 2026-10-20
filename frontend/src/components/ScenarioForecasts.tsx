import {useEffect,useRef,useState} from 'react';
import {Link,useSearchParams} from 'react-router-dom';
import {canWrite,jsonRequest} from '../api/session';

type Worker='sensor_failure'|'fire';
type Payload={ref:string;worker:Worker;object:string|null;channel:string|null;eligible:boolean;warning:boolean;
  score:number|null;threshold:number|null;cutoff:string;issued_at:string;window_start:string;window_end_exclusive:string;
  model_version:string;evidence_level:string;score_kind:string;label_source:string;reason:string|string[]|null};
type Forecast={id:number;run_id:number;worker:Worker;object_id:number|null;channel_id:number|null;payload:Payload;
  attention:boolean;status:string;revision:number;request_id:number|null;
  decisions:{actor:string;role:string;created_at:string;decision:string;notes:string}[]};
type Recommendation={code:string;text_ru:string;forecast_refs:string[];recommendation_source:string};
type Run={id:number;as_of_date:string;revision:number;snapshot_version:string;state:string;error_code:string|null;
  workers:Record<string,{status:string;reason?:string}>;worker_errors:Record<string,string>;
  recommendations:Recommendation[];rule_version:string;finished_at:string|null};
type Data={configuration:{enabled:boolean;fire:boolean;sensor_failure:boolean};run:Run|null;runs:Run[];
  forecasts:Forecast[];has_more:boolean};
const LABELS:Record<Worker,string>={sensor_failure:'Сценарный прогноз отказа датчика',fire:'Экспериментальный сценарный прогноз пожара'};
const DECISIONS:Record<string,string>={monitoring:'Мониторинг',reviewed:'Проверено вручную',dismissed:'Отклонено',new:'Без решения'};
const REASONS:Record<string,string>={INSUFFICIENT_HISTORY:'Недостаточный охват истории (нужно 33 суток)',
  NO_RECENT_OBSERVATIONS:'Нет свежих наблюдений',NO_RELEVANT_CHANNEL:'Нет подходящего канала',
  UNBOUND_CHANNEL:'Привязка канала к объекту не подтверждена',BINDING_UNAVAILABLE:'Проверьте справочник привязок',
  WORKER_UNAVAILABLE:'Нет результата расчёта',MODULE_DISABLED:'Модуль отключён',
  UNSUPPORTED_MODEL_VERSION:'Неподдерживаемая версия модели',EVIDENCE_CUTOFF_MISMATCH:'Разные даты данных',
  EVIDENCE_ISSUE_TIME_INVALID:'Некорректное время выпуска',STALE_FORECAST:'Прогнозное окно уже началось',
  LATE_RUN:'Недостаточное опережение для нового расчёта',SCENARIO_RUNTIME_TIMEOUT:'Превышено время расчёта',
  SCENARIO_RUNTIME_UNAVAILABLE:'Среда расчёта недоступна',SCENARIO_RUNTIME_FAILED:'Ошибка среды расчёта'};
function reason(value:string|string[]|null|undefined):string {
  if(Array.isArray(value))return value.map(v=>reason(v)).join('; ');
  return value ? REASONS[value] ?? `Результат недоступен: ${value}` : 'Нет результата расчёта';
}
function time(value:string):string {
  const date=new Date(value);
  return Number.isFinite(date.getTime())?new Intl.DateTimeFormat('ru-RU',{dateStyle:'short',timeStyle:'short',timeZone:'Europe/Moscow'}).format(date)+' МСК':'Время не предоставлено';
}
export default function ScenarioForecasts(){
  const [params,setParams]=useSearchParams();
  const [result,setResult]=useState<{key:string;data:Data|null;error:string}>({key:'',data:null,error:''});
  const [clock,setClock]=useState(()=>Date.now());
  const [version,setVersion]=useState(0);
  const runId=params.get('scenarioRun');
  const filter=params.get('scenarioType')??'all';
  const key=JSON.stringify([runId,filter,version]);
  const loading=result.key!==key,data=result.data,error=loading?'':result.error;
  useEffect(()=>{const timer=setInterval(()=>setClock(Date.now()),60000);return()=>clearInterval(timer);},[]);
  useEffect(()=>{
    const controller=new AbortController();
    const query=new URLSearchParams();if(runId)query.set('run_id',runId);
    if(filter==='fire'||filter==='sensor_failure')query.set('worker',filter);
    jsonRequest<Data>(`/api/v1/predictions/scenarios?${query}`,{signal:controller.signal})
      .then(data=>{if(!controller.signal.aborted)setResult({key,data,error:''});})
      .catch(e=>{if(!controller.signal.aborted)setResult(previous=>({key,data:previous.data,error:e.message}));});
    return()=>controller.abort();
  },[runId,filter,key]);
  return <section className="scenario-section" aria-label="Экспериментальные сценарии">
    <h2>Экспериментальные сценарии</h2>
    <p>Отдельные оценки на искусственных сценариях. Это не подтверждённые вероятности аварий и не независимые подтверждения друг друга. Автоматические действия отключены.</p>
    {loading&&<p role="status">Загрузка сценарных прогнозов…</p>}
    {error&&<p role="alert">{error} <button onClick={()=>setVersion(v=>v+1)}>Повторить загрузку сценариев</button></p>}
    {data&&<>
      <div className="scenario-controls">
        <label>Тип сценария <select value={filter} onChange={e=>setParams(p=>{const n=new URLSearchParams(p);n.set('scenarioType',e.target.value);return n;})}>
          <option value="all">Все типы</option><option value="sensor_failure">Отказ датчика</option><option value="fire">Пожар</option>
        </select></label>
        {data.runs.length>0&&<label>Снимок расчёта <select value={runId??String(data.run?.id??'')} onChange={e=>setParams(p=>{const n=new URLSearchParams(p);n.set('scenarioRun',e.target.value);return n;})}>
          {data.runs.map(r=><option key={r.id} value={r.id}>{r.as_of_date} · ревизия {r.revision} · {r.snapshot_version}</option>)}
        </select></label>}
      </div>
      {data.run&&<p>Данные по {data.run.as_of_date} включительно · снимок {data.run.snapshot_version} · ревизия {data.run.revision}.
        {data.run.state==='partial'?' Контекст неполный.':''}{data.run.state==='failed'?` Расчёт недоступен: ${reason(data.run.error_code)}`:''}</p>}
      <div className="scenario-grid">{(['sensor_failure','fire'] as Worker[]).filter(w=>filter==='all'||filter===w).map(worker=>{
        const rows=data.configuration[worker]?data.forecasts.filter(r=>r.worker===worker):[];
        return <section key={worker} aria-label={LABELS[worker]} className="scenario-group"><h3>{worker==='sensor_failure'?'Техническая проверка датчиков':'Проверка пожарных признаков'}</h3>
          {rows.length?rows.map(row=><ScenarioCard key={row.id} row={row} run={data.run} now={clock} refresh={()=>setVersion(v=>v+1)}/>):
            <article className="scenario-forecast-card"><h4>{LABELS[worker]}</h4><span className="scenario-badge">{worker==='fire'?'Экспериментально · синтетическая проверка':'Синтетическая оценка'}</span>
              <p>— · {data.configuration[worker]?'Прогноз недоступен':'Модуль отключён'}</p>
              <p>{data.configuration[worker]?reason(data.run?.worker_errors[worker]??data.run?.workers[worker]?.reason):'Экспериментальный модуль выключен административной конфигурацией.'}</p>
            </article>}
        </section>;
      })}</div>
      {data.has_more&&<p>Показаны первые 100 записей снимка. Выберите тип сценария для уточнения списка.</p>}
    </>}
    <details className="scenario-quality"><summary>Доказательства и ограничения качества</summary>
      <p>Ограниченная синтетическая проверка 19 объектов. Отказ датчика: Precision 56,3%, Recall 30,1%, Coverage 50,2%. Fire: 18,2%, 13,3%, 57,9%. В overlap-сценарии не обнаружены 30 из 30 искусственных отказов датчиков.</p>
      <p>Технический запуск не доказывает точность на реальных инцидентах. Flood, Intrusion и System Failure не активированы. Общая вероятность инцидента не рассчитывается.</p>
    </details>
  </section>;
}

function ScenarioCard({row,run,now,refresh}:{row:Forecast;run:Run|null;now:number;refresh:()=>void}){
  const p=row.payload;const [params,setParams]=useSearchParams();const panel=useRef<HTMLElement>(null);
  const [notes,setNotes]=useState(''),[decision,setDecision]=useState('monitoring'),[busy,setBusy]=useState(false),[error,setError]=useState(''),[feedback,setFeedback]=useState('');
  const focused=params.get('scenarioId')===String(row.id);
  useEffect(()=>{if(focused){panel.current?.scrollIntoView({block:'start'});panel.current?.focus({preventScroll:true});}},[focused]);
  const recs=run?.recommendations.filter(r=>r.forecast_refs.includes(p.ref))??[];
  const available=p.eligible&&typeof p.score==='number'&&Number.isFinite(p.score);
  const stale=Date.parse(p.window_start)<=now;
  async function act(kind:'decision'|'request'){
    setBusy(true);setError('');setFeedback('');
    try{
      await jsonRequest(`/api/v1/predictions/scenarios/${row.id}/${kind}`,kind==='request'?{method:'POST'}:
        {method:'PATCH',body:JSON.stringify({revision:row.revision,decision,notes})});
      setFeedback(kind==='request'?'Черновик заявки создан. Подтвердите его отдельно.':'Решение сохранено');refresh();
    }catch(e){setError(e instanceof Error?e.message:'Не удалось сохранить действие');}
    finally{setBusy(false);}
  }
  return <article className="scenario-forecast-card" ref={panel} tabIndex={-1} aria-label={`${LABELS[row.worker]} №${row.id}`}>
    <h4>{LABELS[row.worker]}</h4><span className="scenario-badge">{row.worker==='fire'?'Экспериментально · синтетическая проверка':'Синтетическая оценка'}</span>
    <p>{row.object_id?<Link to={`/?mapMode=forecasts&objectId=${row.object_id}${row.channel_id?`&channelId=${row.channel_id}`:''}`}>Объект №{row.object_id}{row.channel_id?` · канал №${row.channel_id}`:''}</Link>:'Привязка к объекту/каналу не подтверждена'}</p>
    <p className="scenario-score">Сценарная оценка: {available?p.score!.toLocaleString('ru-RU',{minimumFractionDigits:3,maximumFractionDigits:3}):'—'}</p>
    <p>{!available?'Прогноз недоступен':p.warning?'Рекомендуется ручная проверка':'Порог сценарного предупреждения не превышен'}</p>
    <p>Обработка: {DECISIONS[row.status]??row.status}{p.warning&&!row.attention?' · Повтор в пределах трёхдневного периода внимания; результат сохранён.':''}</p>
    {!available&&<p>{reason(p.reason)}</p>}
    <p>Окно: {time(p.window_start)} — {time(p.window_end_exclusive)} (конец не включается).</p>
    {stale&&<p className="scenario-historical">Исторический результат: прогнозное окно уже началось. Не является актуальным предупреждением.</p>}
    <p>Данные по {p.cutoff} включительно · Рассчитано: {time(p.issued_at)}</p>
    <details open={focused} onToggle={e=>{
      const open=e.currentTarget.open;
      if(open!==focused)setParams(old=>{const n=new URLSearchParams(old);if(open)n.set('scenarioId',String(row.id));else n.delete('scenarioId');return n;},{replace:true});
    }}>
      <summary>Подробности сценарной оценки</summary>
      <p>Версия модели: {p.model_version}. Уровень доказательств: {p.evidence_level}. Источник: {p.label_source}. Тип: {p.score_kind}.</p>
      <p>Полная оценка: {available?String(p.score):'—'} · Замороженный порог: {p.threshold?.toFixed(6)??'—'}</p>
      {recs.map((r,i)=><div key={`${r.code}-${i}`}><p>{r.text_ru}</p><small>Рекомендация по заданному правилу · {r.recommendation_source} · {run?.rule_version}</small></div>)}
      {!recs.length&&<p>Предупреждающей рекомендации по заданному правилу нет. Это не подтверждает исправность или безопасность.</p>}
      {row.decisions.map((d,i)=><p key={i}>{time(d.created_at)} · {d.actor} · {DECISIONS[d.decision]??d.decision} · {d.notes}</p>)}
      {canWrite('predictions')&&<fieldset disabled={busy}><legend>Ручная проверка</legend>
        <label>Решение <select value={decision} onChange={e=>setDecision(e.target.value)}><option value="monitoring">Мониторинг</option><option value="reviewed">Проверено вручную</option><option value="dismissed">Отклонено</option></select></label>
        <label>Комментарий проверки <textarea maxLength={4000} value={notes} onChange={e=>setNotes(e.target.value)}/></label>
        {!notes.trim()&&<p>Для сохранения решения заполните комментарий проверки.</p>}
        <button disabled={!notes.trim()||busy} onClick={()=>void act('decision')}>Сохранить ручную проверку</button>
        {row.request_id?<Link to={`/requests?requestId=${row.request_id}`}>Открыть черновик / заявку №{row.request_id}</Link>:
          <button disabled={!available||busy||row.status==='dismissed'} onClick={()=>void act('request')}>Создать отдельный черновик заявки</button>}
        {!available&&<p>Черновик недоступен: нет пригодного результата с подтверждённой привязкой.</p>}
      </fieldset>}
      {!canWrite('predictions')&&<p>Режим только чтения. Ручная проверка и создание черновика доступны диспетчеру, аналитику или администратору.</p>}
      {!canWrite('predictions')&&row.request_id&&<Link to={`/requests?requestId=${row.request_id}`}>Открыть связанную заявку №{row.request_id}</Link>}
    </details>
    {error&&<p role="alert">{error}</p>}{feedback&&<p role="status">{feedback}</p>}
  </article>;
}
