"""The labelling page (D8): a person judges each draft, and the judgement is evidence.

    python -m clinical_review.labeling          # then open http://127.0.0.1:8765

Shows every draft with the exact records it cites, resolved from the snapshot.
Each label is appended to `labels/labels.jsonl` the moment it is saved:
worth sending or not, a reason, and the query as it would actually be sent.
The difference between the agent's draft and the sent text measures its
wording; the reasons measure its judgement.
"""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pandas as pd

from clinical_review.data import ParquetTrialData

ROOT = Path(__file__).resolve().parents[2]
DRAFTS = ROOT / "runs" / "drafts.jsonl"
LABELS = ROOT / "labels" / "labels.jsonl"

REASONS = [
    ("worth", "Worth sending as written"),
    ("worth_edited", "Worth sending, after editing the wording"),
    ("not_relevant", "Not worth it: clinically irrelevant or too minor"),
    ("explained", "Not worth it: already explained elsewhere in the record"),
    ("wrong_target", "Not worth it: wrong form or field"),
    ("evidence_wrong", "Not worth it: the evidence does not show what it claims"),
    ("duplicate", "Not worth it: repeats another query"),
    ("unsure", "Not sure: need a clinician's view"),
]

SHOW = {
    "LB": ["VISIT", "LBDTC", "LBTEST", "LBSTRESN", "LBSTRESU", "LBSTNRLO", "LBSTNRHI", "LBNRIND"],
    "AE": ["AETERM", "AEDECOD", "AESTDTC", "AEENDTC", "AESEV", "AESER", "AEREL", "AEACN", "AEOUT"],
    "DS": ["DSDECOD", "DSTERM", "VISIT", "DSSTDTC"],
    "SV": ["VISIT", "SVSTDTC"],
    "CM": ["CMTRT", "CMINDC", "CMSTDTC", "CMENDTC"],
    "MH": ["MHTERM", "MHDECOD", "MHCAT"],
    "VS": ["VISIT", "VSDTC", "VSTEST", "VSSTRESN", "VSSTRESU"],
    "DM": ["AGE", "SEX", "SITEID", "RFXSTDTC", "RFXENDTC"],
    "TI": ["IETESTCD", "IECAT", "IETEST"],
}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def resolve(data: ParquetTrialData, ref: str) -> dict[str, Any]:
    """One src_ref back to its record, for the labeller to see."""
    domain, *rest = ref.split(":")
    try:
        if domain == "TI":
            df = data.study_rows("ti")
        else:
            df = data.patient_rows(domain.lower(), rest[0])
        row = df[df["src_ref"] == ref]
        if row.empty:
            return {"src_ref": ref, "missing": True}
        rec = row.iloc[0]
        return {"src_ref": ref, **{c: rec[c] for c in SHOW.get(domain, []) if c in rec and str(rec[c]) not in ("", "nan")}}
    except Exception as exc:  # shown, never hidden
        return {"src_ref": ref, "error": str(exc)}


def page(data: ParquetTrialData) -> str:
    drafts = _jsonl(DRAFTS)
    done = {lab["draft"]: lab for lab in _jsonl(LABELS)}
    cards = []
    for d in drafts:
        evidence = [resolve(data, r) for r in d["evidence"]]
        rows = "".join(
            "<tr>" + f"<td><code>{html.escape(e['src_ref'])}</code></td>"
            + "<td>" + html.escape(", ".join(f"{k}: {v}" for k, v in e.items() if k != "src_ref")) + "</td></tr>"
            for e in evidence
        )
        prev = done.get(d["key"])
        options = "".join(
            f'<label><input type="radio" name="r-{d["key"]}" value="{v}" {"checked" if prev and prev["reason"] == v else ""}> {html.escape(t)}</label>'
            for v, t in REASONS
        )
        sent = prev["sent_text"] if prev else d["query_text"]
        note = prev["note"] if prev else ""
        status = '<span class="pill done">Labelled</span>' if prev else '<span class="pill open">To label</span>'
        cards.append(f"""
<div class="card" id="{d['key']}">
  <div class="head"><b>{html.escape(d['usubjid'])} · {html.escape(d['form'])} · {html.escape(d['category'])}</b> {status}</div>
  <p><b>Issue:</b> {html.escape(d['issue'])}</p>
  <p><b>Agent's draft query:</b></p><div class="query">{html.escape(d['query_text'])}</div>
  <details open><summary>Evidence it cites ({len(evidence)} records)</summary><table>{rows}</table></details>
  <p><b>Your judgement</b></p><div class="opts">{options}</div>
  <p><b>The query as you would send it</b> <span class="muted">(edit only if the wording should change)</span></p>
  <textarea id="t-{d['key']}">{html.escape(sent)}</textarea>
  <p><b>Note</b> <span class="muted">(optional: why)</span></p>
  <input type="text" id="n-{d['key']}" value="{html.escape(note)}">
  <button onclick="save('{d['key']}')">Save label</button> <span id="s-{d['key']}" class="muted"></span>
</div>""")
    labelled = sum(1 for d in drafts if d["key"] in done)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Label Drafts</title><style>
body{{margin:0;background:#fff;color:#1d1d1f;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
main{{max-width:960px;margin:0 auto;padding:24px 16px 80px}} h1{{font-size:26px;margin:0 0 6px}}
.card{{border:1px solid #e3e3df;border-radius:12px;padding:14px 18px;margin:16px 0}}
.head{{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}}
.query{{border-left:4px solid #0f6cbd;background:#f4f7fb;padding:8px 12px;border-radius:0 8px 8px 0}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td{{border-bottom:1px solid #e3e3df;padding:4px 6px;vertical-align:top}}
.opts label{{display:block;margin:3px 0}} textarea{{width:100%;min-height:90px;font:inherit;padding:8px;border:1px solid #ccc;border-radius:8px}}
input[type=text]{{width:100%;font:inherit;padding:6px 8px;border:1px solid #ccc;border-radius:8px}}
button{{margin-top:10px;font:inherit;padding:6px 14px;border-radius:8px;border:1px solid #0f6cbd;background:#0f6cbd;color:#fff;cursor:pointer}}
.pill{{font-size:12px;font-weight:600;padding:1px 9px;border-radius:999px}} .done{{color:#1a7f37;background:#e8f5ec}} .open{{color:#0f6cbd;background:#e7f0fb}}
.muted{{color:#5f6368}} code{{background:#f3f3ef;padding:1px 4px;border-radius:4px}}
.guide{{background:#f4f7fb;border:1px solid #dbe5f1;border-radius:12px;padding:12px 16px}}
</style></head><body><main>
<h1>Label the agent's drafts</h1>
<p class="muted">{labelled} of {len(drafts)} labelled. Each label is saved to <code>labels/labels.jsonl</code> as soon as you press Save.</p>
<div class="guide"><b>What makes a query worth sending.</b> A data manager would send it to a busy site coordinator because:
<ul><li>the record really is inconsistent, or missing something that matters, and the evidence shows it;</li>
<li>it asks rather than tells, and does not make the investigator's clinical call for them;</li>
<li>it points at the right form and is specific enough to answer in one go.</li></ul>
If any of those fails, it is not worth sending as it is. Choose the closest reason; "not sure" is an honest answer.</div>
{''.join(cards) or '<p>No drafts yet.</p>'}
</main><script>
async function save(key) {{
  const r = document.querySelector(`input[name="r-${{key}}"]:checked`);
  const s = document.getElementById("s-" + key);
  if (!r) {{ s.textContent = "Choose a judgement first."; return; }}
  const body = {{draft: key, reason: r.value, sent_text: document.getElementById("t-" + key).value,
                note: document.getElementById("n-" + key).value}};
  const res = await fetch("/label", {{method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify(body)}});
  s.textContent = res.ok ? "Saved." : "Not saved: " + await res.text();
}}
</script></body></html>"""


def save_label(payload: dict[str, Any]) -> None:
    drafts = {d["key"]: d for d in _jsonl(DRAFTS)}
    draft = drafts.get(payload.get("draft", ""))
    if draft is None:
        raise ValueError("unknown draft")
    if payload.get("reason") not in {v for v, _ in REASONS}:
        raise ValueError("unknown reason")
    record = {
        "draft": draft["key"],
        "usubjid": draft["usubjid"],
        "run_id": draft["run_id"],
        "category": draft["category"],
        "reason": payload["reason"],
        "worth_sending": payload["reason"] in ("worth", "worth_edited"),
        "edited": payload.get("sent_text", "").strip() != draft["query_text"].strip(),
        "sent_text": payload.get("sent_text", ""),
        "note": payload.get("note", ""),
        "labeller": "shalini",
        "labelled_at": datetime.now(UTC).isoformat(),
    }
    LABELS.parent.mkdir(parents=True, exist_ok=True)
    with LABELS.open("a") as f:
        f.write(json.dumps(record) + "\n")


def serve(port: int = 8765) -> None:
    data = ParquetTrialData.latest(ROOT / "data" / "curated")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = page(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                save_label(json.loads(self.rfile.read(length)))
                self.send_response(204)
                self.end_headers()
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(exc).encode())

        def log_message(self, *args: object) -> None:
            return

    print(f"Labelling page: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    pd.options.mode.copy_on_write = True
    serve()
