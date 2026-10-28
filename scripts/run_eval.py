"""Run the agent over a world's patients, several times each (task 2.5).

    python scripts/run_eval.py --limit 5          # measure the first five first
    python scripts/run_eval.py --repeats 3        # then the rest

Every run gets its own drafts store, so a repeat never sees an earlier repeat's
queries. Stops launching new runs once the spend ceiling is reached (D10, G3),
and runs four patients at a time (G4). Writes runs/eval-<tag>/<patient>/r<k>/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clinical_review.run import review  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="planted-v1")
    ap.add_argument("--tag", default="planted-v1")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0, help="only the first N patients")
    ap.add_argument("--budget", type=float, default=20.0, help="stop launching runs past this spend, USD")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    world = json.loads((ROOT / "worlds" / args.world / "patients.json").read_text())
    snapshot = ROOT / "data" / "curated" / world["snapshot_id"]
    patients = world["patients"][: args.limit] if args.limit else world["patients"]
    out = ROOT / "runs" / f"eval-{args.tag}"
    jobs = [(p["usubjid"], k) for k in range(1, args.repeats + 1) for p in patients
            if not any((out / p["usubjid"] / f"r{k}").glob("*/record.json"))]
    spent = sum(json.loads(f.read_text())["cost_usd"] for f in out.glob("*/r*/*/record.json"))
    gate = asyncio.Semaphore(args.concurrency)
    print(f"{len(jobs)} runs to do; already spent ${spent:.2f} on this eval")

    async def one(usubjid: str, k: int) -> None:
        nonlocal spent
        async with gate:
            if spent >= args.budget:
                print(f"  skip {usubjid} r{k}: budget ${args.budget:.2f} reached")
                return
            folder = out / usubjid / f"r{k}"
            folder.mkdir(parents=True, exist_ok=True)
            try:
                rec = await review(usubjid, snapshot=snapshot, drafts_path=folder / "drafts.jsonl", out_dir=folder)
            except Exception as exc:  # recorded, never hidden
                (folder / "error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
                print(f"  ERROR {usubjid} r{k}: {exc}")
                return
            spent += rec["cost_usd"]
            print(f"  {usubjid} r{k}: {rec['termination']}, {len(rec['drafts'])} drafts, ${rec['cost_usd']:.3f} (total ${spent:.2f})")

    await asyncio.gather(*(one(u, k) for u, k in jobs))
    print(f"done; spent ${spent:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
