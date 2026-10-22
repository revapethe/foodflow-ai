"use client";

import { useEffect, useState } from "react";
import Intelligence from "./intelligence";
import { Activity, ArrowDownToLine, ArrowUpRight, BarChart3, Box, ChevronRight, Database, LayoutDashboard, Leaf, RefreshCw, Truck } from "lucide-react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Analytics = {
  source: string;
  available: { cities: string[]; start: string; end: string };
  kpis: { all_orders: number; delivered_orders: number; revenue: number; average_order_value: number | null; average_delivery_minutes: number | null; fulfillment_rate: number | null; average_rating: number | null; units_sold: number; units_per_delivered_order: number | null; over_60_min_percent: number | null; cancellation_percent: number | null };
  daily: { date: string; orders: number; delivered_orders: number; revenue: number }[];
  restaurants: { restaurant_key: number; restaurant_name: string; city: string; cuisine: string; orders: number; revenue: number; delivery_minutes: number }[];
  products: { food_name: string; category: string; units: number; revenue: number }[];
  statuses: { status: string; orders: number }[];
  forecast: { status: string; reason: string };
};
const money = (n: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
const number = (n: number) => new Intl.NumberFormat("en-US").format(n);
const dateLabel = (s: string) => new Date(s + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
const panel = "rounded-2xl border border-slate-200 bg-white p-5 md:p-6";

export default function Dashboard() {
  const [data, setData] = useState<Analytics | null>(null);
  const [city, setCity] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [metric, setMetric] = useState<"revenue" | "orders">("revenue");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    const query = new URLSearchParams();
    if (city) query.set("city", city);
    if (start) query.set("start", start);
    if (end) query.set("end", end);
    fetch(`/api/analytics?${query}`, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]), cache: "no-store" })
      .then(async response => { if (!response.ok) throw new Error(response.status === 422 ? "Choose a valid date range: start must be on or before end." : "The analytics service is unavailable. Check that FastAPI and the warehouse are running."); return response.json(); })
      .then(setData).catch(e => { if (e.name !== "AbortError") setError(e.name === "TimeoutError" ? "The analytics request timed out. Please retry." : e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [city, start, end, retry]);

  function download() {
    if (!data || loading || error) return;
    const csv = ["date,orders,delivered_orders,revenue", ...data.daily.map(d => `${d.date},${d.orders},${d.delivered_orders},${d.revenue}`)].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a"); a.href = url; a.download = "foodflow-daily-analytics.csv"; a.click(); URL.revokeObjectURL(url);
  }
  const k = data?.kpis;
  return <div className="min-h-screen bg-[#f6f8fa] text-slate-800 lg:pl-60">
    <aside className="fixed inset-y-0 left-0 hidden w-60 flex-col border-r border-slate-200 bg-white px-5 py-8 lg:flex">
      <a href="#" className="flex items-center gap-3 px-2 text-2xl font-bold tracking-tight"><span className="rounded-xl bg-emerald-700 p-2 text-white"><Leaf size={23}/></span>foodflow<span className="-ml-2 text-emerald-600">.</span></a>
      <p className="mb-10 mt-3 px-2 text-[10px] font-semibold uppercase tracking-[.2em] text-slate-400">Intelligence platform</p>
      <p className="mb-3 px-3 text-[10px] font-semibold uppercase tracking-widest text-slate-400">Workspace</p>
      <a href="#overview" className="nav active"><LayoutDashboard size={18}/>Overview</a>
      <a href="#demand" className="nav"><BarChart3 size={18}/>Demand insights</a>
      <a href="#operations" className="nav"><Truck size={18}/>Delivery operations</a>
      <a href="#products" className="nav"><Box size={18}/>Product performance</a>
      <div className="mt-auto rounded-xl border border-emerald-100 bg-emerald-50 p-4"><Database className="mb-3 text-emerald-700" size={20}/><p className="text-sm font-semibold">Warehouse analytics</p><p className="mt-2 text-xs leading-5 text-slate-500">Read-only insights from the existing dimensional model.</p><span className="mt-3 inline-block text-[10px] font-semibold uppercase tracking-wider text-emerald-700">Synthetic dataset</span></div>
      <div className="mt-6 flex items-center gap-3 px-2"><span className="grid h-9 w-9 place-items-center rounded-full bg-slate-100 text-xs font-bold">FF</span><div><p className="text-xs font-semibold">FoodFlow Analytics</p><p className="text-[10px] text-slate-400">Local workspace</p></div></div>
    </aside>
    <header className="flex min-h-20 items-center justify-between border-b border-slate-200 bg-white px-5 md:px-9"><div className="flex items-center gap-2 text-xs text-slate-400"><span className="font-semibold text-slate-700 lg:hidden">foodflow.</span><span>Workspace</span><ChevronRight size={14}/><span className="text-slate-700">Overview</span></div><div className="flex items-center gap-2 rounded-full border border-slate-200 px-3 py-1.5 text-[11px] text-slate-500"><span className={`h-1.5 w-1.5 rounded-full ${error ? "bg-amber-500" : "bg-emerald-500"}`}/>{data?.source.includes("PostgreSQL")?"PostgreSQL":"SQLite"} · read only</div></header>
    <nav aria-label="Dashboard sections" className="flex gap-5 overflow-x-auto border-b border-slate-200 bg-white px-5 py-3 text-xs font-medium text-slate-600 lg:hidden"><a href="#overview">Overview</a><a href="#demand">Demand</a><a href="#operations">Operations</a><a href="#products">Products</a></nav>
    <main id="overview" className="mx-auto max-w-[1550px] space-y-6 p-5 md:p-9">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="eyebrow">From data to better decisions</p><h1 className="mt-2 text-3xl font-semibold tracking-tight md:text-4xl">Supply chain overview</h1><p className="mt-3 text-sm text-slate-500">Understand demand, track delivery performance, and uncover what drives revenue.</p></div><button onClick={download} disabled={!data || loading || !!error} className="button bg-white"><ArrowDownToLine size={15}/>Export daily data</button></div>
      <div className="flex flex-wrap items-end gap-4 rounded-xl border border-slate-200 bg-white p-4"><label className="filter">Market<select value={city} onChange={e => setCity(e.target.value)}><option value="">All cities</option>{data?.available.cities.map(c => <option key={c}>{c}</option>)}</select></label><label className="filter">From<input aria-label="From date" type="date" value={start} min={data?.available.start} max={data?.available.end} onChange={e => setStart(e.target.value)}/></label><label className="filter">To<input aria-label="To date" type="date" value={end} min={data?.available.start} max={data?.available.end} onChange={e => setEnd(e.target.value)}/></label><button onClick={() => { setCity(""); setStart(""); setEnd(""); }} className="button text-slate-500">Reset filters</button><p className="ml-auto pb-2 text-xs text-slate-400">{data ? `${dateLabel(data.available.start)} – ${dateLabel(data.available.end)}, ${data.available.start.slice(0,4)}` : "Connecting to warehouse…"}</p></div>
      <div role="status" aria-live="polite">{loading && <p className="text-sm text-slate-500">Loading warehouse results…</p>}</div>
      {error ? <div role="alert" aria-label="Analytics error" className="rounded-xl border border-amber-200 bg-amber-50 p-6"><p>{error}</p><button className="button mt-4 bg-white" onClick={() => setRetry(v => v + 1)}><RefreshCw size={14}/>Retry</button></div> : !loading && data && k ? <>
      <section aria-label="Key performance indicators" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[
        { label: "Delivered revenue", value: money(k.revenue), caption: "Order totals including delivery fees", icon: BarChart3 },
        { label: "Delivered orders", value: number(k.delivered_orders), caption: `${number(k.all_orders)} total orders in selection`, icon: Box },
        { label: "Delivery completion", value: k.fulfillment_rate === null ? "—" : `${k.fulfillment_rate}%`, caption: "Delivered orders ÷ all orders", icon: Truck },
        { label: "Avg. delivery time", value: k.average_delivery_minutes === null ? "—" : `${k.average_delivery_minutes} min`, caption: "Delivered orders only", icon: Activity },
      ].map(card => <article key={card.label} className={panel}><div className="flex items-center justify-between"><p className="text-xs font-medium text-slate-500">{card.label}</p><card.icon size={17} className="text-emerald-600"/></div><p className="my-4 text-3xl font-semibold tracking-tight">{card.value}</p><p className="text-[11px] text-slate-400">{card.caption}</p></article>)}</section>
      {k.all_orders === 0 ? <div className={panel}><h2>No orders in this selection</h2><p className="mt-2 text-sm text-slate-500">Adjust the market or date filters to explore available data.</p></div> : <>
      <section id="demand" className="grid gap-6 xl:grid-cols-3"><article className={`${panel} xl:col-span-2`}><div className="flex flex-wrap justify-between gap-3"><div><h2>Demand & revenue</h2><p className="subtitle">Daily warehouse results for the selected market</p></div><div className="flex h-9 rounded-lg bg-slate-100 p-1">{(["revenue", "orders"] as const).map(m => <button key={m} aria-pressed={metric === m} onClick={() => setMetric(m)} className={`rounded-md px-3 text-xs capitalize ${metric === m ? "bg-white text-emerald-700 shadow-sm" : "text-slate-500"}`}>{m}</button>)}</div></div><div className="mt-7 h-72" role="img" aria-label={`Daily ${metric} chart. Export daily data for exact values.`}><ResponsiveContainer width="100%" height="100%"><AreaChart data={data.daily} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}><defs><linearGradient id="revenueFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#059669" stopOpacity={.22}/><stop offset="100%" stopColor="#059669" stopOpacity={0}/></linearGradient></defs><CartesianGrid strokeDasharray="3 5" vertical={false} stroke="#e8edf1"/><XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={45} axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#64748b" }}/><YAxis tickFormatter={v => metric === "revenue" ? `$${v}` : String(v)} axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#64748b" }} width={55}/><Tooltip labelFormatter={v => dateLabel(String(v))} formatter={v => metric === "revenue" ? money(Number(v)) : number(Number(v))}/><Area isAnimationActive={false} type="linear" dataKey={metric} name={metric === "revenue" ? "Delivered revenue" : "All orders"} stroke="#059669" strokeWidth={2} fill="url(#revenueFill)"/></AreaChart></ResponsiveContainer></div><div className="mt-4 flex gap-2 border-t border-slate-100 pt-4 text-[11px] text-slate-400"><span className="mt-1 h-2 w-2 rounded-full bg-emerald-500"/>Historical observations · missing dates are not imputed</div></article>
      <article className={`${panel} flex flex-col`}><h2>Fulfillment signals</h2><p className="subtitle">Actual delivered-item throughput and delivery outcomes</p><dl className="mt-6 space-y-5">{[
        ["Delivered food units",number(k.units_sold)],
        ["Units per delivered order",k.units_per_delivered_order===null?"—":String(k.units_per_delivered_order)],
        ["Deliveries over 60 minutes",k.over_60_min_percent===null?"—":`${k.over_60_min_percent}%`],
        ["Order cancellation rate",k.cancellation_percent===null?"—":`${k.cancellation_percent}%`],
      ].map(([label,value])=><div key={label}><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 text-xl font-semibold">{value}</dd></div>)}</dl><p className="mt-6 text-xs leading-5 text-slate-500">All figures follow the historical filters. The 60-minute threshold is descriptive, not a promised delivery SLA. Stock levels and supplier records are unavailable.</p></article></section>
      <Intelligence city={city} start={start} end={end}/>
      <section id="operations" className="grid gap-6 xl:grid-cols-3"><article className={`${panel} overflow-hidden xl:col-span-2`}><div className="mb-6 flex items-center justify-between"><div><h2>Restaurant performance</h2><p className="subtitle">Top 10 by delivered revenue</p></div><ArrowUpRight size={18} className="text-slate-400"/></div><div className="overflow-x-auto" role="region" aria-label="Restaurant rankings" tabIndex={0}><table className="w-full whitespace-nowrap text-left text-xs"><thead><tr>{["Restaurant", "Market", "Orders", "Revenue", "Delivery"].map(s => <th key={s} className="pb-4 pr-5 text-[10px] font-medium uppercase tracking-wider text-slate-400">{s}</th>)}</tr></thead><tbody>{data.restaurants.map((r,i) => <tr key={r.restaurant_key} className="border-t border-slate-100"><td className="py-4 pr-5"><span className="mr-3 text-[10px] text-slate-400">{String(i+1).padStart(2,"0")}</span><span className="font-medium">{r.restaurant_name}</span></td><td className="pr-5 text-slate-500">{r.city}</td><td className="pr-5">{number(r.orders)}</td><td className="pr-5 font-semibold">{money(r.revenue)}</td><td className="text-slate-500">{r.delivery_minutes} min</td></tr>)}</tbody></table></div></article><article className={panel}><h2>Order health</h2><p className="subtitle">Every order accounted for</p><div className="mt-7 flex h-3 overflow-hidden rounded-full">{data.statuses.map(s => <div key={s.status} style={{width:`${100*s.orders/k.all_orders}%`}} className={s.status === "delivered" ? "bg-emerald-500" : s.status === "cancelled" ? "bg-amber-400" : "bg-slate-300"}/>)}</div><div className="mt-6 space-y-5">{data.statuses.map(s => <div key={s.status} className="flex justify-between text-sm"><span className="capitalize text-slate-500">{s.status}</span><span className="font-semibold">{number(s.orders)} <span className="ml-2 text-xs font-normal text-slate-400">{(100*s.orders/k.all_orders).toFixed(1)}%</span></span></div>)}</div><div className="mt-8 grid grid-cols-2 gap-3 border-t border-slate-100 pt-6"><div><p className="text-xs text-slate-400">Avg. order value</p><p className="mt-2 text-xl font-semibold">{k.average_order_value === null ? "—" : money(k.average_order_value)}</p></div><div><p className="text-xs text-slate-400">Customer rating</p><p className="mt-2 text-xl font-semibold">{k.average_rating === null ? "—" : `${k.average_rating} / 5`}</p></div></div></article></section>
      <section id="products" className={panel}><h2>What customers order</h2><p className="subtitle">Top products by units in delivered orders · item revenue excludes delivery fees</p><div className="mt-6 h-80" role="img" aria-label="Top products ranked by units sold"><ResponsiveContainer width="100%" height="100%"><BarChart data={data.products} layout="vertical" margin={{left:0,right:25}}><CartesianGrid horizontal={false} strokeDasharray="3 5" stroke="#e8edf1"/><XAxis type="number" axisLine={false} tickLine={false} tick={{fontSize:11}}/><YAxis dataKey="food_name" type="category" width={100} axisLine={false} tickLine={false} tick={{fontSize:11}}/><Tooltip/><Bar isAnimationActive={false} dataKey="units" name="Units sold" fill="#10b981" radius={[0,4,4,0]} maxBarSize={18}/></BarChart></ResponsiveContainer></div></section>
      </>}
      <footer className="flex flex-wrap justify-between gap-3 border-t border-slate-200 py-4 text-[11px] text-slate-400"><span>{data.source}</span><span>Inventory & supplier analysis require additional source data.</span></footer>
      </> : null}
    </main>
  </div>;
}
