import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import {
  Server, Plus, Trash2, Loader2, CheckCircle2, XCircle, Wifi,
  BookOpen, ExternalLink, ShieldCheck, Ban,
} from "lucide-react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger,
} from "@/components/ui/dialog";
import {
  Accordion, AccordionItem, AccordionTrigger, AccordionContent,
} from "@/components/ui/accordion";
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

  const refresh = useCallback(async () => {
    try { setProxies(await listProxies()); }
    catch (e) { console.error("Failed to load proxies:", e); }
  }, []);

  useEffect(() => { if (open) refresh(); }, [open, refresh]);

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
          {/* Add form — kept at top so users don't scroll */}
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
          <div className="space-y-2 mb-4" data-testid="proxy-list">
            {proxies.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">No proxies added — jobs will connect directly.</p>
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

          {/* Setup guide — click-to-expand sections */}
          <div className="flex items-center gap-2 text-sm font-medium text-emerald-300 mb-2 px-1">
            <BookOpen size={15} /> Setup guide
          </div>
          <Accordion type="multiple" className="space-y-2" data-testid="proxy-guide">
            <AccordionItem value="providers" className="border border-emerald-800/40 bg-emerald-950/15 rounded-lg px-3">
              <AccordionTrigger data-testid="guide-providers-trigger" className="text-[13px] font-medium text-emerald-300 hover:no-underline py-3">
                Which proxies allow port 25
              </AccordionTrigger>
              <AccordionContent className="pb-3">
                <p className="text-[11px] text-muted-foreground leading-relaxed mb-2">
                  SMTP mailbox checks need <span className="text-emerald-300 font-medium">SOCKS5</span> proxies that explicitly allow
                  <span className="text-emerald-300 font-medium"> outbound port 25</span>. HTTP/SOCKS4 can't tunnel the raw SMTP handshake.
                </p>
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
                <div className="rounded-md border border-rose-900/40 bg-rose-950/20 px-2.5 py-2 mt-2">
                  <p className="flex items-center gap-1.5 text-[11px] font-semibold text-rose-300 mb-1">
                    <Ban size={13} /> Won't work
                  </p>
                  <p className="text-[10px] text-muted-foreground leading-snug">{BLOCK_PROVIDERS}</p>
                </div>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="quicksteps" className="border border-border/50 bg-black/20 rounded-lg px-3">
              <AccordionTrigger data-testid="guide-steps-trigger" className="text-[13px] font-medium text-foreground hover:no-underline py-3">
                Quick steps
              </AccordionTrigger>
              <AccordionContent className="pb-3">
                <ol className="text-[10px] text-muted-foreground space-y-0.5 list-decimal list-inside leading-relaxed">
                  <li>Buy a <span className="text-emerald-300">SOCKS5</span> proxy that confirms "outbound port 25 access".</li>
                  <li>Add it in the form above (type SOCKS5 · host · port · optional user/pass).</li>
                  <li>Hit <span className="text-emerald-300">Test</span> — it must show "✓ port 25 ok".</li>
                  <li>Leave it enabled — bulk jobs auto-rotate through all working proxies.</li>
                </ol>
                <p className="text-[10px] text-muted-foreground mt-1.5 leading-snug">
                  Tip: providers with reverse-DNS (PTR) + warmed, blacklist-clean IPs give far more accurate results than raw datacenter IPs.
                </p>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="roadblocks" className="border border-amber-900/40 bg-amber-950/10 rounded-lg px-3">
              <AccordionTrigger data-testid="guide-roadblocks-trigger" className="text-[13px] font-medium text-amber-300 hover:no-underline py-3">
                Yahoo / AOL & iCloud roadblocks
              </AccordionTrigger>
              <AccordionContent className="pb-3">
                <ul className="text-[10px] text-muted-foreground space-y-1 leading-snug list-disc list-inside">
                  <li><span className="text-amber-300">Yahoo/AOL catch-all trap:</span> on high volume from an unproven IP, Yahoo replies 250 OK to <em>everything</em> (even fake addresses). We auto-detect this and tag those emails <span className="text-amber-300">Catch-All</span> instead of falsely "valid". Needs a pristine IP + FCrDNS to get real answers.</li>
                  <li><span className="text-amber-300">Yahoo requires FCrDNS:</span> without matching forward/reverse DNS on your proxy IP, Yahoo refuses the port-25 connection outright.</li>
                  <li><span className="text-amber-300">iCloud greylisting:</span> Apple often says "try again later" (4xx) to new IPs and hard-blocks budget VPS ranges. We flag these <span className="text-amber-300">Greylisted</span> (not invalid) so you can re-check later rather than get false bounces.</li>
                </ul>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="selfhost" className="border border-border/50 bg-black/20 rounded-lg px-3">
              <AccordionTrigger data-testid="guide-selfhost-trigger" className="text-[13px] font-medium text-foreground hover:no-underline py-3">
                Self-host checklist (run your own SOCKS5 on a VPS)
              </AccordionTrigger>
              <AccordionContent className="pb-3">
                <ol className="text-[10px] text-muted-foreground space-y-1 leading-snug list-decimal list-inside">
                  <li>Use a <span className="text-emerald-300">strict-KYC VPS</span> (Hetzner / Linode) — clean IP ranges. Open a ticket asking to unblock outbound port 25 for "email list hygiene, with full FCrDNS/SPF".</li>
                  <li>Set up <span className="text-emerald-300">FCrDNS</span>: A record <code className="text-emerald-300">myverifier.com → VPS IP</code>, and PTR (reverse DNS) <code className="text-emerald-300">VPS IP → myverifier.com</code> (must match both ways).</li>
                  <li>Publish <span className="text-emerald-300">SPF</span> (<code>v=spf1 ip4:YOUR_IP ~all</code>) and <span className="text-emerald-300">DMARC</span> (<code>v=DMARC1; p=none;</code>) on that domain.</li>
                  <li>Point this app's HELO / MAIL FROM at your domain via backend env: <code className="text-emerald-300">SMTP_HELO_NAME=myverifier.com</code> and <code className="text-emerald-300">SMTP_MAIL_FROM=verifier@myverifier.com</code>.</li>
                  <li>Run a SOCKS5 daemon (e.g. Dante) on the VPS and add it above. We already EHLO with your domain, use a real MAIL FROM, and send a clean QUIT — the MTA-emulation Yahoo expects.</li>
                </ol>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="cost" className="border border-emerald-800/40 bg-emerald-950/15 rounded-lg px-3">
              <AccordionTrigger data-testid="guide-cost-trigger" className="text-[13px] font-medium text-emerald-300 hover:no-underline py-3">
                Cutting cost & the 10k/day cap
              </AccordionTrigger>
              <AccordionContent className="pb-3">
                <ul className="text-[10px] text-muted-foreground space-y-1 leading-snug list-disc list-inside">
                  <li><span className="text-emerald-300">Pre-filter free first:</span> run the list once with <span className="text-emerald-300">SMTP off</span> (MX + syntax + disposable + typo) — it's unlimited and free, and removes a big chunk of junk before you spend any paid verifications.</li>
                  <li><span className="text-emerald-300">Self-host beats managed at volume:</span> a strict-KYC VPS (Hetzner/Linode) is ~$5–15/mo with port 25 unblocked — no per-verification cap. One clean IP handles Gmail/Microsoft-heavy lists well beyond 10k/day; add 2–4 IPs only for Yahoo/AOL/iCloud reputation limits.</li>
                  <li><span className="text-emerald-300">Rotate a few cheap IPs</span> instead of one expensive managed pool — this app auto-rotates through every enabled proxy.</li>
                  <li>Managed pools ($49/mo tiers) are worth it only if you can't do DNS/PTR setup or need instant warmed IPs. For most, self-host is far cheaper per email.</li>
                </ul>
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
