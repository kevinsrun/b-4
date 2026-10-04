"""Command-line interface for reproducible, scriptable runs.

The CLI exists so that a run can be reproduced and diffed outside the
orchestrator -- useful for debugging a surprising result and for regression
testing the forward model against a stored expectation.

    python -m bacteriocin_sim schema experiment_spec
    python -m bacteriocin_sim capabilities
    python -m bacteriocin_sim run --spec spec.json
    python -m bacteriocin_sim run --spec specs.json --batch
    python -m bacteriocin_sim agent --input envelope.json
    python -m bacteriocin_sim sweep --spec spec.json \
        --factor bacteriocin_concentration --values 0.1,0.3,1,3,10
    python -m bacteriocin_sim selftest
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__
from .agent import run_agent
from .api import run_experiment, run_experiments
from .errors import BacteriocinSimError
from .registry import describe_backends
from .schemas import AgentInput, AgentOutput, ExperimentResult, ExperimentSpec


def _load_json(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _emit(payload: Any, *, compact: bool = False) -> None:
    text = (
        json.dumps(payload, separators=(",", ":"), sort_keys=True)
        if compact
        else json.dumps(payload, indent=2, sort_keys=True)
    )
    print(text)


def _cmd_schema(args: argparse.Namespace) -> int:
    models = {
        "experiment_spec": ExperimentSpec,
        "experiment_result": ExperimentResult,
        "agent_input": AgentInput,
        "agent_output": AgentOutput,
    }
    if args.name == "all":
        _emit({k: v.model_json_schema() for k, v in models.items()}, compact=getattr(args, "compact", False))
        return 0
    model = models.get(args.name)
    if model is None:
        print(f"unknown schema {args.name!r}; choose from {sorted(models)} or 'all'",
              file=sys.stderr)
        return 2
    _emit(model.model_json_schema(), compact=getattr(args, "compact", False))
    return 0


def _cmd_capabilities(args: argparse.Namespace) -> int:
    _emit(
        {"module": "bacteriocin_sim", "version": __version__, "backends": describe_backends()},
        compact=getattr(args, "compact", False),
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    payload = _load_json(args.spec)
    overrides = _load_json(args.parameter_overrides) if args.parameter_overrides else None
    try:
        if args.batch or isinstance(payload, list):
            specs = payload if isinstance(payload, list) else [payload]
            results = run_experiments(
                specs, backend=args.backend, parameter_overrides=overrides
            )
            _emit([r.to_json_dict() for r in results], compact=getattr(args, "compact", False))
            return 0 if all(r.status == "ok" for r in results) else 1
        result = run_experiment(payload, backend=args.backend, parameter_overrides=overrides)
        _emit(result.to_json_dict(), compact=getattr(args, "compact", False))
        return 0
    except BacteriocinSimError as exc:
        _emit(exc.to_dict(), compact=getattr(args, "compact", False))
        return 1


def _cmd_agent(args: argparse.Namespace) -> int:
    envelope = _load_json(args.input)
    output = run_agent(envelope)
    _emit(output.to_json_dict(), compact=getattr(args, "compact", False))
    return 0 if output.decision.get("n_executed", 0) else 1


def _cmd_sweep(args: argparse.Namespace) -> int:
    """Vary one condition across values and emit one result per point.

    This is the shape of experiment the loop most often wants: a dose-response
    or density-response series from which the analysis agent can fit a curve.
    """
    base = _load_json(args.spec)
    if not isinstance(base, dict):
        print("sweep requires a single ExperimentSpec object", file=sys.stderr)
        return 2
    try:
        values = [float(v) for v in args.values.split(",") if v.strip()]
    except ValueError:
        print("--values must be a comma-separated list of numbers", file=sys.stderr)
        return 2

    unit = args.unit
    specs: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        spec = json.loads(json.dumps(base))
        spec["experiment_id"] = f"{base.get('experiment_id', 'sweep')}-{index:03d}"
        conditions = spec.setdefault("conditions", {})
        conditions[args.factor] = {"value": value, "unit": unit} if unit else value
        specs.append(spec)

    results = run_experiments(specs, backend=args.backend)
    _emit(
        {
            "factor": args.factor,
            "unit": unit,
            "points": [
                {
                    "value": value,
                    "experiment_id": r.experiment_id,
                    "result_id": r.result_id,
                    "status": r.status,
                    "predicted_inhibition_fraction": (
                        r.measurement.predicted_inhibition_fraction
                    ),
                    "predicted_survival_fraction": r.measurement.predicted_survival_fraction,
                    "predicted_activity": r.measurement.predicted_activity,
                    "uncertainty": r.measurement.uncertainty,
                    "ci95_inhibition_fraction": r.measurement.ci95_inhibition_fraction,
                    "predicted_mic_um": r.measurement.predicted_mic_um,
                    "confidence": r.confidence,
                }
                for value, r in zip(values, results)
            ],
            "model_version": results[0].model_version if results else None,
            "evidence_type": "simulation-derived",
            "validated_experimentally": False,
        },
        compact=getattr(args, "compact", False),
    )
    return 0


def _cmd_selftest(args: argparse.Namespace) -> int:
    """Assert the model's qualitative invariants without needing pytest.

    These are the monotonicity properties the forward model must satisfy for
    its output to be scientifically usable. A failure here means the model is
    wrong, not merely imprecise.
    """
    from .selftest import run_selftest

    report = run_selftest()
    _emit(report, compact=getattr(args, "compact", False))
    return 0 if report["passed"] else 1


def build_parser() -> argparse.ArgumentParser:
    # --compact is accepted on either side of the subcommand; a CLI that
    # rejects a flag for being on the wrong side of the subcommand is a
    # needless papercut in scripts. The subcommand copy defaults to SUPPRESS so
    # that omitting it there does not overwrite a value given at the top level.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--compact",
        action="store_true",
        default=argparse.SUPPRESS,
        help="emit single-line JSON instead of indented",
    )

    parser = argparse.ArgumentParser(
        prog="bacteriocin-sim",
        description=(
            "Computational simulation experiment backend for bacteriocin activity. "
            "All output is simulation-derived and must never be reported as "
            "experimentally validated."
        ),
    )
    parser.add_argument("--version", action="version", version=f"bacteriocin-sim {__version__}")
    parser.add_argument(
        "--compact", action="store_true", help="emit single-line JSON instead of indented"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_schema = sub.add_parser("schema", parents=[common], help="print a JSON schema")
    p_schema.add_argument(
        "name",
        nargs="?",
        default="all",
        help="experiment_spec | experiment_result | agent_input | agent_output | all",
    )
    p_schema.set_defaults(func=_cmd_schema)

    p_cap = sub.add_parser("capabilities", parents=[common], help="describe the registered backends")
    p_cap.set_defaults(func=_cmd_capabilities)

    p_run = sub.add_parser("run", parents=[common], help="run one spec or a list of specs")
    p_run.add_argument("--spec", required=True, help="path to a JSON spec, or - for stdin")
    p_run.add_argument("--batch", action="store_true", help="treat the input as a list")
    p_run.add_argument("--backend", default=None, help="override backend routing")
    p_run.add_argument("--parameter-overrides", default=None, help="path to an override JSON")
    p_run.set_defaults(func=_cmd_run)

    p_agent = sub.add_parser("agent", parents=[common], help="run the agent envelope interface")
    p_agent.add_argument("--input", required=True, help="path to an AgentInput JSON, or -")
    p_agent.set_defaults(func=_cmd_agent)

    p_sweep = sub.add_parser("sweep", parents=[common], help="vary one condition across values")
    p_sweep.add_argument("--spec", required=True)
    p_sweep.add_argument(
        "--factor",
        default="bacteriocin_concentration",
        help="condition field to vary (e.g. bacteriocin_concentration, target_cell_density)",
    )
    p_sweep.add_argument("--values", required=True, help="comma-separated values")
    p_sweep.add_argument("--unit", default="uM", help="unit for the swept values ('' for none)")
    p_sweep.add_argument("--backend", default=None)
    p_sweep.set_defaults(func=_cmd_sweep)

    p_self = sub.add_parser("selftest", parents=[common], help="check the model's qualitative invariants")
    p_self.set_defaults(func=_cmd_selftest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        print(f"file not found: {exc.filename}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"invalid JSON input: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:  # pragma: no cover - piping into head
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
