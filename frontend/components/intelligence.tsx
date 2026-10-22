"use client";
import { useEffect, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Point = {date:string; prediction:number; lower:number; upper:number};
type Metric = {mae:number; rmse:number; wape_percent:number|null};
type Flag = {date:string; metric:string; actual:number; expected:number; score:number; direction:string};
type Insights = {
  status:string; reason?:string; market?:string; as_of?:string; selected_model?:string; selected_label?:string;
  forecast_scope?:string; horizon_days?:number; training_days?:number;
  predictions?:Point[]; history?:{date:string; orders:number}[];
  evaluation?: {candidates:Record<string,{label:string; validation:Metric; test:Metric}>; test_start:string; test_end:string; test_days:number; test_band_coverage_percent:number; error_band_nominal_percent:number};
  anomalies?:{flags:Flag[]; threshold:number; evaluation:string};
};
const amount=(value:number|null|undefined,digits=2) => value==null ? "—" : value.toLocaleString("en-US",{maximumFractionDigits:digits,minimumFractionDigits:digits});
const shortDate=(s:string)=>new Date(s+"T00:00:00").toLocaleDateString("en-US",{month:"short",day:"numeric"});
const metricNames:Record<string,string>={orders:"Order volume",revenue:"Delivered revenue ($)",delivery_minutes:"Avg. delivery minutes"};

export default function Intelligence({city,start,end}:{city:string;start:string;end:string}) {
  const [data,setData]=useState<Insights|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [retry,setRetry]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true);setError("");
    const query=new URLSearchParams();
    if(city)query.set("city",city);if(start)query.set("start",start);if(end)query.set("end",end);
    fetch(`/api/intelligence?${query}`,{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(15000)]),cache:"no-store"})
      .then(async r=>{if(!r.ok)throw new Error("Intelligence could not be loaded. Check the date range or retry.");return r.json();})
      .then(value=>{if(!controller.signal.aborted)setData(value);}).catch(e=>{if(e.name!=="AbortError")setError(e.name==="TimeoutError"?"Intelligence request timed out.":e.message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[city,start,end,retry]);
  function download(){
    if(!data?.predictions)return;
    const csv=["date,expected_orders,lower_error_band,upper_error_band,model",...data.predictions.map(p=>`${p.date},${p.prediction},${p.lower},${p.upper},${data.selected_model}`)].join("\n");
    const url=URL.createObjectURL(new Blob([csv],{type:"text/csv"}));const a=document.createElement("a");a.href=url;a.download="foodflow-demand-forecast.csv";a.click();URL.revokeObjectURL(url);
  }
  const selected=data?.evaluation?.candidates[data.selected_model||""];
  const points=[...(data?.history||[]).map(p=>({date:p.date,actual:p.orders,prediction:undefined as number|undefined,band:undefined as number[]|undefined})),...(data?.predictions||[]).map(p=>({date:p.date,actual:undefined as number|undefined,prediction:p.prediction,band:[p.lower,p.upper]}))];
  const forecastsReady=data?.status==="ready";
  return <section id="intelligence" aria-label="Demand intelligence" className="space-y-5 rounded-2xl border border-slate-200 bg-white p-5 md:p-6">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="eyebrow">Evaluated from warehouse history</p><h2 className="mt-2 text-lg">Demand intelligence</h2><p className="subtitle">Forecasts and historical statistical flags · synthetic delivery data</p></div>{forecastsReady&&!loading&&!error&&<button className="button" onClick={download}>Export forecast</button>}</div>
    {loading?<p role="status" className="text-sm text-slate-500">Loading evaluated intelligence…</p>:error?<div role="alert" aria-label="Intelligence error" className="rounded-xl bg-amber-50 p-4 text-sm"><p>{error}</p><button className="button mt-3 bg-white" onClick={()=>setRetry(n=>n+1)}>Retry intelligence</button></div>:!forecastsReady?<div role="status" className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500">{data?.reason||"Evaluated forecasts are not available."}</div>:<>
      <div className="rounded-xl border border-amber-100 bg-amber-50 p-4 text-xs leading-5 text-amber-900"><strong>Historical demo forecast as of {data?.as_of}.</strong> Predictions follow the dataset, not today. {data?.forecast_scope}</div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[
        ["Selected forecasting method",data?.selected_label||"—"],
        ["Holdout MAE · orders / day",amount(selected?.test.mae)],
        ["Holdout WAPE",selected?.test.wape_percent==null?"N/A":`${amount(selected.test.wape_percent)}%`],
        [`Next ${data?.horizon_days} days · expected orders`,amount(data?.predictions?.reduce((s,p)=>s+p.prediction,0),1)],
      ].map(([label,value])=><div key={label} className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-500">{label}</p><p className="mt-3 text-lg font-semibold" data-testid="forecast-metric">{value}</p></div>)}</div>
      <p className="text-xs leading-5 text-slate-500">Selected by validation error across three chronological folds. The final {data?.evaluation?.test_days} days ({data?.evaluation?.test_start} through {data?.evaluation?.test_end}) were held out from selection. Lower error is better; the trained model is not assumed to outperform a baseline.</p>
      <div className="h-80" role="img" aria-label="Observed daily orders and 14-day forecast with empirical error band"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={points} margin={{left:0,right:15,top:10,bottom:0}}><CartesianGrid strokeDasharray="3 5" vertical={false} stroke="#e2e8f0"/><XAxis dataKey="date" tickFormatter={shortDate} minTickGap={40} tick={{fontSize:10,fill:"#64748b"}}/><YAxis tick={{fontSize:10,fill:"#64748b"}} width={35}/><Tooltip labelFormatter={v=>String(v)} formatter={(value,name)=>[Array.isArray(value)?value.map(v=>amount(Number(v))).join(" – "):amount(Number(value)),name]}/><Area dataKey="band" name="Empirical error band" type="linear" stroke="none" fill="#d1fae5" isAnimationActive={false}/><Line dataKey="actual" name="Observed orders" stroke="#64748b" dot={false} strokeWidth={2} isAnimationActive={false}/><Line dataKey="prediction" name="Expected orders" stroke="#059669" dot={false} strokeWidth={2} strokeDasharray="5 3" isAnimationActive={false}/></ComposedChart></ResponsiveContainer></div>
      <p className="text-xs leading-5 text-slate-500">Gray: observed orders. Dashed green: forecast. Shading: an {data?.evaluation?.error_band_nominal_percent}% empirical absolute-error band estimated from 28 earlier calibration days. Observed holdout coverage: {amount(data?.evaluation?.test_band_coverage_percent,1)}%. Temporal dependence and small samples limit coverage guarantees. Calendar gaps inside dataset coverage are treated as zero orders, assuming complete upstream data.</p>
      <div role="region" aria-label="Model comparison" tabIndex={0} className="overflow-x-auto"><table className="w-full whitespace-nowrap text-left text-xs"><thead><tr>{["Candidate","Validation MAE","Test MAE","Test RMSE","Test WAPE"].map(c=><th key={c} className="border-b border-slate-200 px-3 py-3 font-medium text-slate-500">{c}</th>)}</tr></thead><tbody>{Object.entries(data?.evaluation?.candidates||{}).map(([name,c])=><tr key={name} className={name===data?.selected_model?"bg-emerald-50":""}><td className="px-3 py-3 font-medium">{c.label}{name===data?.selected_model?" · selected":""}</td><td className="px-3 py-3">{amount(c.validation.mae)}</td><td className="px-3 py-3">{amount(c.test.mae)}</td><td className="px-3 py-3">{amount(c.test.rmse)}</td><td className="px-3 py-3">{c.test.wape_percent==null?"N/A":`${amount(c.test.wape_percent)}%`}</td></tr>)}</tbody></table></div>
      <div className="border-t border-slate-100 pt-5"><h3 className="text-sm font-semibold">Historical anomaly screening</h3><p className="subtitle">{data?.anomalies?.flags.length||0} statistical flags in the selected dates. Past-only weekday median and robust variability; absolute score threshold {data?.anomalies?.threshold}. These are candidates for investigation, not confirmed incidents.</p>{data?.anomalies?.flags.length?<div role="region" aria-label="Anomaly flags" tabIndex={0} className="mt-3 overflow-x-auto"><table className="w-full whitespace-nowrap text-left text-xs"><thead><tr>{["Date","Signal","Observed","Historical median","Robust score"].map(c=><th key={c} className="border-b border-slate-200 px-3 py-3 font-medium text-slate-500">{c}</th>)}</tr></thead><tbody>{data.anomalies.flags.slice(0,10).map(f=><tr key={`${f.date}-${f.metric}`} className="border-b border-slate-100"><td className="px-3 py-3">{f.date}</td><td className="px-3 py-3">{metricNames[f.metric]||f.metric}</td><td className="px-3 py-3">{amount(f.actual)}</td><td className="px-3 py-3">{amount(f.expected)}</td><td className="px-3 py-3">{amount(f.score)}</td></tr>)}</tbody></table><p className="mt-3 text-xs text-slate-500">Showing up to 10 flags ranked by absolute score.</p></div>:<p className="mt-4 text-sm text-slate-500">No flags exceed the configured threshold for this selection.</p>}<p className="mt-3 text-xs text-slate-500">{data?.anomalies?.evaluation}</p></div>
    </>}
  </section>;
}
