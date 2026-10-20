import {useEffect,useState} from 'react';
import {jsonRequest} from './session';
export type ForecastKind = 'gas' | 'sensor_failure' | 'fire';
export type MapForecast = {
  key:string; worker:ForecastKind; object_id:number|null; channel_id:number|null;
  bound:boolean; available:boolean; score:number|null; score_kind:string|null;
  warning:boolean|null; queue_selected?:boolean; reason:string|string[]|null;
  cutoff:string|null; issued_at:string|null; window_start:string|null; window_end_exclusive:string|null;
  model_version:string|null; source:string; snapshot_version:string; detail_url:string; recommendations:string[];
};
export type ForecastData = {forecasts:MapForecast[]; truncated:boolean;
  scenario_run:{id:number;state:string;error_code:string|null}|null;
  configuration:{enabled:boolean;fire:boolean;sensor_failure:boolean}};
export const FORECAST_LABELS:Record<ForecastKind,string> = {gas:'Газ G2 v3 · shadow',sensor_failure:'Отказ датчика · сценарий',fire:'Fire v4 · сценарий'};
export const FORECAST_SYMBOLS:Record<ForecastKind,string> = {gas:'G',sensor_failure:'S',fire:'F'};

export function useMapForecasts(enabled:boolean) {
  const [attempt,setAttempt]=useState(0);
  const [result,setResult]=useState<{attempt:number;data:ForecastData|null;error:string}>({attempt:-1,data:null,error:''});
  useEffect(()=>{
    if(!enabled)return;
    const abort=new AbortController();
    jsonRequest<ForecastData>('/api/v1/map/forecasts',{signal:abort.signal})
      .then(data=>{if(!abort.signal.aborted)setResult({attempt,data,error:''});})
      .catch(()=>{if(!abort.signal.aborted)setResult({attempt,data:null,error:'Не удалось загрузить сохранённые прогнозы. Фактическое состояние доступно отдельно.'});});
    return()=>abort.abort();
  },[enabled,attempt]);
  return {data:result.data,error:result.attempt===attempt?result.error:'',loading:enabled&&result.attempt!==attempt,retry:()=>setAttempt(v=>v+1)};
}
