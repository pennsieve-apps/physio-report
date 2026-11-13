"""
physio-report: one report (HTML + PDF) of whatever physiology steps are linked in, plus a tables folder.

Reads INPUT_DIR recursively: physio-import's qc output and each analysis step's top folder
(provenance.json + summary.json) in any layout (one folder per port, side by side, or merged at the
root), and physio-import's physio port (recordings.csv, channels.csv) when it is merged in too.
Writes, in the one output port `report`:

  OUTPUT_DIR/physio-report/  report.html, report.pdf, figures/<step>/..., summary.json, provenance.json
  OUTPUT_DIR/physio-report/tables/  recordings.csv, overview.csv, headline.csv, qc_summary.csv,
      resting_hrv.csv, resting_bp.csv, reference_values.csv, dose_response.csv, fulcrum.csv,
      <step>/<every table the step wrote>

Exit codes: 0 ok, 1 nothing to report on (no step output linked) or the PDF could not be written
(everything else is written first), 2 bad parameters.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import re
import resource
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("physio-report")
APP = "physio-report"
OWN_CITATIONS: list[str] = []  # the report adds no method of its own (reference values are cited where shown)


class ParameterError(ValueError):
    pass


def version() -> str:
    for p in (Path(__file__).resolve().parent.parent / "VERSION", Path("/processor/VERSION")):
        if p.exists():
            return p.read_text().strip()
    return "0.0.0"


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name, "").strip().lower()
    if v == "":
        return default
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ParameterError(f"{name} must be true or false, got {v!r}")


def parameters() -> dict[str, Any]:
    raw = os.environ.get("MAX_FIGURES", "").strip() or "40"
    try:
        max_figures = int(raw)
    except ValueError:
        raise ParameterError(f"MAX_FIGURES must be an integer, got {raw!r}") from None
    if max_figures < 0:
        raise ParameterError("MAX_FIGURES must be >= 0")
    dois = os.environ.get("DATASET_DOIS", "").strip()
    from processor.citations import valid

    bad = [d for d in re.split(r"[\s,;]+", dois) if d and not valid(d)]
    if bad:
        raise ParameterError(f"DATASET_DOIS must be DOIs (10.<registrant>/<suffix>), got {', '.join(map(repr, bad))}")
    title = os.environ.get("REPORT_TITLE", "").strip()
    if len(title) > 200:
        raise ParameterError("REPORT_TITLE is longer than 200 characters")
    return {"REPORT_TITLE": title, "MAX_FIGURES": max_figures, "DATASET_DOIS": dois,
            "WRITE_PDF": _bool("WRITE_PDF", True)}


def _scratch() -> None:
    """HOME and TMPDIR may name folders that don't exist yet (Lambda): make them. Caches that must
    be written (fontconfig for the PDF) go under TMPDIR, never into the image or HOME."""
    for var in ("TMPDIR", "HOME"):
        d = os.environ.get(var)
        if d:
            try:
                Path(d).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
    tmp = Path(tempfile.gettempdir())
    os.environ.setdefault("XDG_CACHE_HOME", str(tmp / "cache"))
    Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)


def _peak_rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(r / (1024 * 1024) if sys.platform == "darwin" else r / 1024, 1)


def _tool_versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as v

    out = {"python": sys.version.split()[0]}
    for pkg in ("jinja2", "weasyprint", "pillow", "pydyf"):
        try:
            out[pkg] = v(pkg)
        except PackageNotFoundError:
            pass
    return out


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(["" if v is None else ("|".join(map(str, v)) if isinstance(v, list) else v) for v in r])


def _scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def copy_figures(model: dict[str, Any], out: Path) -> None:
    from processor.render import image_size

    n = 0
    for sec in model["sections"]:
        for f in sec["figures"] + sec["omitted"]:
            dst = out / f["dest"]
            f["out_path"] = str(dst)
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f["src_path"], dst)
                size = image_size(dst)
            except OSError as exc:
                log.warning("cannot copy figure %s: %s", f["src_path"], exc)
                size = None
            f["ok"] = size is not None
            f["w"], f["h"] = size if size else (0, 0)
            if not f["ok"]:
                msg = f"figure {f['rel']} could not be read as an image"
                sec["warnings"].append(msg)
                model["issues"].append({"step": sec["label"], "problem": msg})
        for f in sec["figures"]:
            n += 1
            f["number"] = n


def write_tables(model: dict[str, Any], found: Any, out: Path) -> list[str]:
    from processor.model import resolve

    written: list[str] = []
    out.mkdir(parents=True, exist_ok=True)
    recs = model["recordings"]
    if recs:
        _write_csv(out / "recordings.csv", ["recording_id", "subject", "species", "duration", "channel_types",
                                            "steps_with_results", "not_analysed"],
                   [[r["recording_id"], r["subject"], "" if r["species"] == "–" else r["species"], r["duration"],
                     "|".join(r["type_keys"]), "|".join(r["steps"]), " | ".join(r["not_analysed"])] for r in recs])
        written.append("recordings.csv")
    g = model["glance"]
    if g["rows"]:
        _write_csv(out / "overview.csv", ["recording_id"] + [f"{app}:{key}" for _, app, key, _ in g["cols"]],
                   [[r["recording_id"]] + r["raw"] for r in g["rows"]])
        written.append("overview.csv")
    long_rows = []
    for sec in model["sections"]:
        for rid, rec in sec["recs"].items():
            for k, v in rec.items():
                if k == "recording_id":
                    continue
                if _scalar(v) and v not in (None, ""):
                    long_rows.append([rid, sec["label"], k, v])
                elif isinstance(v, list) and all(_scalar(x) for x in v) and v:
                    long_rows.append([rid, sec["label"], k, "|".join(map(str, v))])
                elif isinstance(v, dict):
                    for k2, v2 in v.items():
                        if _scalar(v2) and v2 not in (None, ""):
                            long_rows.append([rid, sec["label"], f"{k}.{k2}", v2])
    if long_rows:
        _write_csv(out / "headline.csv", ["recording_id", "step", "metric", "value"], long_rows)
        written.append("headline.csv")
    for sec in model["sections"]:
        if sec.get("qc"):
            keys = ["recording_id", "duration", "recorded", "n_channels", "types", "flagged", "n_flagged",
                    "uncalibrated", "inspector", "trials", "markers"]
            _write_csv(out / "qc_summary.csv", keys, [[r.get(k) for k in keys] for r in sec["qc"]["rows"]])
            written.append("qc_summary.csv")
            break
    key = model["key"]
    from processor.model import REST_BP, REST_HRV, recordings_of

    for name, k, cols in (("resting_hrv.csv", "hrv", REST_HRV), ("resting_bp.csv", "bp", REST_BP)):
        if key.get(k):
            sec = next(s for s in model["sections"] if s["anchor"] == key[k]["anchor"])
            recs_ = recordings_of(sec["step"])
            species = {r["recording_id"]: ("" if r["species"] == "–" else r["species"]) for r in recs}
            _write_csv(out / name, ["recording_id", "species"] + [c[1] for c in cols],
                       [[rid, species.get(rid, "")] + [recs_[rid].get(c[1]) for c in cols] for rid in recs_])
            written.append(name)
    refs = [r for k in ("hrv", "bp") for r in ((key.get(k) or {}).get("refs") or [])]
    if refs:
        _write_csv(out / "reference_values.csv", ["step", "metric", "species", "reference", "note", "population", "dois"],
                   [[r["app"], r["key"], r["species"], r["text"], r["note"], r["population"], "|".join(r["dois"])]
                    for r in refs])
        written.append("reference_values.csv")
    dose = key.get("dose") or {}
    for name, t in (("dose_response.csv", dose.get("fits")), ("fulcrum.csv", dose.get("fulcrum"))):
        if t and t.get("raw"):
            cols: list[str] = []
            for r in t["raw"]:
                cols += [c for c in r if c not in cols]
            _write_csv(out / name, cols, [[r.get(c) for c in cols] for r in t["raw"]])
            written.append(name)
    # Copies of every table each step wrote, under <step label>/.
    for sec in model["sections"]:
        step = sec["step"]
        for t in sec["tables"]:
            for rel in t["files"]:
                src = resolve(step, rel)
                if src is None:
                    continue
                dst = out / sec["label"] / rel
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
                    written.append(f"{sec['label']}/{rel}")
                except OSError as exc:
                    log.warning("cannot copy table %s: %s", src, exc)
    # physio-import's dataset index tables, when its physio port is linked too.
    for d in [x for x in found.datasets if not x.in_step]:
        for name in ("recordings.csv", "channels.csv", "events.tsv"):
            src = d.folder / name
            if src.is_file():
                dst = out / "physio-import" / "physio" / name
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
                    written.append(f"physio-import/physio/{name}")
    return written


def run(input_dir: Path, output_dir: Path, params: dict[str, Any]) -> int:
    _scratch()
    from processor import model as M
    from processor import render
    from processor.inputs import find

    t0 = time.time()
    started = datetime.now(timezone.utc)
    found = find(input_dir)
    for d in found.datasets:
        log.info("physio-import dataset %-40s recordings=%d channels=%d", d.rel, len(d.recordings), len(d.channels))
    for s in found.steps:
        log.info("step %-22s %-45s recordings=%d figures=%d", s.label, s.rel,
                 len(M.recordings_of(s)), len(s.summary.get("figures") or []))
    if not found.steps:
        log.error("nothing to report on under %s: no step output (<app>/provenance.json + summary.json) in any of "
                  "the ports qc, events, hrv, bp, responses", input_dir)
        return 1

    model = M.build(found, params, version())
    model["generated"] = started.strftime("%Y-%m-%d %H:%M UTC")
    rep = output_dir / APP
    rep.mkdir(parents=True, exist_ok=True)
    copy_figures(model, rep)
    written = write_tables(model, found, rep / "tables")
    model["warnings_total"] = sum(len(s["warnings"]) for s in model["sections"])
    (rep / "report.html").write_text(render.html(model), encoding="utf-8")
    log.info("wrote report.html (%d sections, %d figures shown, %d recordings), %d tables",
             len(model["sections"]), sum(len(s["figures"]) for s in model["sections"]), len(model["recordings"]),
             len(written))

    pdf_error = ""
    if params["WRITE_PDF"]:
        try:
            t1 = time.time()
            render.write_pdf(model, rep / "report.pdf")
            log.info("wrote report.pdf (%.1f MB, %.0f s)", (rep / "report.pdf").stat().st_size / 1e6, time.time() - t1)
        except Exception as exc:  # noqa: BLE001
            pdf_error = f"{type(exc).__name__}: {exc}"[:500]
            log.exception("report.pdf could not be written: %s", pdf_error)
            (rep / "report.pdf").unlink(missing_ok=True)

    finished = datetime.now(timezone.utc)
    summary = {
        "app": APP, "version": version(),
        "recordings": {r["recording_id"]: {"steps": r["steps"], "not_analysed": r["not_analysed"]}
                       for r in model["recordings"]},
        "steps": [s["label"] for s in model["sections"]],
        "workflows": model["workflows"],
        "steps_not_linked": model["missing_apps"],
        "n_figures": sum(len(s["figures"]) for s in model["sections"]),
        "n_references": len(model["references"]),
        "n_unknown_dois": sum(1 for r in model["references"] if not r["known"]),
        "figures": [],
        "tables": [{"path": f"tables/{t}", "caption": ""} for t in written if "/" not in t],
        "warnings": [f"{s['label']}: {w}" for s in model["sections"] for w in s["warnings"]]
        + ([f"physio-report: report.pdf could not be written ({pdf_error})"] if pdf_error else []),
        "notice": "Research output, not a clinical finding: every number is to be reviewed against the recordings "
                  "by the researcher.",
    }
    (rep / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    inputs = [str(Path(d.rel) / "recordings.csv") for d in found.datasets] + \
             [str(Path(s.rel) / "provenance.json") for s in found.steps]
    provenance = {
        "app": APP, "version": version(), "variant": None, "tools": _tool_versions(), "parameters": params,
        "inputs": inputs,
        "started": started.isoformat().replace("+00:00", "Z"), "finished": finished.isoformat().replace("+00:00", "Z"),
        "wall_seconds": round(time.time() - t0, 2), "peak_rss_mb": _peak_rss_mb(),
        "threads": {"requested": 0, "used": 1, "why": "single-threaded: reads small JSON/CSV/PNG files"},
        "recordings": {r["recording_id"]: {"status": "ok", "seconds": 0.0, "species": r["species"]}
                       for r in model["recordings"]},
        "citations": OWN_CITATIONS, "licence_notice": None,
    }
    (rep / "provenance.json").write_text(json.dumps(provenance, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("done: %d steps, %d recordings, %d references (%d DOI-only), %d warnings, %d input notes, %.1f s, "
             "peak %.0f MB", len(model["sections"]), len(model["recordings"]), len(model["references"]),
             summary["n_unknown_dois"], model["warnings_total"], len(model["issues"]), provenance["wall_seconds"],
             provenance["peak_rss_mb"])
    if pdf_error:
        log.error("failing the step: report.pdf could not be written (report.html and the tables are complete)")
        return 1
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    for noisy in ("weasyprint", "fontTools", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    input_dir = Path(os.environ.get("INPUT_DIR") or "/data/input")
    output_dir = Path(os.environ.get("OUTPUT_DIR") or "/data/output")
    try:
        params = parameters()
    except ParameterError as exc:
        log.error("bad parameter: %s", exc)
        return 2
    if not input_dir.is_dir():
        log.error("INPUT_DIR %s does not exist", input_dir)
        return 1
    log.info("physio-report %s: INPUT_DIR=%s OUTPUT_DIR=%s %s", version(), input_dir, output_dir,
             " ".join(f"{k}={v!r}" for k, v in params.items()))
    return run(input_dir, output_dir, params)


if __name__ == "__main__":
    sys.exit(main())
