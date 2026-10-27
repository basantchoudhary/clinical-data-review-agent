# Findings

What building this agent found, and where each finding is routed. A finding
that belongs to a framework is fixed **in that framework**, released as a new
version and re-pinned here, never patched around in this repository.

| # | Date | Finding | Belongs to | Routed |
|---|---|---|---|---|
| F-1 | 27 Oct 2026 | `agent_harness` `Message` and `ModelResponse` carry text only, so Claude Opus 5.5's thinking blocks cannot be passed back unchanged in a tool loop, which the model requires | Agent Harness (`contracts/model.py`, `loop/__init__.py:221`) | To do |
| F-2 | 27 Oct 2026 | Context assembly trims the middle of the transcript past 24,000 characters (`context/__init__.py:173`), and the limit cannot be set per agent. Opus 5.5 rejects requests whose earlier messages changed (preserved thinking). A job needs an append-only mode that stops on a budget instead. | Agent Harness; AHC L1 | To do |
| F-3 | 27 Oct 2026 | No Anthropic adapter for the `llm` port; the only adapters speak the OpenAI wire | Agent Harness (`llm/`, `adapters/model.py`) | To do |
| F-4 | 27 Oct 2026 | `ModelRequest.temperature` defaults to 0 ("determinism is the floor"), but Opus 5.5 rejects any sampling parameter. Determinism on current models comes from recorded responses and replay, not temperature. | Agent Harness; AHC L9 | To do |
| F-5 | 27 Oct 2026 | `Budgets.max_tool_result_chars` is never applied to in-process `LocalTool` results; `loop/spend.py` drops cached input tokens from the run total; `cost.PRICES` has no Claude rows | Agent Harness | To do |
| F-6 | 27 Oct 2026 | Blinding needs more than dropping arm columns: the exposure domain's dose (0, 54 or 81 mg) reveals the arm. AAC has no obligation for concealed fields such as treatment assignment. | AAC (candidate new obligation) | To propose |
| F-7 | 27 Oct 2026 | A dataset-wide gap (no consent dates in this study) would make the agent raise the same query for every patient. Study-wide known gaps need to be declared once and handed to the agent as context. | This agent (study notes); AgentTwin world design | Done here |
| F-8 | 27 Oct 2026 | `loop.run` requires an `Identity` with a `customer_id` and a `ToolClient` even when every tool is local: conversation assumptions in a job-shaped agent | Agent Harness | To do |
