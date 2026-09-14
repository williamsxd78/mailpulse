# MailPulse — Email Validator (PRD)

## Original Problem Statement
Inspired by reacher.email. Input a list of emails (one per line) on one side; on the other side, two output boxes — one for bounce/invalid/error emails, one for perfect/deliverable emails — each with copy + download buttons, plus concurrency ("thread") for checking.

## User Choices
- Validation depth: syntax + MX record based (NO SMTP probing).
- Save check history to DB: Yes.
- Input format: one email per line, simple.
- Access: public, no login.
- Concurrency: fixed 12 workers, no user control.

## Architecture
- Backend: FastAPI + Motor (MongoDB), dnspython for MX lookups. Concurrency via asyncio + threadpool (semaphore, MAX_WORKERS=12). MX results cached per domain.
- Frontend: React (CRA/craco), Tailwind + shadcn/ui, sonner toasts, lucide icons. Dark carbon/emerald/rose theme, Sora/Chivo/JetBrains Mono fonts.

## Classification Logic (backend/server.py `_validate_one`)
- invalid_syntax → invalid box (malformed)
- disposable → invalid box (throwaway domains list)
- no_mx → invalid box (domain has no MX; A-record fallback)
- risky → deliverable box (role account e.g. info@/support@)
- deliverable → deliverable box (valid + active MX)
- Typo suggestions for common domain misspellings (gmial.com → gmail.com)

## API
- POST /api/validate {emails[], name?, dedupe} → BatchDetail (saves batch)
- GET /api/history → list of BatchSummary (recent first)
- GET /api/history/{id} → BatchDetail
- DELETE /api/history/{id}

## Implemented (2026-06)
- Dual-console workspace: input stream (textarea, batch name, dedupe, sample, clear, file upload) + two categorized result boxes.
- Per-email status tags/reason, metrics bar (total/deliverable/invalid/score), animated progress.
- Copy + CSV download per box, search filter per box.
- Check history slide-over (load / re-run / delete).
- Verified: testing agent 100% backend + 100% frontend (iteration_1).

## Backlog
- P1: max emails hard limit surfaced in UI; pagination for history.
- P2: CSV column mapping on upload; catch-all domain detection; per-item DNS timeout surfacing.
- P2: LRU/TTL on MX cache.
