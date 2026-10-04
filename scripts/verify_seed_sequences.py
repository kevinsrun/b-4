#!/usr/bin/env python3
"""Verify seed bacteriocin sequences against UniProt.

The shipped seed dataset is marked ``"sequence_verified": false`` because its
sequences were transcribed from secondary knowledge, not fetched from a primary
database. A single wrong residue silently corrupts mass, charge, GRAVY and every
score derived from them, so the flag stays false until checked.

This script fetches each record's accession from the UniProt REST API and
compares sequences.

Usage::

    pip install httpx
    PYTHONPATH=src python3 scripts/verify_seed_sequences.py          # report only
    PYTHONPATH=src python3 scripts/verify_seed_sequences.py --write  # flip flags on exact matches

Exit codes: 0 all matched, 1 at least one mismatch or fetch failure.

A caveat on mature vs. precursor sequences: UniProt entries for bacteriocins
usually cover the full precursor, including the leader peptide that is cleaved
during export. The seed file stores *mature* sequences. A reported mismatch
where the mature sequence is a suffix of the UniProt sequence is therefore
expected, and the script calls that out separately from a genuine conflict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = REPO_ROOT / "bacteriocin_lab" / "agents" / "candidate" / "data" / "seed_bacteriocins.json"
UNIPROT_FASTA = "https://rest.uniprot.org/uniprotkb/{accession}.fasta"


def fetch_sequence(client, accession: str) -> str | None:
    """Fetch one sequence from UniProt, or None on any failure."""
    try:
        response = client.get(UNIPROT_FASTA.format(accession=accession), timeout=30.0)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - network boundary
        print(f"    fetch failed: {exc}")
        return None

    lines = response.text.splitlines()
    if not lines or not lines[0].startswith(">"):
        print("    unexpected response: not FASTA")
        return None
    return "".join(line.strip() for line in lines[1:]).upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Set sequence_verified=true for records whose sequence matches exactly.",
    )
    parser.add_argument("--path", type=Path, default=SEED_PATH, help="Seed JSON file to verify.")
    args = parser.parse_args()

    try:
        import httpx
    except ImportError:
        print("httpx is required: pip install httpx", file=sys.stderr)
        return 1

    records = json.loads(args.path.read_text(encoding="utf-8"))
    exact = 0
    contained = 0
    problems = 0

    with httpx.Client(follow_redirects=True) as client:
        for record in records:
            name = record.get("name", "<unnamed>")
            accession = record.get("accession")
            local = (record.get("sequence") or "").upper()

            print(f"\n{name}  [{accession or 'no accession'}]")
            if not accession:
                print("    SKIP: no accession to verify against")
                problems += 1
                continue
            if not local:
                print("    SKIP: no local sequence")
                continue

            remote = fetch_sequence(client, accession)
            if remote is None:
                problems += 1
                continue

            if local == remote:
                print(f"    MATCH exact ({len(local)} aa)")
                record["sequence_verified"] = True
                exact += 1
            elif local in remote:
                offset = remote.index(local)
                print(
                    f"    MATCH as subsequence: local {len(local)} aa is a substring of the "
                    f"{len(remote)} aa UniProt entry at offset {offset}."
                )
                print(
                    "    Consistent with a mature peptide inside a precursor. Confirm the "
                    "cleavage site in the UniProt feature table, then set the flag by hand."
                )
                contained += 1
            else:
                print(f"    MISMATCH: local {len(local)} aa vs UniProt {len(remote)} aa")
                print(f"      local : {local}")
                print(f"      uniprot: {remote}")
                problems += 1

    print(f"\n{'=' * 70}")
    print(f"exact matches: {exact}   subsequence matches: {contained}   problems: {problems}")

    if args.write and exact:
        args.path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {exact} verified flag(s) to {args.path}")
    elif exact and not args.write:
        print("Re-run with --write to persist the verified flags for exact matches.")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
