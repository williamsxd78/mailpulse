import { useEffect, useRef, useState, useCallback } from "react";
import { toast } from "sonner";
import {
  Upload, Play, Pause, X, Trash2, Download, Loader2, FileText, ChevronDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import {
  createJob, listJobs, pauseJob, resumeJob, cancelJob, deleteJob, downloadUrl,
} from "@/lib/api";

const STATUS_STYLE = {
  queued: "bg-slate-800 text-slate-300 border-slate-700",
  preparing: "bg-indigo-950/70 text-indigo-300 border-indigo-800/60",
  running: "bg-emerald-950/70 text-emerald-300 border-emerald-800/60",
  paused: "bg-amber-950/70 text-amber-300 border-amber-800/60",
  completed: "bg-emerald-900/70 text-emerald-200 border-emerald-700/60",
  canceled: "bg-rose-950/70 text-rose-300 border-rose-800/60",
  failed: "bg-rose-950/70 text-rose-300 border-rose-800/60",
};

const ACTIVE = new Set(["queued", "preparing", "running", "paused"]);

function JobCard({ job, onChange }) {
  const pct = job.percent || 0;
  const busy = job.status === "running" || job.status === "preparing";

  const act = async (fn, label) => {
    try {
      await fn(job.id);
      toast.success(label);
      onChange();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Action failed");
    }
  };

  const download = (category) => {
    window.open(downloadUrl(job.id, category), "_blank");
  };

  return (
    <div data-testid={`job-card-${job.id}`} className="rounded-xl border border-border/60 bg-card/60 backdrop-blur-md p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-display text-sm font-semibold text-foreground truncate">{job.name}</p>
          <p className="text-[11px] text-muted-foreground font-mono mt-0.5">
            {job.smtp_check ? "SMTP verify" : "MX + syntax"} · {job.rate ? `${job.rate}/s` : "—"}
          </p>
        </div>
        <span className={`shrink-0 text-[10px] font-mono uppercase px-2 py-1 rounded-full border ${STATUS_STYLE[job.status] || STATUS_STYLE.queued}`}>
          {job.status}
        </span>
      </div>

      <div className="mt-3">
        <div className="flex justify-between text-[11px] font-mono text-muted-foreground mb-1">
          <span>{job.processed.toLocaleString()} / {job.total.toLocaleString()}</span>
          <span>{pct}%</span>
        </div>
        <Progress value={pct} className="h-1.5 bg-black/40" />
      </div>

      <div className="flex flex-wrap gap-3 mt-3 text-xs font-mono">
        <span className="text-emerald-400">{job.deliverable_count.toLocaleString()} deliverable</span>
        <span className="text-rose-400">{job.invalid_count.toLocaleString()} invalid</span>
        {job.unknown_count > 0 && <span className="text-amber-400">{job.unknown_count.toLocaleString()} unverified</span>}
        {job.catchall_count > 0 && <span className="text-amber-400">{job.catchall_count.toLocaleString()} catch-all</span>}
      </div>

      {job.error && <p className="text-[11px] text-rose-400 mt-2 font-mono">{job.error}</p>}

      <div className="flex items-center gap-2 mt-4">
        {busy && (
          <Button data-testid={`job-pause-${job.id}`} onClick={() => act(pauseJob, "Pausing…")} size="sm" variant="secondary" className="h-8 gap-1.5">
            <Pause size={13} /> Pause
          </Button>
        )}
        {(job.status === "paused" || job.status === "failed") && (
          <Button data-testid={`job-resume-${job.id}`} onClick={() => act(resumeJob, "Resumed")} size="sm" className="h-8 gap-1.5 bg-emerald-500 hover:bg-emerald-400 text-emerald-950">
            <Play size={13} /> Resume
          </Button>
        )}
        {ACTIVE.has(job.status) && job.status !== "paused" && (
          <Button data-testid={`job-cancel-${job.id}`} onClick={() => act(cancelJob, "Canceling…")} size="sm" variant="secondary" className="h-8 gap-1.5">
            <X size={13} /> Cancel
          </Button>
        )}
        {job.processed > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button data-testid={`job-download-${job.id}`} size="sm" variant="secondary" className="h-8 gap-1.5">
                <Download size={13} /> CSV <ChevronDown size={12} />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="bg-popover border-border">
              <DropdownMenuItem onClick={() => download("all")} data-testid={`job-download-all-${job.id}`}>All results</DropdownMenuItem>
              <DropdownMenuItem onClick={() => download("deliverable")}>Deliverable only</DropdownMenuItem>
              <DropdownMenuItem onClick={() => download("invalid")}>Invalid only</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        <Button data-testid={`job-delete-${job.id}`} onClick={() => act(deleteJob, "Deleted")} size="icon" variant="ghost" className="h-8 w-8 ml-auto text-muted-foreground hover:text-rose-400">
          <Trash2 size={14} />
        </Button>
      </div>
    </div>
  );
}

export default function BulkJobs() {
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [dedupe, setDedupe] = useState(true);
  const [smtp, setSmtp] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [jobs, setJobs] = useState([]);
  const fileRef = useRef(null);
  const fileObj = useRef(null);

  const refresh = useCallback(async () => {
    try {
      setJobs(await listJobs());
    } catch (e) {
      console.error("Failed to load jobs:", e);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [refresh]);

  const onFile = (e) => {
    const f = e.target.files?.[0];
    fileObj.current = f || null;
    setFileName(f ? f.name : "");
  };

  const submit = async () => {
    if (!fileObj.current && !text.trim()) return toast.error("Upload a file or paste emails");
    setSubmitting(true);
    try {
      const fd = new FormData();
      if (name.trim()) fd.append("name", name.trim());
      fd.append("dedupe", dedupe);
      fd.append("smtp_check", smtp);
      if (text.trim()) fd.append("text", text);
      if (fileObj.current) fd.append("file", fileObj.current);
      await createJob(fd);
      toast.success("Bulk job started");
      setName(""); setText(""); setFileName(""); fileObj.current = null;
      if (fileRef.current) fileRef.current.value = "";
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to start job");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="grid lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] gap-5">
      {/* Upload panel */}
      <section className="rounded-xl border border-border/60 bg-card/60 backdrop-blur-md overflow-hidden">
        <div className="px-4 py-3 border-b border-border/60 bg-black/20">
          <h2 className="font-display text-sm font-semibold text-foreground">New Bulk Job</h2>
          <p className="text-[11px] text-muted-foreground">upload up to millions · runs in background · download CSV</p>
        </div>
        <div className="p-4 space-y-3">
          <Input data-testid="bulk-name-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Job name (optional)" className="h-9 bg-black/30 border-border/60 text-sm" />

          <label className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border/70 bg-black/30 hover:bg-black/40 cursor-pointer py-8 transition-colors">
            <input ref={fileRef} data-testid="bulk-file-input" type="file" accept=".txt,.csv" onChange={onFile} className="hidden" />
            <Upload className="text-emerald-400" size={22} />
            <span className="text-sm text-foreground font-medium">{fileName || "Drop / choose CSV or TXT"}</span>
            <span className="text-[11px] text-muted-foreground">one email (or email:pass) per line</span>
          </label>

          <Textarea data-testid="bulk-text-input" value={text} onChange={(e) => setText(e.target.value)} placeholder="…or paste emails here" className="mp-scroll h-24 resize-none font-mono text-xs text-emerald-300 bg-black/40 border-border/60" />

          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2">
              <Switch data-testid="bulk-dedupe-switch" checked={dedupe} onCheckedChange={setDedupe} />
              <Label className="text-xs text-muted-foreground">Dedupe</Label>
            </div>
            <div className="flex items-center gap-2">
              <Switch data-testid="bulk-smtp-switch" checked={smtp} onCheckedChange={setSmtp} />
              <Label className="text-xs text-muted-foreground">SMTP verify</Label>
            </div>
          </div>

          <Button data-testid="bulk-start-button" onClick={submit} disabled={submitting} className="w-full h-11 gap-2 font-display font-semibold bg-emerald-500 hover:bg-emerald-400 text-emerald-950 active:scale-[0.98] transition-transform">
            {submitting ? <><Loader2 size={17} className="animate-spin" /> Starting…</> : <><Play size={17} /> Start Bulk Job</>}
          </Button>
          {smtp && (
            <p className="text-[11px] text-amber-400/90 leading-snug">
              Heads-up: without SMTP proxies, mail providers rate-limit large runs and many emails will come back "unverified". Add proxies (port-25 capable) in the Proxies panel for scale.
            </p>
          )}
        </div>
      </section>

      {/* Jobs list */}
      <section className="rounded-xl border border-border/60 bg-card/60 backdrop-blur-md overflow-hidden">
        <div className="px-4 py-3 border-b border-border/60 bg-black/20 flex items-center justify-between">
          <h2 className="font-display text-sm font-semibold text-foreground">Jobs</h2>
          <span className="text-[11px] font-mono text-muted-foreground">{jobs.length} total</span>
        </div>
        <ScrollArea className="h-[62vh] min-h-[300px] mp-scroll">
          <div className="p-3 space-y-3" data-testid="jobs-list">
            {jobs.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-20 text-center">
                <FileText className="text-muted-foreground opacity-40" size={28} />
                <p className="text-sm text-muted-foreground">No bulk jobs yet</p>
              </div>
            ) : (
              jobs.map((j) => <JobCard key={j.id} job={j} onChange={refresh} />)
            )}
          </div>
        </ScrollArea>
      </section>
    </div>
  );
}
