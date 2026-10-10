"""Audited model catalog. Disabled entries never invoke upstream training code."""

CATALOG = {
    "ampir": {
        "model_version": "1.1.0",
        "source": "https://github.com/Legana/ampir",
        "source_commit": "93bcaa2d074d946eac5d66ef8d3640724e68d725",
        "publication": "https://doi.org/10.1093/bioinformatics/btaa653",
        "license": "GPL-2.0",
        "min_length": 10,
        "max_length": None,
        "requires": ["R 4.4.3", "ampir 1.1.0", "caret", "kernlab", "Peptides", "Rcpp"],
        "score_interpretation": "upstream prob_AMP from SVM probability estimation; "
        "local calibration unverified",
        "limitations": [
            "mature model recommended for peptides <60 residues; "
            "precursor model is a distinct pretrained classifier",
            "minimum 10 enforced conservatively: README says 10, source defaults to 5",
        ],
    },
    "ampeppy": {
        "model_version": "1.1.0",
        "source": "https://github.com/tlawrence3/amPEPpy",
        "source_commit": "85aab3428b328d9fe4744052258746d8f4ba7bf6",
        "publication": "https://doi.org/10.1093/bioinformatics/btaa917",
        "license": "GPL-3.0 (LICENSE; setup classifiers conflict)",
        "min_length": 1,
        "max_length": None,
        "requires": [
            "Python 3.11",
            "scikit-learn 1.4.0",
            "numpy 1.26.4",
            "pandas 2.2.1",
            "biopython 1.83",
            "scipy 1.12.0",
        ],
        "score_interpretation": "upstream probability_AMP from random forest predict_proba; "
        "local calibration unverified",
        "limitations": [
            "no documented hard length domain; executable acceptance is not "
            "evidence of applicability",
            "current checkpoint differs from historical "
            "publication artifact; publication-metric reproduction unverified",
        ],
    },
    "amplify": {
        "model_version": "2.0.1/source@3a07713c",
        "source": "https://github.com/BirolLab/AMPlify",
        "source_commit": "3a07713c25b8a21ef66d31d10e121989d26d9320",
        "publication": "https://doi.org/10.1186/s12864-022-08310-4",
        "license": "GPL-3.0; commercial licensing contact in LICENSE",
        "min_length": 2,
        "max_length": 200,
        "requires": ["Python 3.6", "TensorFlow 1.12", "Keras 2.2.4", "numpy <1.17", "h5py <3"],
        "score_interpretation": "ensemble probability and -10*log10(1-p) score",
        "blocker": "legacy TensorFlow 1.x runtime unavailable on native Apple Silicon; "
        "official x86_64 TensorFlow 1.12 wheel aborts: AVX unavailable through local Rosetta; "
        "no Linux/amd64 runtime available; inference-only adapter remains unverified",
        "limitations": ["balanced/imbalanced five-member ensembles have distinct contexts"],
    },
    "ampscanner_v2": {
        "model_version": "source@16d48ef7",
        "source": "https://github.com/dan-veltri/amp-scanner-v2",
        "source_commit": "16d48ef78d150853bd4bd8a3b18b50b03a357a85",
        "publication": "https://doi.org/10.1093/bioinformatics/bty179",
        "license": "GPL-3.0",
        "min_length": 10,
        "max_length": 200,
        "requires": ["Python 3.6", "TensorFlow 1.2.1 or 1.12", "Keras 2.x", "h5py 2.x"],
        "score_interpretation": "upstream neural classifier score; no local calibration",
        "blocker": "native legacy TensorFlow unavailable; original/2019/2020 checkpoints "
        "require separately pinned runtimes; 021820 checkpoint selected for TensorFlow 1.12; "
        "local x86_64 import aborts because AVX unavailable",
        "limitations": ["200-residue recommended limit; upstream accepts X, this API does not"],
    },
    "ai4amp": {
        "model_version": "source@04ea9fcb",
        "source": "https://github.com/LinTzuTang/AI4AMP_predictor",
        "source_commit": "04ea9fcb9956027f373d36b9ef621a41d778eaca",
        "publication": "https://doi.org/10.1128/mSystems.00299-21",
        "license": "no repository license found; article CC-BY-4.0 is not a code license",
        "min_length": 10,
        "max_length": 200,
        "requires": ["TensorFlow/Keras", "PC6 encoding", "PC6_final_8.h5"],
        "score_interpretation": "PC6 neural score; implementation uses >0.5; "
        "paper discusses approximately 0.41; local calibration unverified",
        "blocker": "code/weights reuse license unresolved; runtime and inference unverified",
        "limitations": ["paper excludes sequences below 10 residues; PC6 pads to 200"],
    },
    "apin": {
        "model_version": "source@11f50b4c",
        "source": "https://github.com/zhanglabNKU/APIN",
        "source_commit": "11f50b4cfbd7eef50f9350a4e61d9642caf93cc6",
        "publication": "https://doi.org/10.1186/s12859-019-3327-y",
        "license": "no repository license found",
        "min_length": 1,
        "max_length": None,
        "requires": ["Linux", "Python 3", "numpy", "Keras"],
        "score_interpretation": "neural classifier output from an on-demand trained model",
        "blocker": "official main calls model.fit before predict; no checkpoint/load_model "
        "path found; training prohibited and code license unresolved",
        "limitations": ["never executed; cannot be enabled through configuration"],
    },
}


# Public SHA256 identities, not bundled third-party code or model weights.
CATALOG["amplify"]["pinned_artifacts"] = {
    "AMPlify.py": "68fdcf72745cd911d2d50624b619ccf322c08992c31d663c10539c1bd75ea0f6",
    "layers.py": "cac0b5a8ddbdc5d69c4dad2d62fdf296bf48c0823456144406fc45fde0aaff2f",
    "weights_1": "f9a0bf942a3ea6b01579295c6e4b87125e0a05c5a373de0fb54c5c5eb8280cf2",
    "weights_2": "f3542737840254e4135ef238413c8dac67cc5ddde9782004d7ad42cac35cf0a5",
    "weights_3": "b6644c510b57d202fa08330af402e6d2c76735cf577a3d7832a3cb1175de5bd3",
    "weights_4": "1718d26c4ba00e93ba65329995bdb52f6f449d7e379ba891371436258f82d87a",
    "weights_5": "cbb8012d0a31c2076591b3e6e0f300e63bae0d485b63a46d4f9dcc84e7b36446",
}
CATALOG["ampscanner_v2"]["pinned_artifacts"] = {
    "predictor.py": "e08747d4b2e79539456155b24d1c3947f3928d331a8661c993c85bdfbdf230ce",
    "weights": "d56226f03fa5607923bb5b02ae9fead711c9923d1e100e4cba29e05f1db27bb4",
}

for _metadata in CATALOG.values():
    _metadata["independent_benchmark"] = "BLOCKED"
    _metadata["class_definition"] = "upstream AMP-vs-nonAMP label, not bacteriocin identity"
