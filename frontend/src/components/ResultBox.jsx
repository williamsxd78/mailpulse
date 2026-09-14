import { useState, useMemo } from "react";
import { Copy, Download, Search, ShieldCheck, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";

const TAG_STYLES = {
  "Syntax Valid": "bg-emerald-950/70 text-emerald-300 border-emerald-800/60",
  "MX Active": "bg-emerald-950/70 text-emerald-300 border-emerald-800/60",
  "Invalid Syntax": "bg-rose-950/70 text-rose-300 border-rose-800/60",
  "No MX Record": "bg-rose-950/70 text-rose-300 border-rose-800/60",
  "Disposable Domain": "bg-amber-950/70 text-amber-300 border-amber-800/60",
  "Role Account": "bg-cyan-950/70 text-cyan-300 border-cyan-800/60",
  "Possible Typo": "bg-fuchsia-950/70 text-fuchsia-300 border-fuchsia-800/60",
};

function Tag({ label }) {
  const cls = TAG_STYLES[label] || "bg-slate-800/70 text-slate-300 border-slate-700/60";
  return (
    <span className={`px-1.5 py-0.5 rounded border text-[10px] font-mono uppercase tracking-wide ${cls}`}>
      {label}
    </span>
  );
}

export function ResultBox({ variant, results, testId, countTestId, copyTestId, downloadTestId }) {
  const [query, setQuery] = useState("");
  const valid = variant === "valid";

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return results;
    return results.filter((r) => r.email.toLowerCase().includes(q) || r.reason.toLowerCase().includes(q));
  }, [results, query]);

  const emailsText = results.map((r) => r.email).join("\n");

  const handleCopy = () => {
    if (!results.length) return toast.error("Nothing to copy yet");
    navigator.clipboard.writeText(emailsText);
    toast.success(`Copied ${results.length} ${valid ? "deliverable" : "invalid"} email(s)`);
  };

  const handleDownload = () => {
    if (!results.length) return toast.error("Nothing to download yet");
    const header = "email,status,reason\n";
    const body = results.map((r) => `${r.email},${r.status},"${r.reason}"`).join("\n");
    const blob = new Blob([header + body], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${valid ? "deliverable" : "invalid"}-emails.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("CSV downloaded");
  };

  const accent = valid
    ? { ring: "border-emerald-800/50", glow: "shadow-[0_0_24px_rgba(16,185,129,0.12)]", text: "text-emerald-400", dot: "bg-emerald-400" }
    : { ring: "border-rose-800/50", glow: "shadow-[0_0_24px_rgba(244,63,94,0.12)]", text: "text-rose-400", dot: "bg-rose-400" };

  return (
    <div data-testid={testId} className={`flex flex-col rounded-xl border ${accent.ring} bg-card/60 backdrop-blur-md ${accent.glow} overflow-hidden`}>
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-border/60 bg-black/20">
        <div className="flex items-center gap-2.5 min-w-0">
          {valid ? <ShieldCheck className={`w-4.5 h-4.5 ${accent.text}`} size={18} /> : <ShieldAlert className={`w-4.5 h-4.5 ${accent.text}`} size={18} />}
          <div className="min-w-0">
            <h3 className="font-display text-sm font-semibold text-foreground truncate">
              {valid ? "Deliverable & Valid" : "Bounce / Invalid / Error"}
            </h3>
            <p className="text-[11px] text-muted-foreground truncate">
              {valid ? "Safe to send · active mailboxes" : "Filtered out · will bounce or fail"}
            </p>
          </div>
        </div>
        <span data-testid={countTestId} className={`shrink-0 font-mono text-xs font-semibold px-2.5 py-1 rounded-full border ${accent.ring} ${accent.text} bg-black/30`}>
          {results.length}
        </span>
      </div>

      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/40">
        <div className="relative flex-1">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter results…"
            className="h-8 pl-7 text-xs font-mono bg-black/30 border-border/60"
            data-testid={`${testId}-search`}
          />
        </div>
        <Button data-testid={copyTestId} onClick={handleCopy} variant="secondary" size="sm" className="h-8 px-2.5 gap-1.5 active:scale-95 transition-transform">
          <Copy size={13} /> Copy
        </Button>
        <Button data-testid={downloadTestId} onClick={handleDownload} variant="secondary" size="sm" className="h-8 px-2.5 gap-1.5 active:scale-95 transition-transform">
          <Download size={13} /> CSV
        </Button>
      </div>

      <ScrollArea className="h-[42vh] min-h-[240px] mp-scroll">
        <div className="p-2 space-y-1.5">
          {filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center gap-2">
              <span className={`w-2 h-2 rounded-full ${accent.dot} opacity-40`} />
              <p className="text-xs text-muted-foreground font-mono">
                {results.length === 0 ? "Awaiting validation…" : "No matches"}
              </p>
            </div>
          ) : (
            filtered.map((r, i) => (
              <div key={r.email + i} className="mp-fade-up group rounded-lg border border-border/40 bg-black/20 hover:bg-black/40 px-3 py-2 transition-colors">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[13px] text-foreground truncate">{r.email}</span>
                  <span className={`shrink-0 w-1.5 h-1.5 rounded-full ${accent.dot}`} />
                </div>
                <div className="flex flex-wrap items-center gap-1 mt-1.5">
                  {r.tags.map((t) => <Tag key={t} label={t} />)}
                  <span className="text-[10px] text-muted-foreground ml-0.5">{r.reason}</span>
                </div>
                {r.suggestion && (
                  <p className="text-[10px] text-fuchsia-300 mt-1 font-mono">↳ did you mean {r.suggestion}?</p>
                )}
              </div>
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
