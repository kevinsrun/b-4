"""Use upstream features/checkpoint with one inference thread, without training."""

from __future__ import annotations

import argparse
import csv
import pickle
from pathlib import Path


def main():
    # Keep scientific dependencies out of the API interpreter and import-time module audit.
    from amPEPpy.amPEP import score

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("weights", type=Path)
    args = parser.parse_args()
    # The parent verifies the official artifact hash before this trusted local pickle is loaded.
    with args.weights.open("rb") as stream:
        model = pickle.load(stream)
    if model.classes_.tolist() != [0, 1]:
        raise ValueError("unexpected pretrained class ordering")
    model.set_params(n_jobs=1)
    with args.input.open() as stream:
        features = score(stream)
    probabilities = model.predict_proba(features)
    classes = model.predict(features)
    with args.output.open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["probability_nonAMP", "probability_AMP", "predicted", "seq_id"])
        for seq_id, values, predicted in zip(features.index, probabilities, classes, strict=True):
            writer.writerow([*values, "AMP" if predicted == 1 else "nonAMP", seq_id])


if __name__ == "__main__":
    main()
