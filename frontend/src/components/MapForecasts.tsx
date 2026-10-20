import {useEffect, useState} from 'react';
import {FORECAST_LABELS,FORECAST_SYMBOLS} from '../api/mapForecasts';
import type {MapForecast,ForecastKind,ForecastData} from '../api/mapForecasts';
import {Link} from 'react-router-dom';
import type {MapObject} from '../types/map';
import '../styles/map-forecasts.css';


function time(value:string|null) {
  if(!value)return 'Не предоставлено';
  // Date-only model boundaries are midnight Moscow, never browser-local midnight.
  const date=new Date(value.length===10?`${value}T00:00:00+03:00`:value);
  return Number.isFinite(date.getTime())?new Intl.DateTimeFormat('ru-RU',{dateStyle:'short',timeStyle:'short',timeZone:'Europe/Moscow'}).format(date):'Не предоставлено';
}

function count(value:number, forms:[string,string,string]) {
  const form=new Intl.PluralRules('ru-RU').select(value);
  return `${value} ${forms[form==='one'?0:form==='few'?1:2]}`;
}

export function ObjectForecasts({rows}:{rows:MapForecast[]}) {
  const [now,setNow]=useState(()=>Date.now());
  useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),60000);return()=>clearInterval(timer);},[]);
  return <section className="object-forecasts" aria-label="Сохранённые прогнозы объекта">
    <h3>Сохранённые прогнозы</h3>
    <p>Отдельные оценки моделей. Общая вероятность аварии не рассчитывается.</p>
    {!rows.length&&<p>У объекта нет результатов в доступном снимке. Это не означает нулевой риск.</p>}
    {rows.map(row=><article className={`map-forecast-card ${row.worker}`} key={row.key} aria-label={FORECAST_LABELS[row.worker]}>
      <h4><span aria-hidden="true">{FORECAST_SYMBOLS[row.worker]}</span> {FORECAST_LABELS[row.worker]}</h4>
      <p className="map-forecast-score">{row.worker==='gas'?'Proxy-оценка':'Сценарная оценка'}: {row.available&&row.score!==null?row.score.toLocaleString('ru-RU',{maximumSignificantDigits:7}):'— · Недостаточно данных / результат недоступен'}</p>
      <p>{row.source}. Требуется проверка специалистом.</p>
      {row.available&&<p>{row.worker==='gas'?(row.queue_selected?'Выбран в газовую очередь проверки':'Вне газовой очереди Top-K / cooldown'):(row.warning?'Превышен сценарный порог ручной проверки':'Порог сценарного предупреждения не превышен')}</p>}
      {!row.bound&&<p>Привязка не подтверждена. Результат не размещён на карте.</p>}
      <p>Окно: {time(row.window_start)} — {time(row.window_end_exclusive)} МСК, конец не включается.</p>
      {row.window_start&&Date.parse(row.window_start.length===10?`${row.window_start}T00:00:00+03:00`:row.window_start)<=now&&<p>Исторический результат: окно уже началось. Это не актуальное предупреждение.</p>}
      <p>Данные по {row.cutoff??'неизвестную дату'} · Рассчитано {time(row.issued_at)} МСК</p>
      <details><summary>Версия, источник и рекомендации</summary><p>Модель: {row.model_version??'не предоставлена'} · Снимок: {row.snapshot_version}</p>
        {!row.available&&<p>Причина в контракте: {Array.isArray(row.reason)?row.reason.join(', '):row.reason??'результат недоступен'}</p>}
        {row.recommendations.map((text,i)=><p key={i}>{text}</p>)}
        {!row.recommendations.length&&<p>Предупреждающей рекомендации по правилу нет. Допустима ручная проверка; исправность не подтверждена.</p>}
      </details>
      <Link to={row.detail_url}>{row.worker==='gas'&&row.detail_url==='/predictions'?'Журнал выбранных газовых прогнозов':'Детали, решение и черновик заявки'}</Link>
      {row.worker==='gas'&&row.detail_url==='/predictions'&&<p>Этот результат не имеет отдельной рабочей карточки в газовой очереди. Параметры очереди не изменялись.</p>}
      {row.bound&&row.channel_id!==null&&<Link to={`/?mapMode=forecasts&objectId=${row.object_id}&channelId=${row.channel_id}`}>Открыть канал №{row.channel_id}</Link>}
    </article>)}
  </section>;
}

export function MapForecastControls({data,loading,error,retry,kind,availability,window,change,onSelect,objects,filtered}: {
  data:ForecastData|null;loading:boolean;error:string;retry:()=>void;kind:string;availability:string;window:string;
  change:(key:string,value:string)=>void;onSelect:(object:MapObject)=>void;objects:MapObject[];filtered:MapForecast[];
}) {
  const windows=[...new Set(data?.forecasts.map(r=>r.window_start).filter((v):v is string=>!!v))];
  const objectIds=[...new Set(filtered.filter(r=>r.bound).map(r=>r.object_id))];
  const unbound=filtered.filter(r=>!r.bound);
  return <section className="map-forecast-controls" aria-label="Фильтры прогнозов карты">
    <p>Схематическое расположение · сохранённые результаты · G: газовый proxy · S: отказ датчика · F: Fire v4. Сценарии не являются подтверждёнными вероятностями аварий.</p>
    <label>Модель <select aria-label="Модель" value={kind} onChange={e=>change('forecastType',e.target.value)}>
      <option value="all">Все прогнозы</option><option value="gas">Газ</option><option value="sensor_failure">Отказ датчика</option><option value="fire">Пожар</option><option value="multiple">Несколько моделей</option>
    </select></label>
    <label>Доступность <select aria-label="Доступность" value={availability} onChange={e=>change('forecastAvailability',e.target.value)}>
      <option value="all">Все результаты</option><option value="available">Доступные</option><option value="unavailable">Недоступные / abstain</option>
    </select></label>
    {windows.length>0&&<label>Начало окна <select aria-label="Начало окна" value={window} onChange={e=>change('forecastWindow',e.target.value)}><option value="all">Все даты</option>{windows.map(w=><option key={w} value={w}>{time(w)} МСК</option>)}</select></label>}
    {loading&&<p role="status">Загрузка прогнозов…</p>}
    {error&&<p role="alert">{error} <button onClick={retry}>Повторить загрузку прогнозов</button></p>}
    {data&&!loading&&!error&&<>
      <p>{count(filtered.length,['результат','результата','результатов'])} · {count(objectIds.length,['объект','объекта','объектов'])}. Низкие оценки также показаны. Цвет фактической тревоги в этом режиме не используется.</p>
      {(['gas','sensor_failure','fire'] as ForecastKind[]).filter(w=>!data.forecasts.some(r=>r.worker===w)).map(w=><p key={w}>{FORECAST_LABELS[w]}: нет сохранённого результата{w!=='gas'&&!data.configuration[w]?' · модуль отключён':''}.</p>)}
      {data.scenario_run&&data.scenario_run.state!=='completed'&&<p>Последний сценарный расчёт неполон или не завершён. Ранее успешный снимок не подставляется автоматически.</p>}
      {!filtered.length&&<p>По выбранным фильтрам результатов нет. Это не означает отсутствие риска.</p>}
      <div className="map-forecast-object-links">{objectIds.map(id=>{const obj=objects.find(o=>o.object_id===id);return obj?<button key={id} onClick={()=>onSelect(obj)}>{obj.name??`Объект №${id}`} · {[...new Set(filtered.filter(r=>r.object_id===id).map(r=>FORECAST_SYMBOLS[r.worker]))].join(' / ')}</button>:null;})}</div>
      {!!unbound.length&&<details><summary>Не размещены на карте: {unbound.length}</summary><ObjectForecasts rows={unbound}/></details>}
      {data.truncated&&<p>Показаны первые 500 записей каждого контура. Полная история доступна в журнале прогнозов.</p>}
    </>}
  </section>;
}
