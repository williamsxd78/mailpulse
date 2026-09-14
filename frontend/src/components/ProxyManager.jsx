import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Server, Plus, Trash2, Loader2, CheckCircle2, XCircle, Wifi,
  BookOpen, ChevronDown, ExternalLink, ShieldCheck, Ban,
} from "lucide-react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger,
} from "@/components/ui/dialog";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { listProxies, addProxy, deleteProxy, testProxy } from "@/lib/api";

const EMPTY = { label: "", type: "socks5", host: "", port: "", username: "", password: "" };

const ALLOW_PROVIDERS = [
  { name: "Proxy25", url: "https://proxy25.com", note: "Built only for email verification · SOCKS5 · reverse-DNS matched IPs (recommended)" },
  { name: "No2Bounce Proxies", url: "https://www.no2bounce.com/email-verifier-proxy-infrastructure", note: "Purpose-built SMTP proxies · port 25 open · warmed, Spamhaus-clean IPs" },
  { name: "Proxy-Connect", url: "https://proxy-connect.com/rotatingsocks.html", note: "Rotating SOCKS5 gateway made for email verifiers" },
  { name: "Reacher managed proxies", url: "https://reacher.email/smtp_proxies_for_email_verification", note: "MX-aware routing (Google/Microsoft/Mimecast) to dodge rate-limits" },
  { name: "Self-host VPS (advanced)", url: "https://vpsforlife.com/port-25-vps.php", note: "VPS with port 25 open + run your own SOCKS5 (Dante). Full control, cheapest at scale" },
];

const BLOCK_PROVIDERS = "Bright Data, Oxylabs, Smartproxy/Decodo, IPRoyal, and most residential/datacenter proxies block outbound port 25 by default — they will NOT work.";

export function ProxyManager({ open, onOpenChange }) {
  const [proxies, setProxies] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState(null);
  const [directResult, setDirectResult] = useState(null);
  const [testingDirect, setTestingDirect] = useState(false);
  const [guideOpen, setGuideOpen] = useState(true);

  const refresh = async () => {
    try { setProxies(await listProxies()); } catch { /* ignore */ }
  };

  useEffect(() => { if (open) refresh(); }, [open]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    if (!form.host.trim() || !form.port) return toast.error("Host and port required");
    setSaving(true);
    try {
      await addProxy({ ...form, port: Number(form.port) });
      toast.success("Proxy added");
      setForm(EMPTY);
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to add proxy");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id) => {
    try { await deleteProxy(id); refresh(); toast.success("Proxy removed"); }
    catch { toast.error("Failed to remove"); }
  };

  const runTest = async (id) => {
    setTestingId(id);
    try {
      const res = await testProxy({ id });
      toast[res.ok ? "success" : "error"](res.message);
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Test failed");
    } finally {
      setTestingId(null);
    }
  };

  const testDirect = async () => {
    setTestingDirect(true);
    setDirectResult(null);
    try {
      const res = await testProxy({});
      setDirectResult(res);
      toast[res.ok ? "success" : "error"](res.message);
    } catch (e) {
      toast.error("Test failed");
    } finally {
      setTestingDirect(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button data-testid="proxies-toggle" variant="outline" size="sm" className="gap-1.5 h-9 border-border/60 bg-black/20 hover:bg-black/40">
          <Server size={15} /> Proxies
        </Button>
      </DialogTrigger>
      <DialogContent data-testid="proxy-manager" className="max-w-2xl bg-card border-border/60 max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="font-display flex items-center gap-2 text-foreground">
            <Server size={18} className="text-emerald-400" /> SMTP Proxies
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            Add SOCKS/HTTP proxies that allow outbound port 25. Jobs rotate through enabled proxies to avoid provider rate-limits.
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="mp-scroll pr-3 overflow-y-auto">
          {/* Setup guide */}
          <Collapsible open={guideOpen} onOpenChange={setGuideOpen} className="mb-4">
            <div className="rounded-lg border border-emerald-800/40 bg-emerald-950/20 overflow-hidden">
              <CollapsibleTrigger asChild>
                <button data-testid="proxy-guide-toggle" className="w-full flex items-center justify-between gap-2 px-3 py-2.5 hover:bg-emerald-950/30 transition-colors">
                  <span className="flex items-center gap-2 text-sm font-medium text-emerald-300">
                    <BookOpen size={15} /> Setup guide — which proxies allow port 25
                  </span>
                  <ChevronDown size={15} className={`text-emerald-400 transition-transform ${guideOpen ? "rotate-180" : ""}`} />
                </button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="px-3 pb-3 pt-1 space-y-3">
                  <p className="text-[11px] text-muted-foreground leading-relaxed">
                    SMTP mailbox checks need <span className="text-emerald-300 font-medium">SOCKS5</span> proxies that explicitly allow
                    <span className="text-emerald-300 font-medium"> outbound port 25</span>. HTTP/SOCKS4 can't tunnel the raw SMTP handshake.
                  </p>

                  <div>
                    <p className="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-300 mb-1.5">
                      <ShieldCheck size={13} /> Providers that DO allow port 25
                    </p>
                    <div className="space-y-1.5">
                      {ALLOW_PROVIDERS.map((p) => (
                        <a key={p.name} href={p.url} target="_blank" rel="noreferrer"
                           data-testid={`guide-provider-${p.name}`}
                           className="flex items-start gap-2 rounded-md border border-border/50 bg-black/20 hover:bg-black/40 hover:border-emerald-800/50 px-2.5 py-2 transition-colors group">
                          <ExternalLink size={12} className="mt-0.5 text-emerald-400 shrink-0" />
                          <span className="min-w-0">
                            <span className="text-xs text-foreground font-medium group-hover:text-emerald-300">{p.name}</span>
                            <span className="block text-[10px] text-muted-foreground leading-snug">{p.note}</span>
                          </span>
                        </a>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-md border border-rose-900/40 bg-rose-950/20 px-2.5 py-2">
                    <p className="flex items-center gap-1.5 text-[11px] font-semibold text-rose-300 mb-1">
                      <Ban size={13} /> Won't work
                    </p>
                    <p className="text-[10px] text-muted-foreground leading-snug">{BLOCK_PROVIDERS}</p>
                  </div>

                  <div>
                    <p className="text-[11px] font-semibold text-foreground mb-1">Quick steps</p>
                    <ol className="text-[10px] text-muted-foreground space-y-0.5 list-decimal list-inside leading-relaxed">
                      <li>Buy a <span className="text-emerald-300">SOCKS5</span> proxy that confirms "outbound port 25 access".</li>
                      <li>Add it below (type SOCKS5 · host · port · optional user/pass).</li>
                      <li>Hit <span className="text-emerald-300">Test</span> — it must show "✓ port 25 ok".</li>
                      <li>Leave it enabled — bulk jobs auto-rotate through all working proxies.</li>
                    </ol>
                    <p className="text-[10px] text-muted-foreground mt-1.5 leading-snug">
                      Tip: providers with reverse-DNS (PTR) + warmed, blacklist-clean IPs give far more accurate results than raw datacenter IPs.
                    </p>
                  </div>
                </div>
              </CollapsibleContent>
            </div>
          </Collapsible>

          {/* Direct connectivity test */}
          <div className="rounded-lg border border-border/60 bg-black/20 p-3 mb-4">
            <div className="flex items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium text-foreground">Server connectivity (no proxy)</p>
                <p className="text-[11px] text-muted-foreground">check if this server can reach port 25 directly</p>
              </div>
              <Button data-testid="test-direct-button" onClick={testDirect} disabled={testingDirect} size="sm" variant="secondary" className="gap-1.5">
                {testingDirect ? <Loader2 size={13} className="animate-spin" /> : <Wifi size={13} />} Test
              </Button>
            </div>
            {directResult && (
              <div className={`mt-2 flex items-center gap-2 text-xs font-mono ${directResult.ok ? "text-emerald-400" : "text-rose-400"}`}>
                {directResult.ok ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                {directResult.message} {directResult.latency_ms ? `(${directResult.latency_ms}ms)` : ""}
              </div>
            )}
          </div>

          {/* Add form */}
          <div className="rounded-lg border border-border/60 bg-black/20 p-3 mb-4">
            <p className="text-sm font-medium text-foreground mb-3">Add proxy</p>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2 sm:col-span-1">
                <Label className="text-[11px] text-muted-foreground">Label</Label>
                <Input data-testid="proxy-label" value={form.label} onChange={(e) => set("label", e.target.value)} placeholder="My proxy" className="h-9 mt-1 bg-black/30 border-border/60 text-sm" />
              </div>
              <div className="col-span-2 sm:col-span-1">
                <Label className="text-[11px] text-muted-foreground">Type</Label>
                <Select value={form.type} onValueChange={(v) => set("type", v)}>
                  <SelectTrigger data-testid="proxy-type" className="h-9 mt-1 bg-black/30 border-border/60 text-sm"><SelectValue /></SelectTrigger>
                  <SelectContent className="bg-popover border-border">
                    <SelectItem value="socks5">SOCKS5</SelectItem>
                    <SelectItem value="socks4">SOCKS4</SelectItem>
                    <SelectItem value="http">HTTP</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-[11px] text-muted-foreground">Host</Label>
                <Input data-testid="proxy-host" value={form.host} onChange={(e) => set("host", e.target.value)} placeholder="1.2.3.4" className="h-9 mt-1 bg-black/30 border-border/60 text-sm font-mono" />
              </div>
              <div>
                <Label className="text-[11px] text-muted-foreground">Port</Label>
                <Input data-testid="proxy-port" value={form.port} onChange={(e) => set("port", e.target.value)} placeholder="1080" className="h-9 mt-1 bg-black/30 border-border/60 text-sm font-mono" />
              </div>
              <div>
                <Label className="text-[11px] text-muted-foreground">Username (opt)</Label>
                <Input data-testid="proxy-user" value={form.username} onChange={(e) => set("username", e.target.value)} className="h-9 mt-1 bg-black/30 border-border/60 text-sm" />
              </div>
              <div>
                <Label className="text-[11px] text-muted-foreground">Password (opt)</Label>
                <Input data-testid="proxy-pass" type="password" value={form.password} onChange={(e) => set("password", e.target.value)} className="h-9 mt-1 bg-black/30 border-border/60 text-sm" />
              </div>
            </div>
            <Button data-testid="proxy-add-button" onClick={save} disabled={saving} size="sm" className="mt-3 gap-1.5 bg-emerald-500 hover:bg-emerald-400 text-emerald-950">
              {saving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />} Add proxy
            </Button>
          </div>

          {/* List */}
          <div className="space-y-2" data-testid="proxy-list">
            {proxies.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">No proxies added — jobs will connect directly.</p>
            ) : proxies.map((p) => (
              <div key={p.id} className="flex items-center gap-3 rounded-lg border border-border/50 bg-black/20 p-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-foreground font-mono truncate">{p.type}://{p.host}:{p.port}</p>
                  <p className="text-[11px] text-muted-foreground">{p.label || "—"}
                    {p.last_status && (
                      <span className={p.last_status.ok ? "text-emerald-400 ml-2" : "text-rose-400 ml-2"}>
                        {p.last_status.ok ? "✓ port 25 ok" : "✕ port 25 failed"}
                      </span>
                    )}
                  </p>
                </div>
                <Button data-testid={`proxy-test-${p.id}`} onClick={() => runTest(p.id)} disabled={testingId === p.id} size="sm" variant="secondary" className="h-8 gap-1.5">
                  {testingId === p.id ? <Loader2 size={13} className="animate-spin" /> : <Wifi size={13} />} Test
                </Button>
                <Button onClick={() => remove(p.id)} size="icon" variant="ghost" className="h-8 w-8 text-muted-foreground hover:text-rose-400">
                  <Trash2 size={14} />
                </Button>
              </div>
            ))}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
