"""Isolated Biopython alignment audit; emits sequence similarity, never activity evidence."""

import hashlib
import json
import sys
from pathlib import Path


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def main():
    from Bio import Align, __version__
    from Bio.Align import substitution_matrices

    config = json.loads(Path(sys.argv[1]).read_text())
    aligner = Align.PairwiseAligner()
    aligner.mode = "local"
    aligner.substitution_matrix = substitution_matrices.load("BLOSUM62")
    aligner.open_gap_score = -10
    aligner.extend_gap_score = -0.5
    hits, comparisons, complete = [], 0, True
    # Duplicate training sequences are collapsed for alignment, with source aliases retained.
    references = {}
    for r in config["reference"]:
        references.setdefault(r["sequence"], []).append(r["sequence_id"])

    def compare(queries, references):
        nonlocal comparisons
        hits, complete = [], True
        for query in queries:
            a = query["sequence"]
            for b, ids in references.items():
                if (
                    min(len(a), len(b)) / max(len(a), len(b))
                    < config["identity_cutoff"] * config["coverage_cutoff"]
                ):
                    continue
                if comparisons >= config["pair_budget"]:
                    complete = False
                    break
                comparisons += 1
                alignments = aligner.align(a, b)
                # len(alignments) can overflow for repetitive sequences; use an iterator.
                alignment = next(iter(alignments), None)
                if alignment is None:
                    continue
                coords = alignment.coordinates
                columns, matches = 0, 0
                for i in range(coords.shape[1] - 1):
                    x0, x1 = int(coords[0, i]), int(coords[0, i + 1])
                    y0, y1 = int(coords[1, i]), int(coords[1, i + 1])
                    columns += max(x1 - x0, y1 - y0)
                    if x1 > x0 and y1 > y0:
                        matches += sum(x == y for x, y in zip(a[x0:x1], b[y0:y1], strict=True))
                identity = matches / columns if columns else 0
                qc = (int(coords[0, -1]) - int(coords[0, 0])) / len(a)
                rc = (int(coords[1, -1]) - int(coords[1, 0])) / len(b)
                if (
                    identity >= config["identity_cutoff"]
                    and min(qc, rc) >= config["coverage_cutoff"]
                ):
                    hits.append(
                        {
                            "query_id": query["sequence_id"],
                            "reference_ids": ids,
                            "identity": identity,
                            "query_coverage": qc,
                            "reference_coverage": rc,
                            "alignment_score": alignment.score,
                        }
                    )
            if not complete:
                break
        return hits, complete

    hits, complete = compare(config["query"], references)
    within_hits, within_complete = [], True
    for i, query in enumerate(config["query"]):
        previous = {}
        for r in config["query"][:i]:
            previous.setdefault(r["sequence"], []).append(r["sequence_id"])
        found, done = compare([query], previous)
        within_hits.extend(found)
        within_complete = within_complete and done
        if not done:
            break
    result = {
        "schema_version": "amp-alignment-audit/1",
        "complete": complete,
        "within_benchmark_complete": within_complete,
        "within_benchmark_hits": within_hits,
        "query_digest": digest(config["query"]),
        "reference_digest": digest(config["reference"]),
        "biopython_version": __version__,
        "method": "highest-scoring local BLOSUM62 alignment",
        "gap_open": -10,
        "gap_extend": -0.5,
        "identity_cutoff": config["identity_cutoff"],
        "coverage_cutoff": config["coverage_cutoff"],
        "pair_budget": config["pair_budget"],
        "comparisons": comparisons,
        "hits": hits,
        "interpretation": "similarity screening; not evolutionary homology or activity proof",
    }
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
