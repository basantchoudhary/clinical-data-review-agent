# Architecture decisions

The decisions that shape the clinical data review agent. Each one records the
options considered, what was chosen, why, and what it costs. **Decided by:**
Shalini, with Claude recommending. A decision changes only by a new entry that
replaces it, never by editing the old one.

| # | Decision | Status |
|---|---|---|
| D1 | The boundary: rules first, the agent only for cross-form review | Decided 27 Oct 2026 |
| D2 | The unit of work: one patient per agent run | Decided 27 Oct 2026 |
| D3 | Where the agent reads from: lakehouse snapshot, re-checked in OpenClinica at write time | Decided 27 Oct 2026 |
| D4 | The agent's tools: a patient summary up front plus narrow read-only tools; no SQL | Decided 27 Oct 2026 |
| D5 | How a query leaves: draft, approval, a separate writer | Open |
| D6 | Which Claude surface, and where the model runs | Open |
| D7 | What the model may see: minimisation, free text as untrusted | Open |
| D8 | How we prove it works before anyone trusts it | Open |

---

## D1. The boundary: rules first, the agent only where rules cannot reach

**Decided:** 27 Oct 2026.

**Context.** Trial data cleaning has two kinds of checking:
- **Edit checks** look at one field or one form, and give the same answer every time.
- **Data review** reads the whole patient across forms and visits, and decides what is worth asking.

Only data review passes all four tests for an agent:
1. The path is not known in advance.
2. It needs several sources.
3. Judgement is the hard part.
4. A person can catch its mistakes before anything leaves.

**Decision.**

| Piece | Built as |
|---|---|
| Loading, transforming, SDTM-aligned layers | Pipeline code |
| Edit checks (range, missing, impossible dates) | Data-quality rules in the pipeline |
| Ranking which patients to review first | A score computed from the rule hits |
| Reviewing one patient across forms, drafting queries | The agent |
| Approving and sending a query | A person |

**Why.** Rules are exact, cheap and easy to explain to an auditor. Keeping them as rules puts the agent's cost and risk only where judgement is needed.

**Cost.** The rules alone catch less than an agent let loose on everything would. We accept that.

**In Shalini's words:** *(to write)*

---

## D2. The unit of work: one patient per agent run

**Decided:** 27 Oct 2026.

**Options.**

| Option | Verdict | Reason |
|---|---|---|
| **One patient: the whole record** | **Chosen** | Matches how a reviewer thinks; runs are independent, so they can run in parallel, be retried and be audited one by one |
| One rule hit | Dropped | Loses the cross-form story. In Lesson 1, the eligibility query came from looking beyond the ALT flag. |
| One site, or the whole study | Dropped for v1 | Huge context, hard to audit, one failure loses everything. Site-level patterns are better found by rules over the agent's outputs. |

**Why.** The value is in the story across forms. A smaller unit loses it; a bigger one cannot be audited.

**Cost.** A patient with a long record costs more per run. The per-patient budget (see D8) caps it.

**In Shalini's words:** *(to write)*

---

## D3. Where the agent reads from: review a snapshot, verify at write time

**Decided:** 27 Oct 2026.

**Options.**

| Option | Verdict | Reason |
|---|---|---|
| A. Curated lakehouse tables only | Good, not enough | Reproducible and light on the EDC, but could post a query about a value the site has since fixed |
| B. OpenClinica live, through its API | Dropped | Fresh, but hard to show what the agent saw; every tool call loads a clinical production system; raw form structure is harder to reason over |
| **C. Lakehouse for review, OpenClinica re-checked at write time** | **Chosen** | Reproducible like A, and never posts a stale query |

**Decision.**
- The agent reads only curated, SDTM-aligned tables, through a read-only identity, from one stamped snapshot.
- When an approved query is about to be posted, the writer re-reads that one field in OpenClinica.
- If the value has changed since the snapshot, the writer does not post. The draft goes back as "stale, re-review".

**Why.** An auditor can be shown exactly what the agent saw: the snapshot and the rows it read. And no site is ever asked about something it has already fixed.

**What it requires of the data layer.**
1. **Lineage to the source.** Every curated row carries OpenClinica's identifiers: study subject, event, form, item, and the item value ID. A query has to point at an exact field in OpenClinica.
2. **Snapshot stamps.** Every load gets a snapshot ID and time. Every agent run records which snapshot it read.

**Cost.** More moving parts:
- The writer needs the re-check, and a path for stale drafts.
- The pipeline must carry lineage and snapshot IDs.
- Reviews run on data that may be hours old.

We accept these because they are what makes the design production-grade rather than a demo.

**In Shalini's words:** *(to write)*

---

## D4. The agent's tools: a summary up front, then narrow read-only tools

**Decided:** 27 Oct 2026.

**Options.**

| Option | Verdict | Reason |
|---|---|---|
| A. Narrow named tools only | Good | Least privilege, clear audit, testable; a missing tool means a missing check |
| B. One SQL tool over the lakehouse | Dropped | Can read other patients or the treatment arm; confident wrong answers from bad SQL; the audit shows SQL, not intent |
| C. The whole record in the prompt, no tools | Partly | Simple and fits in context, but not agentic, cannot reach the protocol or earlier queries, and pays full cost for clean patients |
| **D. A one-page summary up front, plus narrow tools to drill down** | **Chosen** | Most patients need a couple of calls; the agentic effort goes where it pays, such as the protocol check |

**The tools.**
- **Read:** `patient_summary`, `lab_trend`, `adverse_events`, `medications`, `vital_signs`, `disposition`, `rule_hits`, `prior_queries`, `protocol_section`.
- **Draft:** `propose_query`. It writes to the drafts table only.

**Four rules the tools follow.**
1. **The patient is fixed by the run.** No tool takes a patient ID; the harness binds the patient when the run starts. The agent cannot read anyone else, whatever the prompt says.
2. **The agent stays blinded.** The treatment arm never appears in any tool output, as for any reviewer in a blinded trial.
3. **Code does the arithmetic, the model does the judgement.** Multiples of the normal limit, days between dates and screening flags are computed in the tools and handed over as facts.
4. **Every fact carries its source IDs.** Tool results include the lineage IDs from D3, so each piece of query evidence points at an exact OpenClinica field.

**Cost.**
- Tools must be designed, tested and versioned.
- A check the tools do not support cannot be done until a tool is added. A run that hits such a gap must say "could not check" rather than guess.

**In Shalini's words:** *(to write)*
