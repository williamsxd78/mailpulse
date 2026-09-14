#!/usr/bin/env python3
"""
MailPulse — single-file email validator (UI + engine in one Python file).

Run:
    pip install dnspython
    python mailpulse_single.py
    # open http://localhost:8000

Checks: syntax, known-typo domains, disposable domains, MX records, and
(optional) live SMTP mailbox probe (RCPT TO) with catch-all + greylist handling.
SMTP verification needs outbound port 25 open on this machine.

Env (optional): PORT, SMTP_HELO_NAME, SMTP_MAIL_FROM
"""
import os, re, json, time, secrets, string, smtplib, threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import dns.resolver

PORT = int(os.environ.get("PORT", "8000"))
MAIL_FROM = os.environ.get("SMTP_MAIL_FROM", "verify@mailpulse.local")
HELO_NAME = os.environ.get("SMTP_HELO_NAME", "mailpulse.local")

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9]"
                         r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
                         r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$")
EMAIL_SEARCH = re.compile(r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9]"
                          r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
                          r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+")

DISPOSABLE = {
    "mailinator.com","10minutemail.com","guerrillamail.com","trashmail.com","yopmail.com",
    "tempmail.com","temp-mail.org","getnada.com","throwaway.email","maildrop.cc","sharklasers.com",
    "grr.la","mailnesia.com","mailcatch.com","mohmal.com","1secmail.com","discard.email","fakeinbox.com",
}
ROLES = {"admin","administrator","support","info","sales","contact","help","team","office","hello",
         "billing","abuse","postmaster","webmaster","noreply","no-reply","marketing","hr","jobs",
         "careers","service","root","security","sysadmin","hostmaster"}
TYPOS = {
    "gmial.com":"gmail.com","gmai.com":"gmail.com","gmail.co":"gmail.com","gnail.com":"gmail.com",
    "gmail.con":"gmail.com","gamil.com":"gmail.com","gmali.com":"gmail.com","gmaill.com":"gmail.com",
    "hotmial.com":"hotmail.com","hotmai.com":"hotmail.com","hotmail.con":"hotmail.com",
    "yaho.com":"yahoo.com","yahooo.com":"yahoo.com","yahoo.co":"yahoo.com","yhoo.com":"yahoo.com",
    "outlok.com":"outlook.com","outllok.com":"outlook.com","outlook.co":"outlook.com",
}
NOT_FOUND = ("does not exist","doesn't exist","no such user","user unknown","unknown user",
             "user not found","recipient not found","no mailbox","mailbox not found","invalid recipient",
             "invalid mailbox","recipient rejected","account that you tried to reach","no such recipient",
             "unknown recipient","unrouteable address")
BLOCK = ("blocked","blacklist","spamhaus","spam","denied","reputation","policy","greylist","rate limit",
         "too many","try again","temporarily","service unavailable","not authorized","access denied")

_resolver = dns.resolver.Resolver()
_resolver.timeout = 4; _resolver.lifetime = 4
_mx_cache = {}; _mx_lock = threading.Lock()


def extract_email(line):
    m = EMAIL_SEARCH.search(line)
    return m.group(0) if m else line


def check_mx(domain):
    with _mx_lock:
        if domain in _mx_cache:
            return _mx_cache[domain]
    res = (False, None)
    try:
        ans = _resolver.resolve(domain, "MX")
        hosts = sorted([(r.preference, str(r.exchange).rstrip('.')) for r in ans])
        if hosts: res = (True, hosts[0][1])
    except Exception:
        try:
            _resolver.resolve(domain, "A"); res = (True, None)
        except Exception:
            res = (False, None)
    with _mx_lock:
        _mx_cache[domain] = res
    return res


def _rand(n=14):
    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(n))


def _probe(srv, addr):
    try: srv.rset()
    except Exception: pass
    srv.mail(MAIL_FROM)
    code, msg = srv.rcpt(addr)
    return code, (msg.decode(errors="replace") if isinstance(msg, bytes) else str(msg))


def verify_one(email, smtp_check):
    out = {"email": email.strip(), "status": "invalid", "category": "invalid",
           "reason": "", "tags": [], "suggestion": None}
    key = email.strip().lower()
    if "@" not in key or not EMAIL_REGEX.match(key):
        out.update(status="invalid_syntax", reason="Malformed email syntax", tags=["Invalid Syntax"]); return out
    local, domain = key.rsplit("@", 1)
    if domain in TYPOS:
        sug = f"{local}@{TYPOS[domain]}"
        out.update(status="typo", reason=f"Misspelled domain — did you mean {sug}?",
                   tags=["Possible Typo"], suggestion=sug); return out
    if domain in DISPOSABLE:
        out.update(status="disposable", reason="Disposable / throwaway domain", tags=["Disposable Domain"]); return out
    has_mx, mx = check_mx(domain)
    if not has_mx:
        out.update(status="no_mx", reason="No MX record found for domain", tags=["No MX Record"]); return out

    tags = ["MX Active"] + (["Role Account"] if local in ROLES else [])
    if not smtp_check or not mx:
        out.update(status=("risky" if local in ROLES else "deliverable"), category="deliverable",
                   reason="Active MX record (mailbox not probed)", tags=["Syntax Valid"] + tags); return out

    srv = None
    for attempt in (True, False):  # try, then retry once
        try:
            srv = smtplib.SMTP(mx, 25, local_hostname=HELO_NAME, timeout=12)
            srv.ehlo_or_helo_if_needed(); break
        except Exception:
            if srv:
                try: srv.close()
                except Exception: pass
            srv = None
            if attempt: continue
    if srv is None:
        out.update(status="unknown", category="deliverable",
                   reason="Could not connect to mail server (blocked/greylisted)", tags=tags + ["Unverified"]); return out
    try:
        catch_all = False
        try:
            c, _ = _probe(srv, f"{_rand()}@{domain}")
            if c in (250, 251): catch_all = True
        except Exception: pass
        try:
            code, text = _probe(srv, key)
        except Exception as ex:
            code, text = None, str(ex)
        try: srv.quit()
        except Exception: pass
        low = (text or "").lower()
        if code in (250, 251):
            if catch_all:
                out.update(status="catch_all", category="deliverable",
                           reason="Catch-all domain — accepts all mail", tags=tags + ["Catch-All"])
            else:
                out.update(status="deliverable", category="deliverable",
                           reason="Mailbox verified via SMTP", tags=tags + ["Mailbox Verified"])
        elif code is not None and 500 <= code < 600 and (any(h in low for h in NOT_FOUND)
                or (code in (550, 551, 553) and not any(b in low for b in BLOCK))):
            out.update(status="mailbox_not_found", category="invalid",
                       reason=f"Mailbox does not exist ({code})", tags=["Mailbox Not Found"])
        elif code is not None and 400 <= code < 500:
            out.update(status="greylisted", category="deliverable",
                       reason="Greylisted — retry later", tags=tags + ["Greylisted"])
        else:
            out.update(status="unknown", category="deliverable",
                       reason="Could not verify mailbox (blocked/greylisted)", tags=tags + ["Unverified"])
    except Exception as ex:
        out.update(status="unknown", category="deliverable", reason=f"Probe error: {ex}", tags=tags + ["Unverified"])
        try: srv.close()
        except Exception: pass
    return out


def validate(emails, smtp_check=True, workers=10, dedupe=True):
    seen, cleaned = set(), []
    for e in emails:
        e = extract_email(e.strip())
        if not e: continue
        k = e.lower()
        if dedupe and k in seen: continue
        seen.add(k); cleaned.append(e)
    workers = max(1, min(int(workers or 10), 20))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda e: verify_one(e, smtp_check), cleaned))


HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MailPulse</title>
<style>
:root{--bg:#070B14;--card:#111827;--bd:#374151;--mut:#9CA3AF;--em:#10b981;--rose:#f43f5e;--amber:#f59e0b;--cyan:#06b6d4}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#F9FAFB;font-family:system-ui,Segoe UI,Roboto,sans-serif;
background-image:radial-gradient(circle at 15% 20%,rgba(16,185,129,.10),transparent 40%),radial-gradient(circle at 85% 80%,rgba(244,63,94,.08),transparent 42%)}
.wrap{max-width:1200px;margin:0 auto;padding:24px 16px}
.hd{display:flex;align-items:center;gap:12px;margin-bottom:22px}
.logo{width:44px;height:44px;border-radius:12px;background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.3);display:flex;align-items:center;justify-content:center;font-size:22px}
h1{font-size:26px;font-weight:800;margin:0;letter-spacing:-.5px}h1 span{color:var(--em)}
.sub{font-size:12px;color:var(--mut);margin-top:2px;font-family:ui-monospace,monospace}
.grid{display:grid;grid-template-columns:.85fr 1.15fr;gap:20px}@media(max-width:900px){.grid{grid-template-columns:1fr}}
.panel{border:1px solid var(--bd);background:rgba(17,24,39,.6);border-radius:12px;overflow:hidden}
.ph{padding:12px 16px;border-bottom:1px solid var(--bd);background:rgba(0,0,0,.2);display:flex;justify-content:space-between;align-items:center}
.ph h2{font-size:14px;margin:0}.ph .cnt{font-family:ui-monospace,monospace;font-size:12px;color:var(--em);border:1px solid rgba(16,185,129,.4);border-radius:999px;padding:4px 10px;background:rgba(0,0,0,.3)}
.body{padding:12px}
textarea{width:100%;height:40vh;min-height:220px;resize:none;font-family:ui-monospace,monospace;font-size:13px;color:#6ee7b7;background:rgba(0,0,0,.4);border:1px solid var(--bd);border-radius:8px;padding:12px;outline:none}
textarea:focus{border-color:var(--em)}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px}
button{cursor:pointer;border:none;border-radius:8px;font-weight:600;font-size:13px;padding:8px 12px;background:#1f2937;color:#e5e7eb;transition:transform .1s}
button:hover{background:#374151}button:active{transform:scale(.96)}
.primary{width:100%;margin-top:12px;height:44px;font-size:16px;background:var(--em);color:#052e1a}
.primary:hover{background:#34d399}.primary:disabled{opacity:.6;cursor:not-allowed}
label.sw{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--mut);margin-left:auto}
input[type=number]{width:56px;background:rgba(0,0,0,.3);border:1px solid var(--bd);color:#fff;border-radius:6px;padding:6px}
.metrics{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px}
.metric{border:1px solid var(--bd);background:rgba(0,0,0,.2);border-radius:10px;padding:10px 16px;min-width:100px}
.metric .l{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--mut);font-family:ui-monospace,monospace}
.metric .v{font-size:22px;font-weight:800}
.boxes{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:700px){.boxes{grid-template-columns:1fr}}
.box{border-radius:12px;border:1px solid var(--bd);background:rgba(17,24,39,.6);overflow:hidden;display:flex;flex-direction:column}
.box.ok{border-color:rgba(16,185,129,.5)}.box.bad{border-color:rgba(244,63,94,.5)}
.bx-h{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border-bottom:1px solid var(--bd);background:rgba(0,0,0,.2)}
.bx-h .t{font-size:13px;font-weight:600}.bx-h .t small{display:block;color:var(--mut);font-weight:400;font-size:11px}
.acts{display:flex;gap:6px;padding:8px 10px;border-bottom:1px solid var(--bd)}
.acts input{flex:1;background:rgba(0,0,0,.3);border:1px solid var(--bd);color:#fff;border-radius:6px;padding:6px 8px;font-size:12px;font-family:ui-monospace,monospace}
.list{height:42vh;min-height:240px;overflow:auto;padding:8px}
.item{border:1px solid rgba(55,65,81,.5);background:rgba(0,0,0,.2);border-radius:8px;padding:8px 12px;margin-bottom:6px}
.item .em{font-family:ui-monospace,monospace;font-size:13px}
.tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px;align-items:center}
.tag{font-size:10px;text-transform:uppercase;letter-spacing:.5px;font-family:ui-monospace,monospace;padding:2px 6px;border-radius:4px;border:1px solid}
.t-ok{background:rgba(6,78,59,.5);color:#6ee7b7;border-color:rgba(16,185,129,.4)}
.t-bad{background:rgba(76,5,25,.5);color:#fda4af;border-color:rgba(244,63,94,.4)}
.t-amber{background:rgba(69,45,3,.5);color:#fcd34d;border-color:rgba(245,158,11,.4)}
.t-cyan{background:rgba(8,51,68,.5);color:#67e8f9;border-color:rgba(6,182,212,.4)}
.reason{font-size:10px;color:var(--mut);margin-left:2px}.sug{font-size:10px;color:#f0abfc;margin-top:3px;font-family:ui-monospace,monospace}
.empty{text-align:center;color:var(--mut);font-family:ui-monospace,monospace;font-size:12px;padding:60px 0}
.dot{width:6px;height:6px;border-radius:50%;display:inline-block}
.foot{text-align:center;color:var(--mut);font-size:11px;font-family:ui-monospace,monospace;margin-top:26px}
.bar{height:4px;background:rgba(0,0,0,.4);border-radius:4px;overflow:hidden;margin-top:10px;display:none}
.bar>i{display:block;height:100%;width:40%;background:var(--em);animation:ind 1s linear infinite}
@keyframes ind{0%{margin-left:-40%}100%{margin-left:100%}}
</style></head><body><div class="wrap">
<div class="hd"><div class="logo">✉️</div><div><h1>MAIL<span>PULSE</span></h1>
<div class="sub">syntax · MX · live SMTP mailbox verification</div></div></div>
<div class="grid">
  <div class="panel">
    <div class="ph"><div><h2>Email Input Stream</h2><div class="sub">one per line · email or email:pass</div></div>
      <span class="cnt" id="cnt">0 loaded</span></div>
    <div class="body">
      <textarea id="inp" placeholder="paste emails here…&#10;john@example.com&#10;jane@company.io:pass123"></textarea>
      <div class="row">
        <button onclick="sample()">⚡ Sample</button>
        <button onclick="clr()">🗑 Clear</button>
        <label class="sw"><input type="checkbox" id="smtp" checked> SMTP verify</label>
        <label class="sw">Threads <input type="number" id="wk" value="10" min="1" max="20"></label>
      </div>
      <button class="primary" id="go" onclick="run()">▶ Validate Email Stream</button>
      <div class="bar" id="bar"><i></i></div>
    </div>
  </div>
  <div>
    <div class="metrics">
      <div class="metric"><div class="l">Total</div><div class="v" id="m-t">0</div></div>
      <div class="metric"><div class="l">Deliverable</div><div class="v" id="m-d" style="color:var(--em)">0</div></div>
      <div class="metric"><div class="l">Invalid</div><div class="v" id="m-i" style="color:var(--rose)">0</div></div>
      <div class="metric"><div class="l">Score</div><div class="v" id="m-s" style="color:var(--cyan)">0%</div></div>
    </div>
    <div class="boxes">
      <div class="box ok"><div class="bx-h"><div class="t">Deliverable & Valid<small>safe to send</small></div>
        <span class="cnt" id="c-ok">0</span></div>
        <div class="acts"><input id="f-ok" placeholder="filter…" oninput="render()">
          <button onclick="copyBox('ok')">Copy</button><button onclick="dl('ok')">CSV</button></div>
        <div class="list" id="l-ok"><div class="empty">Awaiting validation…</div></div></div>
      <div class="box bad"><div class="bx-h"><div class="t">Bounce / Invalid / Error<small>will bounce or fail</small></div>
        <span class="cnt" id="c-bad">0</span></div>
        <div class="acts"><input id="f-bad" placeholder="filter…" oninput="render()">
          <button onclick="copyBox('bad')">Copy</button><button onclick="dl('bad')">CSV</button></div>
        <div class="list" id="l-bad"><div class="empty">Awaiting validation…</div></div></div>
    </div>
  </div>
</div>
<div class="foot">MailPulse · single-file Python edition · amber tags = catch-all / greylisted / unverifiable</div>
</div>
<script>
const SAMPLE=`john.doe@gmail.com\nsupport@microsoft.com\ntest@mailinator.com:pw\ninvalid-email\nuser@gmial.com\nhello@yahoo.com\ninfo@nonexistentdomain-xyz-123.com\nadmin@stripe.com\nfoobar@@broken.com`;
let RESULTS=[];
const $=id=>document.getElementById(id);
const AMBER=new Set(["unknown","catch_all","risky","greylisted"]);
const TAGC={"Syntax Valid":"t-ok","MX Active":"t-ok","Mailbox Verified":"t-ok","Invalid Syntax":"t-bad","No MX Record":"t-bad","Mailbox Not Found":"t-bad","Disposable Domain":"t-amber","Catch-All":"t-amber","Unverified":"t-amber","Greylisted":"t-amber","Possible Typo":"t-amber","Role Account":"t-cyan"};
$("inp").addEventListener("input",()=>{const n=$("inp").value.split("\n").filter(x=>x.trim()).length;$("cnt").textContent=n+" loaded";});
function sample(){$("inp").value=SAMPLE;$("inp").dispatchEvent(new Event("input"));}
function clr(){$("inp").value="";RESULTS=[];render();$("inp").dispatchEvent(new Event("input"));}
async function run(){
  const emails=$("inp").value.split("\n").map(s=>s.trim()).filter(Boolean);
  if(!emails.length){alert("Paste at least one email");return;}
  $("go").disabled=true;$("bar").style.display="block";
  try{
    const r=await fetch("/api/validate",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({emails,smtp_check:$("smtp").checked,workers:+$("wk").value})});
    const d=await r.json();RESULTS=d.results;render();
  }catch(e){alert("Failed: "+e);}finally{$("go").disabled=false;$("bar").style.display="none";}
}
function render(){
  const ok=RESULTS.filter(r=>r.category==="deliverable"),bad=RESULTS.filter(r=>r.category==="invalid");
  const t=RESULTS.length,rate=t?Math.round(ok.length/t*100):0;
  $("m-t").textContent=t;$("m-d").textContent=ok.length;$("m-i").textContent=bad.length;$("m-s").textContent=rate+"%";
  $("c-ok").textContent=ok.length;$("c-bad").textContent=bad.length;
  paint("ok",ok,$("f-ok").value);paint("bad",bad,$("f-bad").value);
}
function paint(which,arr,q){
  q=(q||"").toLowerCase();const items=arr.filter(r=>!q||r.email.toLowerCase().includes(q)||r.reason.toLowerCase().includes(q));
  const el=$("l-"+which);
  if(!items.length){el.innerHTML='<div class="empty">'+(arr.length?"No matches":"Awaiting validation…")+'</div>';return;}
  const dc=which==="ok"?"var(--em)":"var(--rose)";
  el.innerHTML=items.map(r=>{
    const dot=AMBER.has(r.status)?"var(--amber)":dc;
    const tags=r.tags.map(t=>`<span class="tag ${TAGC[t]||'t-ok'}">${t}</span>`).join("");
    const sug=r.suggestion?`<div class="sug">↳ did you mean ${esc(r.suggestion)}?</div>`:"";
    return `<div class="item"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
      <span class="em">${esc(r.email)}</span><span class="dot" style="background:${dot}"></span></div>
      <div class="tags">${tags}<span class="reason">${esc(r.reason)}</span></div>${sug}</div>`;
  }).join("");
}
function esc(s){return (s||"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}
function copyBox(which){
  const arr=RESULTS.filter(r=>r.category===(which==="ok"?"deliverable":"invalid"));
  if(!arr.length){alert("Nothing to copy");return;}
  navigator.clipboard.writeText(arr.map(r=>r.email).join("\n"));
  alert("Copied "+arr.length+" emails");
}
function dl(which){
  const arr=RESULTS.filter(r=>r.category===(which==="ok"?"deliverable":"invalid"));
  if(!arr.length){alert("Nothing to download");return;}
  const csv="email,status,reason\n"+arr.map(r=>`${r.email},${r.status},"${r.reason}"`).join("\n");
  const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([csv],{type:"text/csv"}));
  a.download=(which==="ok"?"deliverable":"invalid")+"-emails.csv";a.click();
}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, HTML, "text/html; charset=utf-8")
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/api/validate":
            self._send(404, json.dumps({"error": "not found"})); return
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or "{}")
            emails = data.get("emails") or []
            if not emails:
                self._send(400, json.dumps({"error": "no emails"})); return
            results = validate(emails, bool(data.get("smtp_check", True)),
                               data.get("workers", 10), bool(data.get("dedupe", True)))
            self._send(200, json.dumps({"results": results}))
        except Exception as ex:
            self._send(500, json.dumps({"error": str(ex)}))

    def log_message(self, *a):  # quiet
        pass


if __name__ == "__main__":
    print(f"MailPulse running →  http://localhost:{PORT}   (Ctrl+C to stop)")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
