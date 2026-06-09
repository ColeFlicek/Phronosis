# ACIP — Business Case & Commercialization Analysis

> **Status:** Pre-commercial. Step 1 is proving measurable effectiveness (see bottom).
> This document captures the commercial opportunity if the tool proves out.

---

## What ACIP Actually Sells

ACIP is not a code search tool. Code search is free and commoditized. ACIP sells three things that don't exist elsewhere in this form:

**1. Persistent organizational memory**
Decision history that survives team turnover, context window limits, and agent session boundaries. Once a team has 18 months of decision history in ACIP, that institutional knowledge belongs to the organization, not to any individual or any AI session.

**2. Token economics for AI-heavy teams**
A developer using Claude Code heavily burns tokens on file reads to understand architecture. ACIP replaces 10 file reads with 1 MCP call. At the rate AI coding is scaling, this becomes a meaningful cost reduction — and more importantly, a quality improvement (the MCP answer is often more complete than the file read).

**3. Multi-agent coordination substrate**
As AI coding scales beyond one agent per developer, teams need a shared nervous system — a place where agent A's work is visible to agent B before B touches the same code. ACIP is that layer. No competitor is doing this at the MCP protocol level today.

**4. Governance layer (Invariant Contracts)**
The contract enforcement system is a compliance/audit product. Enterprise security teams have separate budgets for this. It's sellable independently of the dev productivity story.

---

## Cost Structure

### Variable Costs (LLM API)

Every customer's codebase must be indexed (embedded + summarized). These are the primary variable costs.

**Embedding:** OpenAI `text-embedding-3-small` at $0.02 per 1M tokens.
An average function is ~200 tokens. 1,000 functions = $0.004 to embed once.

**Summarization:** Claude Haiku at ~$0.30 per 1,000 functions (800 tokens in, 80 out per function).

Hash-diffing means only changed functions re-embed on each commit. Monthly costs are roughly 10% of the initial index cost.

| Customer Size | Functions | Initial Cost | Monthly Ongoing |
|---|---|---|---|
| Small startup | 5K | ~$1.80 | ~$0.18 |
| Mid-size team | 50K | ~$18 | ~$1.80 |
| Large company | 200K | ~$72 | ~$7.20 |
| Enterprise (1M+) | 1M+ | ~$360 | ~$36 |

### Infrastructure Costs

The current SQLite + sqlite-vec architecture is extremely cost-efficient. A $60/month dedicated server (Hetzner CX42) handles 100–300 concurrent tenants comfortably. SQLite per customer provides natural isolation with no database server overhead.

At 500 customers: $200–400/month infrastructure. Under $1/customer/month.

### Margin by Tier

| Tier | Monthly Price | COGS | Gross Margin |
|---|---|---|---|
| Pro | $29 | $3–5 | 83–90% |
| Team | $99 | $12–20 | 85–90% |
| Business | $299 | $40–80 | 87–91% |
| Enterprise | $2,000–8,000 | $150–400 | 88–95% |

These are standard SaaS-quality margins.

---

## Pricing Model

**Project-based tiers, not per-seat.**

Per-seat pricing fails here: one developer running multiple AI agents generates more load than ten humans using a traditional code search tool. Per-project pricing aligns with actual resource consumption and perceived value.

| Tier | Price | Limits | Target Customer |
|---|---|---|---|
| **Free** | $0 | 1 project, 5K functions, 30-day history | Solo evaluation |
| **Pro** | $29/month | 5 projects, 50K functions, unlimited history | Freelancers, solo AI-heavy devs |
| **Team** | $99/month | 20 projects, 200K functions, Slack support | Startups, growing teams |
| **Business** | $299/month | Unlimited projects, 500K functions, SLA, SSO | Mid-market engineering orgs |
| **Enterprise** | $2,000–8,000/month | On-prem option, custom LLM providers, audit logs, dedicated support | Fortune 500 |

**Why these numbers:**
- Pro at $29 sits below Cursor ($20) + Linear ($8/seat) on a per-tool basis — lands in "another reasonable dev subscription" territory.
- The Team → Business jump from $99 to $299 is intentional: that delta qualifies a buyer as serious and funds proper support.
- Enterprise pricing is positioned against Sourcegraph Enterprise ($19/seat/month — a 5,000-person org pays $95K/month). A $5–8K/month on-prem ACIP deal looks cheap by comparison and offers things Sourcegraph doesn't.

---

## Deployment Architecture at Scale

### Phase 1: 0–200 Customers (Extend What Exists)

Minimal changes to the current architecture:
- Add authentication (Clerk or Auth0, ~$50/month at this scale)
- Add Stripe billing with usage metering
- SQLite file per customer, backed up to Cloudflare R2 object storage (~$0.015/GB)
- Rate limiting per API key at the FastMCP layer
- One or two servers behind a load balancer

**Infrastructure cost:** $200–400/month. Margins exceed 85% from day one.

### Phase 2: 200–2,000 Customers (Sharding)

- Route customers to server shards by hashed org ID
- SQLite files on network-attached volumes (Hetzner, ~$0.05/GB/month)
- Separate indexing workers (the LLM-heavy part) from the MCP query server
- Job queue (Redis + workers) so indexing doesn't block queries
- Begin offering dedicated instances for Business tier customers

**Infrastructure cost:** $1,500–3,000/month

### Phase 3: 2,000+ Customers (Managed Tenancy)

- Each customer's SQLite DB migrates to Turso (serverless SQLite) or dedicated pgvector on a managed database
- sqlite-vec KNN latency degrades past ~5M vectors per table. Most codebases stay well under this (10K functions × 1,536 embedding dimensions = ~60MB per project). The architecture survives.
- The key insight: most large engineering orgs run microservices. A 500-person org with 200 repos at 2K functions each keeps each vec table tiny. The scaling story is better than it looks.

---

## The MEGA User

A MEGA user: 5,000+ developers, 50+ codebases, 2M+ functions, data residency requirements, SOC 2, custom LLM provider, on-prem deployment.

### Technical Challenges and Solutions

**Vector scale at 1M+ functions across all repos:**
Never do cross-project KNN at this scale. Each repo stays isolated — ACIP already enforces per-project vec tables. The architecture survives unchanged.

**Custom LLM provider:**
A financial institution cannot send code to OpenAI. They need Azure OpenAI or Anthropic Bedrock. The `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` config already abstracts the provider. Add `azure` and `bedrock` as options; charge for integration work.

**On-prem deployment:**
Package as a Docker Compose stack (already done) with a production install script. They run it in their VPC. Deliver updates via a private container registry. COGS drops to near zero (they pay their own LLM costs); you're selling software and support.

**Audit logging:**
Every query needs to be logged to their SIEM — who called `get_decision_history`, on what function, when. Add an `audit_log` table and a webhook stream. This is a $500–1,000/month line item for enterprise procurement.

**SSO/SAML:**
Required by virtually every enterprise IT department. WorkOS or Clerk handles this at ~$1/seat/month. Bundle into Enterprise tier pricing.

**What you charge the MEGA user:** $5,000–12,000/month.
Their procurement teams have this budget for developer tools. You are replacing or supplementing Sourcegraph Enterprise. Your on-prem deal at $8K/month looks cheap by comparison and offers something Sourcegraph doesn't: MCP-native agent coordination and decision memory.

---

## Revenue Scenarios

| Scenario | Customer Mix | MRR | ARR |
|---|---|---|---|
| Launched, early traction | 50 Pro, 20 Team | $3,430 | $41K |
| Anthropic listing / partnership | 200 Pro, 80 Team, 20 Business | $15,780 | $189K |
| First enterprise deal closes | Above + 1 MEGA | $23,780 | $285K |
| Real go-to-market motion | 500 Pro, 200 Team, 50 Business, 5 MEGA | $66,500 | $798K |

**Path to $1M ARR:** approximately 600–700 paying customers. Achievable in 18–24 months with proper distribution.

---

## Defensibility

**The existential risk:** Anthropic ships a native version of this inside Claude Code.

**Why that's not fatal:**

1. **Decision memory is proprietary data.** A customer's two years of decision history doesn't migrate to a new tool. The switching cost is real and grows with use.

2. **You move faster on the niche.** Anthropic is building a general coding assistant. You're building the enterprise governance and coordination layer. Different problems.

3. **On-prem is a structural moat.** Anthropic will not offer on-prem deployments for security-conscious enterprises. You will.

4. **The MCP ecosystem is open.** Even if Claude Code adds basic code indexing natively, Invariant Contracts, multi-agent coordination, and the decision memory substrate are differentiated enough to survive alongside it.

The core defensibility is institutional memory accumulation. Once a customer has 18 months of decision history in ACIP, they don't leave.

---

## What Needs to Be Built for SaaS

The product is functionally complete. The gap is the SaaS wrapper:

| Component | Effort | Notes |
|---|---|---|
| Authentication | Medium | Clerk or Auth0; API key per org |
| Billing | Medium | Stripe; per-project metering |
| Usage limits enforcement | Low | Rate limiting + function count caps at MCP layer |
| Admin dashboard | Medium | Customer health, usage, billing status |
| Multi-tenant isolation hardening | Low | Already architecturally isolated; needs audit |
| Data export / portability | Low | GDPR compliance; dump SQLite per customer |
| SSO / SAML | High | WorkOS; needed for Business+ tier |
| Audit logging | Medium | Append-only log + webhook stream |
| Azure / Bedrock LLM support | Medium | Config abstraction already exists |
| On-prem packaging | Low | Docker Compose already exists; needs installer |

---

## Go-to-Market

**Primary channel: Claude Code ecosystem**

ACIP is an MCP server for Claude Code. The target buyer is already using Claude Code and already experiencing the problem ACIP solves (lost context, repeated file reads, no cross-session memory). Distribution through:

- Anthropic's MCP server directory (submit and maintain)
- Claude Code community (Discord, Reddit, Twitter/X)
- GitHub — the repo itself, properly documented

**Secondary channel: Developer-focused content**

The benchmark comparison (ACIP vs. no ACIP on real tasks) is the clearest marketing asset. A measurable answer to "does this actually make AI coding better?" converts skeptics.

**Enterprise channel:**

Inbound from developer-led adoption. A developer at a large company uses ACIP personally, shows it to their team, team shows it to their manager. Standard bottom-up B2B motion.

---

## Step 1: Proving Functionality

**Before any of the above matters, the tool has to demonstrably work.**

The question to answer: *Is there a measurable difference in AI coding effectiveness with ACIP vs. without it?*

This means running a structured benchmark:
- Same complex coding tasks, same codebase
- Agent A: Claude Code with ACIP (MCP queries for architecture, pre-edit gates, decision history)
- Agent B: Claude Code without ACIP (file reads and grep only)
- Measure: task completion rate, errors introduced, tokens consumed, correct architectural decisions

A compelling benchmark is the single most valuable thing this project can produce right now. It is the proof-of-concept, the marketing asset, and the product roadmap signal all in one.

The `/acip-benchmark` skill in Claude Code runs a structured 5-question comparison against a real indexed codebase. Running this against a nontrivial project (not ACIP itself) and publishing the results is Step 1.
