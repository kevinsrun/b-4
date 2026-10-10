"""Python 3.6 inference-only worker. Never import upstream training entry points."""

import csv
import importlib.util
import json
import sys
from pathlib import Path


def load_source(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    import numpy as np
    import tensorflow as tf
    from Bio import SeqIO
    from keras import backend as K

    K.set_session(
        tf.Session(
            config=tf.ConfigProto(
                intra_op_parallelism_threads=1,
                inter_op_parallelism_threads=1,
                device_count={"GPU": 0},
            )
        )
    )
    config = json.loads(Path(sys.argv[3]).read_text())
    artifacts = config["artifacts"]
    records = list(SeqIO.parse(sys.argv[1], "fasta"))
    ids = [r.id for r in records]
    columns = ["seq_id", "probability_AMP", "predicted"]
    if config["model_id"] == "amplify":
        # All five official members, and only the upstream within-model ensemble.
        source = Path(artifacts["AMPlify.py"]["path"])
        load_source(artifacts["layers.py"]["path"], "layers")
        native = load_source(source, "b4_native_amplify")
        x = native.one_hot_padding([str(r.seq) for r in records], native.MAX_LEN)
        models = native.load_multi_model(
            [artifacts["weights_" + str(i)]["path"] for i in range(1, 6)], native.build_amplify
        )
        predictions, submodels = native.ensemble(models, x)
        columns += ["log_scaled_score"] + ["submodel_" + str(i) for i in range(1, 6)]
    elif config["model_id"] == "ampscanner_v2":
        native = load_source(artifacts["predictor.py"]["path"], "b4_native_scanner")
        ids, _, x, _ = native.check_and_encode_format(sys.argv[1], native.amino_acids, 200)
        predictions = native.predict_amps(x, artifacts["weights"]["path"]).flatten()
    else:
        raise ValueError("unsupported legacy inference path")
    with open(sys.argv[2], "w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        for i, score in enumerate(predictions):
            row = {
                "seq_id": ids[i],
                "probability_AMP": float(score),
                "predicted": "AMP" if score > 0.5 else "nonAMP",
            }
            if config["model_id"] == "amplify":
                row["log_scaled_score"] = float(-10 * np.log10(1 - min(float(score), 0.99999999)))
                row.update({"submodel_" + str(j + 1): float(submodels[j, i]) for j in range(5)})
            writer.writerow(row)
    K.clear_session()


if __name__ == "__main__":
    main()
