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
| D5 | How a query leaves: agent drafts, a person approves, a separate writer posts | Decided 27 Oct 2026 |
| D6 | Our own loop on the Anthropic SDK; Databricks Model Serving as the target, Foundry as fallback; Opus 5.5 first | Decided 27 Oct 2026 |
| D7 | What the model may see: minimised, PII-scanned, free text marked untrusted, the structure contains the damage | Decided 27 Oct 2026 |
| D8 | Proof: planted problems, a labelled real sample, cheapest checks first, release gates, then shadow mode | Decided 27 Oct 2026 |
| D9 | Code structure: ports and adapters like the reference agents; the harness installed by version | Decided 27 Oct 2026 |

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

---

## D5. How a query leaves: the agent drafts, a person approves, a separate writer posts

**Decided:** 27 Oct 2026.

**Options.**

| Option | Verdict | Reason |
|---|---|---|
| A. The agent posts directly to OpenClinica | Dropped | No human check; the agent would need write access to a clinical system |
| B. The agent drafts, a person approves, the agent posts | Dropped | The agent still holds write credentials; a bug or a prompt injection could post anyway |
| **C. The agent drafts, a person approves, a separate writer posts** | **Chosen** | Three parts, each with only the access it needs |

**Decision.**
1. **The agent** writes drafts to a table. It holds no OpenClinica credentials.
2. **A data manager** reviews each draft on a review screen, with its evidence rows beside it. They approve it, edit and approve it, or reject it with a reason. The screen is a small Databricks App.
3. **The writer** is a plain program whose only OpenClinica permission is to create a discrepancy note. It re-checks the field (D3), posts the note, and stores OpenClinica's note ID on the draft.
4. **Each draft has a unique key**, so a retry never posts the same query twice.

**Why.**
- Nothing reaches a site without a named person approving it.
- The one component that can write to OpenClinica contains no model.

**Side benefit.** Two things become measures of the agent's quality for D8, at no extra effort:
- the difference between what the agent drafted and what was sent;
- the reason given for every rejection.

**Cost.** Three components to build instead of one: the review screen, the writer, and the approver rules.

**In Shalini's words:** *(to write)*

---

## D6. Which Claude, called how, and where the model runs

**Decided:** 27 Oct 2026.

**6a. How we call Claude: our own loop on the Anthropic Python SDK (Messages API with tool use).**

| Option | Verdict | Reason |
|---|---|---|
| **Our own loop on the Anthropic SDK** | **Chosen** | About 100 lines; every step visible and logged; the D4 tool rules are enforced in our code |
| The SDK's Tool Runner | Possible | Same API, less code, but hides the mechanism we want to own and explain |
| Claude Agent SDK | Dropped | Built for coding agents; its built-in bash and file tools are the wrong shape next to trial data |
| Claude Managed Agents | Dropped | Trial data would leave the platform for an Anthropic-hosted sandbox |

**6b. Where the model runs: behind one swap point.**

| Stage | Route |
|---|---|
| While building | Anthropic's API directly |
| **Target at a sponsor on Azure Databricks** | **Databricks Model Serving** |
| Fallback | Claude in Microsoft Foundry, if the company's AI governance requires it (for example a central Azure API Management gateway for all AI traffic), or if Claude is approved there but not enabled in the Databricks workspace |

Moving between routes changes the address and the credential only, not the code.

**Why Model Serving is the target.** Everything else the agent touches already lives in Databricks: the curated tables and snapshots (D3), the read-only identity (D4), and the drafts table and review app (D5). With Model Serving the agent has:
- one platform and one identity model, using a service principal instead of a separate API key;
- one audit trail, with model requests and responses logged to lakehouse tables beside the data;
- cost per patient in one place;
- no new vendor onboarding, since it is covered by the existing Databricks agreement.

**6c. Which model.** Claude Opus 5.5 first, because judgement is the hard part. Sonnet 5.5 and Haiku 5.5 are measured on the same test patients once the D8 evals exist, and the choice is made on that evidence.

**Cost.**
- Model Serving can lag Anthropic's API on new features and models, and its pricing and rate limits follow Databricks' terms.
- Availability depends on cloud and region. It was not confirmed on Free Edition, which is why the build uses the direct API.
- First estimate: about $0.15 to $0.30 per patient with prompt caching. To be measured on the first few patients before a larger run.

**The first question at a real company:** "Which route is already approved and enabled?" The architecture is the same either way.

**In Shalini's words:** *(to write)*

---

## D7. What the model may see

**Decided:** 27 Oct 2026.

**Options.**

| Option | Verdict | Reason |
|---|---|---|
| A. Whatever the tools return | Dropped | Free text can hold names typed by site staff, and any text can carry instructions |
| C. No free text at all | Dropped | Free text matters, for example a verbatim term that does not match its coded term |
| **B. Minimise, scan, mark untrusted** | **Chosen** | Four rules, below |

**Four rules.**
1. **Minimise by design.** Tools return a subject ID, never a name; an age, never a birth date; never the treatment arm (D4).
2. **Scan free text before the model sees it.** A PII detector (Presidio, through the Eval Harness) masks names, phone numbers and emails, and logs each masking.
3. **Free text is data, never instructions.** Site-entered text is wrapped in marked untrusted blocks, and the system prompt treats it as evidence only.
4. **The structure contains the damage.** Even a successful injection can read only one patient (D4) and produce only a draft a person approves (D5). Rules 1 to 3 are a second line of defence; safety does not rest on the prompt.

**Recorded, not solved here.**
- Logged model requests and responses contain trial data. They get the same access controls and retention as the trial data.
- Provider terms: under Anthropic's commercial API terms, inputs are not used for training, and enterprises can arrange zero data retention. A sponsor confirms current terms in its governance review; on Databricks Model Serving the Databricks agreement applies.

**Obligations satisfied.** AAC-0006, AAC-0058, AAC-0106.

**In Shalini's words:** *(to write)*

---

## D8. How we prove it works before anyone trusts it

**Decided:** 27 Oct 2026.

**Options.**

| Option | Verdict | Reason |
|---|---|---|
| A. Look at some outputs by eye | Dropped | A number never measured cannot be defended |
| B. Planted problems only | Not enough | Measures finding, not whether the queries are worth sending |
| **C. Planted problems, a labelled real sample, checks cheapest first, release gates, then shadow mode** | **Chosen** | Measures finding, usefulness, safety and cost |

**Decision.**

1. **Planted problems (AgentTwin).** A copy of the pilot trial with about 30 known inconsistencies of different kinds, plus clean patients that should get no query. This gives:
   - recall: how many planted problems were found;
   - false alarms: queries raised on clean patients.
2. **A labelled real sample.** About 20 real pilot patients. Every draft is labelled *worth sending* or *not*, with a reason. **Shalini labels them.** The first is 01-705-1186.
3. **Checks, cheapest first.**
   - **Deterministic, every run, must be 100%:** every evidence ID exists in the snapshot; the draft matches the schema; no treatment arm and no personal data. A failure blocks release.
   - **Claude as judge** of "worth sending": advisory until its verdicts agree with Shalini's labels on the real sample, then counted.
   - **Repeat runs:** each test patient runs 3 times, to measure consistency (AAC-0010).
4. **Release gates, set in advance.** A version ships only if all of these hold:
   - at least 80% of planted problems found;
   - at least 70% of drafts judged worth sending;
   - zero blinding or privacy failures;
   - at most $0.30 per patient;
   - no worse than the previous version.
5. **Shadow mode at a real sponsor.** The agent first drafts alongside human reviewers, sending nothing, until agreement is measured. It never earns sending without approval without measured evidence for that decision (AAC-0118).

**Budget.** About 40 patients × 3 runs × about $0.25 is roughly $30 of the API credit.

**Cost.** Building the planted world and labelling the real sample takes real time, including Shalini's labelling hours.

**Obligations addressed.** AAC-0001, AAC-0010, AAC-0013, AAC-0014, AAC-0118.

**In Shalini's words:** *(to write)*

---

## D9. Code structure: ports and adapters, like the reference agents

**Decided:** 27 Oct 2026.

**Decision.** The agent repository is a thin package holding only what is this domain's, on top of the installed `agent_harness` library, the same as the clothing (AG-001) and motor claims (AG-002) agents. Every outside system sits behind a port; YAML picks the adapter per environment.

```
spec/clinical-review.aoas.yaml   the contract: tools, rules, limits
harness-profile.yaml             AHC: what fills each of the 16 layers
aac.config.yaml                  AAC: which obligations apply, how each is checked
gates.yaml                       the four gates
config/local.yaml, test.yaml, databricks.yaml   port-to-adapter bindings
pipeline/                        Databricks bundle: layers, edit checks, ranking, snapshots, lineage
src/clinical_review/             the tools, the query schema, blinding and PII rules, the one-patient run
src/edc_writer/                  the only code that writes to OpenClinica; the agent may not import it
src/review_app/                  the approval screen (Databricks App)
worlds/                          AgentTwin: the simulated trial with planted problems
evals/                           Eval Harness checks
tests/                           contract tests per port, and scenarios
```

**Ports this agent binds.**

| Port | Adapters |
|---|---|
| Trial data | local parquet (development, tests); Databricks curated tables |
| EDC | fake (tests); OpenClinica (the writer only) |
| Model (`llm`) | Anthropic API; Databricks Model Serving; scripted (tests) |
| PII scanner | Presidio; pass-through (tests on synthetic data) |
| Drafts and approvals | local store (tests); Databricks tables plus the review app |

The same contract tests run against every adapter of a port, so a drift between the Databricks tables and what the tools expect fails a test instead of misleading the agent.

**Installed by version.** `agent_harness`, `agenttwin` and `evalharness` are pinned to tagged versions from GitHub, not local paths, per the one-repository-per-agent decision of 26 Oct 2026.

**What this agent tests in the harness.**
1. **The first Anthropic adapter for the `llm` port** (the planned Claude-family cycle). The harness owns retries, so the adapter sets the Anthropic SDK's `max_retries=0`. The SDK otherwise retries twice on its own, and one patient could quietly cost three calls.
2. **The first agent that is a job, not a conversation.** Parts built for customer chat (channel, portal, escalation) may not apply. Anything that does not fit is reported back to the harness as a finding.

**Cost.** We must tag and publish versions of the three libraries before this agent can pin them, and the Anthropic adapter is new code with its own contract tests.

**In Shalini's words:** *(to write)*

---

# Coverage against the catalogs (27 Oct 2026)

Checked against **AHC's 16 layers** (what must exist) and the **65 AAC obligations** that apply to a tool-using agent (what must be true). Updated as decisions close gaps.

| AHC layer | Covered by | Status |
|---|---|---|
| L1 Context assembly | D4, D7 | Partly. Missing: a size cap on tool results (AAC-0105), prompt versioning |
| L2 Model invocation | D6 | Partly. Missing: timeouts, retry policy, refusal handling, provider-failure fallback (AAC-0009) |
| L3 Tool layer | D4 | Covered. Still: tool errors and empty results (AAC-0053) |
| L4 Control loop | D6 | Partly. Missing: hard termination (AAC-0055), loop detection (AAC-0109), a "could not check" ending |
| L5 State and memory | D2, D4 | Partly. Stateless across runs by choice; to be recorded |
| L6 I/O contracts | D4 | Partly. Missing: a strict `propose_query` schema with required evidence (AAC-0002) |
| L7 Policy enforcement | D4, D5, D7 | Covered. Add: guardrails fail closed (AAC-0091) |
| L8 Concurrency and flow control | — | **Gap** |
| L9 Determinism and replay | D3 | Partly. Missing: recorded model responses, pinned model, prompt and tool versions (AAC-0012, AAC-0059) |
| L10 Failure handling | D3, D5 | Partly. Missing: a run that dies halfway (AAC-0046) |
| L11 Observability | — | **Gap** (AAC-0011, AAC-0060) |
| L12 Eval harness | D8 | Covered (design); to be built |
| L13 Cost accounting | D8 | Partly. Cost per patient is a release gate; missing: a hard per-run spend ceiling (AAC-0093) |
| L14 Human in the loop | D5 | Covered. Autonomy widens only on measured agreement (AAC-0118) |
| L15 Release and configuration | D8 | Partly. Regression gate set; missing: version pinning and the evaluated-equals-served check (AAC-0012, AAC-0107) |
| L16 Identity and authorization | D4, D5 | Covered. Add: who may approve |

**Obligations already satisfied by decisions:**

| Obligation | Satisfied by |
|---|---|
| AAC-0113 Action on a stale read | D3 |
| AAC-0057 Least privilege is enforced server-side | D4 |
| AAC-0029 Every claim is supported by retrieved context | D4 |
| AAC-0056 Destructive actions are gated | D5 |
| AAC-0047 Retried steps are idempotent | D5 |
| AAC-0006 No leakage of PII, secrets or credentials | D7 |
| AAC-0058 Injection arriving through tool output | D7 |
| AAC-0106 The system prompt is not a security boundary | D7 |
