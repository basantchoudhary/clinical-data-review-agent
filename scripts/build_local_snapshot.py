"""Build a local curated snapshot from the raw CDISC pilot SDTM files.

This is the development stand-in for the Databricks pipeline (D3, D9): the same
shape the agent's tools will read from the lakehouse, written as parquet.

    python scripts/build_local_snapshot.py            # writes data/curated/<snapshot_id>/

What it guarantees, because the tools rely on it:
- **Blinded.** Every treatment-arm column is dropped, and the exposure (EX)
  domain is left out entirely: its dose (0, 54 or 81 mg) reveals the arm.
- **Lineage.** Every row carries `src_ref`, a stable key back to its source
  record. Today that is the SDTM key; once data flows from OpenClinica it
  becomes OpenClinica's subject, event, form and item identifiers.
- **Stamped.** Every row carries `snapshot_id`, and a manifest records what went in.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "sdtm"
CURATED = ROOT / "data" / "curated"

DOMAINS = ["dm", "sv", "ae", "lb", "vs", "cm", "mh", "ds", "ti"]
"""EX is deliberately absent: dose reveals the treatment arm."""

BLINDING_COLUMNS = {"ARM", "ARMCD", "ACTARM", "ACTARMCD"}
"""Never leave the pipeline. The tools check again (defence in depth)."""

SEQ_COLUMN = {"ae": "AESEQ", "lb": "LBSEQ", "vs": "VSSEQ", "cm": "CMSEQ", "mh": "MHSEQ", "ds": "DSSEQ"}


def src_ref(domain: str, row: pd.Series) -> str:
    if domain == "dm":
        return f"DM:{row.USUBJID}"
    if domain == "sv":
        return f"SV:{row.USUBJID}:{row.VISITNUM:g}"
    if domain == "ti":
        return f"TI:{row.IETESTCD}"
    return f"{domain.upper()}:{row.USUBJID}:{int(row[SEQ_COLUMN[domain]])}"


def load(domain: str) -> pd.DataFrame:
    df = pd.read_sas(RAW / f"{domain}.xpt", format="xport", encoding="latin1")
    df = df.drop(columns=[c for c in df.columns if c in BLINDING_COLUMNS])
    for column in df.columns:
        if df[column].dtype == object:
            df[column] = df[column].fillna("").astype(str).str.strip()
    df["src_ref"] = df.apply(lambda row: src_ref(domain, row), axis=1)
    return df


def build() -> Path:
    if not RAW.exists():
        sys.exit(f"raw data missing: {RAW} (see README, 'Get the data')")
    frames = {d: load(d) for d in DOMAINS}
    digest = hashlib.sha256()
    for d in DOMAINS:
        digest.update(pd.util.hash_pandas_object(frames[d], index=False).values.tobytes())
    created = datetime.now(UTC)
    snapshot_id = f"snap-{created:%Y%m%dT%H%M%SZ}-{digest.hexdigest()[:8]}"
    out = CURATED / snapshot_id
    out.mkdir(parents=True, exist_ok=False)
    for d, df in frames.items():
        df.insert(0, "snapshot_id", snapshot_id)
        df.to_parquet(out / f"{d}.parquet", index=False)
    manifest = {
        "snapshot_id": snapshot_id,
        "created_at": created.isoformat(),
        "source": "CDISC pilot study cdiscpilot01, PHUSE GitHub (SDTM .xpt)",
        "content_sha256": digest.hexdigest(),
        "rows": {d: len(df) for d, df in frames.items()},
        "blinding": {
            "columns_dropped": sorted(BLINDING_COLUMNS),
            "domains_excluded": {"ex": "dose reveals the treatment arm"},
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (CURATED / "LATEST").write_text(snapshot_id + "\n")
    return out


if __name__ == "__main__":
    path = build()
    print(json.dumps(json.loads((path / "manifest.json").read_text()), indent=2))
