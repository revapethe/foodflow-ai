"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { MessageSquare, Send } from "lucide-react";

type Reply = {
  status: string; answer: string; rows?: Record<string, string | number | null>[];
  sql?: string; parameters?: (string | number)[]; source?: string; queried_at?: string;
  matching_orders?: number; filters?: {city: string | null; start: string | null; end: string | null};
  warehouse_range?: {start: string; end: string}; notes?: string[];
};
const examples = ["What is total revenue?", "How many orders in Denver?", "Top 5 restaurants by revenue", "Top 5 foods by units", "Show monthly revenue", "Compare cities", "Show delivery performance", "What is revenue in March 2025?"];
const label = (key: string) => key.replaceAll("_", " ");
const display = (value: string | number | null) => value === null ? "Unavailable" : typeof value === "number" ? value.toLocaleString("en-US", {maximumFractionDigits: 2}) : value;

export default function Assistant({city, start, end}: {city: string; start: string; end: string}) {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState("");
  const [reply, setReply] = useState<Reply | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    controller.current?.abort(); controller.current = null; setReply(null); setAsked(""); setError(""); setLoading(false);
    return () => { controller.current?.abort(); controller.current = null; };
  }, [city, start, end]);
  async function ask(text: string) {
    if (!text.trim()) return;
    controller.current?.abort();
    const active = new AbortController(); controller.current = active;
    setQuestion(text); setAsked(text); setLoading(true); setReply(null); setError("");
    const timeout = setTimeout(() => active.abort(), 15000);
    try {
      const response = await fetch("/api/assistant", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({question: text, city: city || null, start: start || null, end: end || null}), signal: active.signal});
      if (!response.ok) throw new Error("The assistant could not query the warehouse. Check the service and try again.");
      const result: Reply = await response.json();
      if (controller.current === active) setReply(result);
    } catch {
      if (controller.current === active) setError("The assistant could not finish the request. Check your connection and try again.");
    } finally {
      clearTimeout(timeout);
      if (controller.current === active) setLoading(false);
    }
  }
  function submit(event: FormEvent) { event.preventDefault(); void ask(question); }
  const columns = reply?.rows?.length ? Object.keys(reply.rows[0]) : [];
  return <section id="assistant" aria-label="Warehouse analytics assistant" className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:p-7">
    <div className="flex items-center gap-3"><MessageSquare className="text-emerald-600" size={22}/><div><h2>Ask your warehouse</h2><p className="subtitle">Free natural-language analytics · verified SQL templates · no API key</p></div></div>
    <p className="mt-4 text-sm leading-6 text-slate-500">Ask about revenue, orders, delivery, cancellations, rankings, or monthly trends. Each answer queries the warehouse and includes its SQL. This assistant supports specific question patterns; it does not use a general-purpose language model.</p>
    <p className="mt-2 text-xs leading-5 text-slate-500">Uses dashboard filters unless your question names a city, month, year, or inclusive date range. For example: “Revenue in Denver from 2025-03-01 to 2025-06-30”. Relative dates, inventory, and explanations of why a change happened are unavailable.</p>
    <div className="mt-4 flex flex-wrap gap-2" aria-label="Example questions">{examples.map(text => <button key={text} type="button" disabled={loading} onClick={() => void ask(text)} className="rounded-full border border-slate-200 px-3 py-2 text-left text-xs text-slate-600 hover:border-emerald-400 hover:bg-emerald-50 disabled:opacity-50">{text}</button>)}</div>
    <form onSubmit={submit} className="mt-5"><label htmlFor="warehouse-question" className="text-xs font-medium text-slate-600">Your analytics question</label><textarea id="warehouse-question" rows={2} maxLength={500} value={question} onChange={event => setQuestion(event.target.value)} placeholder="What is total revenue in Denver?" className="mt-2 w-full resize-y rounded-xl border border-slate-200 p-3 text-sm focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-100"/><div className="mt-3 flex items-center justify-between gap-3"><span className="text-xs text-slate-400">{question.length}/500 · synthetic source data</span><button className="button bg-emerald-600 text-white disabled:opacity-50" disabled={loading || !question.trim()} type="submit"><Send size={14}/>{loading ? "Querying…" : "Ask warehouse"}</button></div></form>
    {loading && <p role="status" className="mt-4 text-sm text-slate-500">Reading warehouse results…</p>}
    {error && <div role="alert" className="mt-4 rounded-xl bg-amber-50 p-4 text-sm text-amber-900"><p>{error}</p><button type="button" className="button mt-3 bg-white" onClick={() => void ask(asked)}>Retry question</button></div>}
    {reply && <div className="mt-5 border-t border-slate-100 pt-5" aria-label="Assistant answer" role="region"><p className="break-words text-xs text-slate-400">Question: {asked}</p><p role="status" className="mt-3 text-sm font-medium leading-6 text-slate-800">{reply.answer}</p>{reply.status === "answered" && <>
      <p className="mt-3 text-xs leading-5 text-slate-500">Applied scope: {reply.filters?.city || "All cities"} · {reply.filters?.start || "Beginning of data"} to {reply.filters?.end || "End of data"} · {reply.matching_orders?.toLocaleString()} matching orders.</p>
      {columns.length > 0 && <div role="region" aria-label="Assistant result table" tabIndex={0} className="mt-4 overflow-x-auto"><table className="w-full whitespace-nowrap text-left text-xs"><thead><tr>{columns.map(column => <th key={column} className="border-b border-slate-200 px-3 py-3 font-medium capitalize text-slate-500">{label(column)}</th>)}</tr></thead><tbody>{reply.rows!.map((row, i) => <tr key={i} className="border-b border-slate-100">{columns.map(column => <td key={column} className="px-3 py-3">{display(row[column])}</td>)}</tr>)}</tbody></table></div>}
      <details className="mt-4 rounded-xl bg-slate-50 p-4 text-xs"><summary className="cursor-pointer font-medium text-slate-600">View SQL and bound parameters</summary><pre className="mt-3 overflow-x-auto whitespace-pre text-slate-600">{reply.sql}</pre><p className="mt-3 break-words">Parameters: {JSON.stringify(reply.parameters)}</p></details>
      <p className="mt-4 text-xs leading-5 text-slate-400">{reply.source}. Warehouse coverage: {reply.warehouse_range?.start} to {reply.warehouse_range?.end}. Queried at {reply.queried_at}.</p><ul className="mt-2 list-disc space-y-1 pl-4 text-xs leading-5 text-slate-400">{reply.notes?.map(note => <li key={note}>{note}</li>)}</ul>
    </>}</div>}
  </section>;
}
