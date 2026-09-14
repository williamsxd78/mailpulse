import { useMemo, useState, useEffect, useRef } from "react";
import { Zap, Trash2, FileText, Play, Loader2, Cpu, Mail } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { ResultBox } from "@/components/ResultBox";
import { HistoryPanel } from "@/components/HistoryPanel";
import { validateEmails } from "@/lib/api";

const SAMPLE = `amaury@reacher.email:hunter2
john.doe@gmail.com:MyP@ss123
support@microsoft.com
test@mailinator.com:qwerty
invalid-email-address
user@gmial.com:abc123
hello@yahoo.com
info@nonexistentdomain-xyz-123.com:pass
sarah.kim@outlook.com:letmein
admin@stripe.com
foobar@@broken.com
contact@github.com`;

function Metric({ label, value, accent, testId }) {
  return (
    <div className="flex flex-col px-4 py-2.5 rounded-lg border border-border/50 bg-black/20 min-w-[110px]">
      <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-mono">{label}</span>
      <span data-testid={testId} className={`font-display text-xl font-bold ${accent}`}>{value}</span>
    </div>
  );
}

export default function Validator() {
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const [dedupe, setDedupe] = useState(true);
  const [smtpCheck, setSmtpCheck] = useState(true);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [batch, setBatch] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const progressTimer = useRef(null);

  const lineCount = useMemo(() => text.split("\n").filter((l) => l.trim()).length, [text]);

  const deliverable = batch ? batch.results.filter((r) => r.category === "deliverable") : [];
  const invalid = batch ? batch.results.filter((r) => r.category === "invalid") : [];
  const rate = batch && batch.total ? Math.round((batch.deliverable_count / batch.total) * 100) : 0;

  useEffect(() => () => clearInterval(progressTimer.current), []);

  const startFakeProgress = () => {
    setProgress(6);
    progressTimer.current = setInterval(() => {
      setProgress((p) => (p >= 92 ? 92 : p + Math.random() * 9));
    }, 220);
  };

  const handleValidate = async () => {
    const emails = text.split("\n").map((l) => l.trim()).filter(Boolean);
    if (!emails.length) return toast.error("Paste at least one email to validate");

    setLoading(true);
    startFakeProgress();
    try {
      const data = await validateEmails({ emails, name: name.trim() || null, dedupe, smtp_check: smtpCheck });
      setBatch(data);
      setRefreshKey((k) => k + 1);
      toast.success(`Validated ${data.total} emails · ${data.deliverable_count} deliverable`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Validation failed");
    } finally {
      clearInterval(progressTimer.current);
      setProgress(100);
      setTimeout(() => { setLoading(false); setProgress(0); }, 500);
    }
  };

  const handleFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setText((prev) => (prev ? prev + "\n" : "") + String(ev.target.result));
      toast.success(`Loaded ${file.name}`);
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const loadFromHistory = (b) => {
    setBatch(b);
    setName(b.name);
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6">
      {/* Header */}
      <header className="flex flex-wrap items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="relative flex items-center justify-center w-11 h-11 rounded-xl bg-emerald-500/10 border border-emerald-500/30">
            <Mail className="text-emerald-400" size={22} />
            <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-400 mp-pulse" />
          </div>
          <div>
            <h1 className="font-display text-2xl sm:text-3xl font-extrabold tracking-tight text-foreground leading-none">
              MAIL<span className="text-emerald-400">PULSE</span>
            </h1>
            <p className="text-[11px] sm:text-xs text-muted-foreground font-mono mt-1">
              real-time syntax · MX · deliverability verification
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="hidden sm:flex items-center gap-1.5 text-xs font-mono text-muted-foreground px-3 py-2 rounded-lg border border-border/50 bg-black/20">
            <Cpu size={13} className="text-cyan-400" /> 10 workers
          </div>
          <HistoryPanel open={historyOpen} onOpenChange={setHistoryOpen} onLoad={loadFromHistory} refreshKey={refreshKey} />
        </div>
      </header>

      <div className="grid lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] gap-5">
        {/* LEFT — input */}
        <section className="flex flex-col rounded-xl border border-border/60 bg-card/60 backdrop-blur-md overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border/60 bg-black/20">
            <div>
              <h2 className="font-display text-sm font-semibold text-foreground">Email Input Stream</h2>
              <p className="text-[11px] text-muted-foreground">one per line · email or email:pass</p>
            </div>
            <span className="font-mono text-xs text-emerald-400 px-2.5 py-1 rounded-full border border-emerald-800/50 bg-black/30">
              {lineCount} loaded
            </span>
          </div>

          <div className="p-3">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Batch name (optional)"
              className="h-9 mb-3 text-sm bg-black/30 border-border/60"
              data-testid="batch-name-input"
            />
            <Textarea
              data-testid="email-input-textarea"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={"paste emails here…\njohn@example.com\njane@company.io:password123"}
              className="mp-scroll h-[38vh] min-h-[220px] resize-none font-mono text-[13px] text-emerald-300 bg-black/40 border-border/60 focus-visible:ring-emerald-500/50 focus-visible:border-emerald-600"
            />

            <div className="flex flex-wrap items-center gap-2 mt-3">
              <Button data-testid="sample-data-button" onClick={() => setText(SAMPLE)} variant="secondary" size="sm" className="gap-1.5 active:scale-95 transition-transform">
                <Zap size={14} /> Sample
              </Button>
              <Button data-testid="clear-all-button" onClick={() => { setText(""); setName(""); }} variant="secondary" size="sm" className="gap-1.5 active:scale-95 transition-transform">
                <Trash2 size={14} /> Clear
              </Button>
              <label className="inline-flex">
                <input data-testid="file-upload-input" type="file" accept=".txt,.csv" onChange={handleFile} className="hidden" />
                <span className="cursor-pointer inline-flex items-center gap-1.5 h-9 px-3 rounded-md text-sm font-medium bg-secondary text-secondary-foreground hover:bg-secondary/80 active:scale-95 transition-transform">
                  <FileText size={14} /> Upload
                </span>
              </label>
              <div className="flex items-center gap-2 ml-auto">
                <Switch data-testid="dedupe-switch" checked={dedupe} onCheckedChange={setDedupe} />
                <Label className="text-xs text-muted-foreground cursor-pointer">Dedupe</Label>
              </div>
            </div>

            <div className="flex items-center gap-2 mt-3 px-3 py-2 rounded-lg border border-border/50 bg-black/20">
              <Switch data-testid="smtp-check-switch" checked={smtpCheck} onCheckedChange={setSmtpCheck} />
              <div className="min-w-0">
                <Label className="text-xs text-foreground cursor-pointer">SMTP mailbox verification</Label>
                <p className="text-[10px] text-muted-foreground leading-tight">
                  probes the mail server to confirm the exact mailbox exists (catches "address not found" bounces). Off = syntax + MX only.
                </p>
              </div>
            </div>

            <Button
              data-testid="validate-start-button"
              onClick={handleValidate}
              disabled={loading}
              className="w-full mt-3 h-11 gap-2 font-display font-semibold text-base bg-emerald-500 hover:bg-emerald-400 text-emerald-950 active:scale-[0.98] transition-transform shadow-[0_0_20px_rgba(16,185,129,0.25)]"
            >
              {loading ? <><Loader2 size={18} className="animate-spin" /> Verifying…</> : <><Play size={18} /> Validate Email Stream</>}
            </Button>

            {loading && (
              <div data-testid="progress-indicator" className="mt-3">
                <Progress value={progress} className="h-1.5 bg-black/40" />
                <p className="text-[11px] font-mono text-muted-foreground mt-1.5 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 mp-pulse" /> probing mail servers · {Math.round(progress)}%
                </p>
              </div>
            )}
          </div>
        </section>

        {/* RIGHT — results */}
        <section className="flex flex-col gap-4">
          {/* metrics */}
          <div className="flex flex-wrap gap-2.5">
            <Metric label="Total" value={batch?.total ?? 0} accent="text-foreground" testId="metric-total" />
            <Metric label="Deliverable" value={batch?.deliverable_count ?? 0} accent="text-emerald-400" testId="metric-deliverable" />
            <Metric label="Invalid" value={batch?.invalid_count ?? 0} accent="text-rose-400" testId="metric-invalid" />
            <Metric label="Score" value={`${rate}%`} accent="text-cyan-400" testId="metric-score" />
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <ResultBox
              variant="valid"
              results={deliverable}
              testId="deliverable-box"
              countTestId="deliverable-count-badge"
              copyTestId="deliverable-copy-button"
              downloadTestId="deliverable-download-button"
            />
            <ResultBox
              variant="invalid"
              results={invalid}
              testId="invalid-box"
              countTestId="invalid-count-badge"
              copyTestId="invalid-copy-button"
              downloadTestId="invalid-download-button"
            />
          </div>
        </section>
      </div>

      <footer className="mt-8 text-center text-[11px] text-muted-foreground font-mono">
        MailPulse · syntax + MX + live SMTP mailbox verification · amber tags = catch-all / unverifiable
      </footer>
    </div>
  );
}
