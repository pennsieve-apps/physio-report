"""
The report as data. Every section of the HTML page and the PDF is built from this model, and the
tables folder is written from it. Nothing here recomputes a result: numbers, captions and warnings
are copied from each step's summary.json, provenance.json and tables; the only text the report
adds is its built-in description of each known app, the published reference values next to the
resting numbers (apps.REFERENCE_VALUES, with their sources) and the research-output labels.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

from processor import apps as A
from processor import citations as C
from processor.inputs import Dataset, Found, Step, read_table

NOTICE_KEYS = ("notice", "note")
WARN_VISIBLE = 8
GENERIC_COLS = 12
OK_STATUS = {"ok", "success", "done", "warn", "warning"}
TABLE_SUFFIXES = (".csv", ".tsv")
CHANNEL_TYPES = ["ecg", "bp", "resp", "ppg", "nerve", "emg", "stim", "hr", "temp", "pressure", "other"]
TYPE_NAMES = {"ecg": "ECG", "bp": "BP", "resp": "respiration", "ppg": "PPG", "nerve": "nerve", "emg": "EMG",
              "stim": "stimulation", "hr": "device HR", "temp": "temperature", "pressure": "other pressure",
              "other": "other"}


# ----------------------------------------------------------------------------- formatting

def num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else float(v)
    if isinstance(v, str) and re.fullmatch(r"\s*-?\d+(\.\d+)?([eE][-+]?\d+)?\s*", v):
        return float(v)
    return None


def duration(s: Any) -> str:
    x = num(s)
    if x is None:
        return "–"
    if x < 90:
        return f"{x:.0f} s"
    if x < 5400:
        return f"{x / 60:.1f} min"
    return f"{x / 3600:.1f} h"


def fmt(v: Any, kind: str = "num") -> str:
    """A value as a person reads it: integers exactly, rates to two decimals, other numbers to four
    significant digits, 0-1 fractions as percentages (kind pct), durations (kind dur)."""
    if v is None or v == "":
        return "–"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if kind == "dur":
        return duration(v)
    if kind == "bool":
        s = str(v).strip().lower()
        return "yes" if s in ("true", "1", "yes") else "no" if s in ("false", "0", "no") else str(v)
    x = num(v)
    if kind == "text" or x is None:
        if isinstance(v, (list, tuple)):
            return ", ".join(fmt(i, "text") for i in v) if len(v) <= 8 else f"{len(v)} values"
        if isinstance(v, dict):
            return "; ".join(f"{k}: {fmt(val)}" for k, val in v.items())
        if isinstance(v, float):
            return "–"
        return str(v)
    if kind == "pct":
        return f"{x * 100:.0f} %" if abs(x * 100 - round(x * 100)) < 0.05 else f"{x * 100:.1f} %"
    if kind == "int" or (x.is_integer() and not isinstance(v, float) and abs(x) < 1e15):
        return f"{int(round(x)):,}"
    ax = abs(x)
    if ax == 0:
        return "0"
    if kind == "rate":
        return f"{x:,.2f}"
    if ax >= 1000:
        return f"{x:,.0f}"
    if ax >= 0.001:
        return f"{x:.4g}"
    return f"{x:.2e}"


def humanise(key: str) -> str:
    k = key.replace("_", " ").strip()
    return k[:1].upper() + k[1:]


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "step"


def natural(text: str) -> list[Any]:
    """Sort key that orders frequency_hz=2 before frequency_hz=10."""
    return [(0, float(t), "") if re.fullmatch(r"\d+(\.\d+)?", t) else (1, 0.0, t)
            for t in re.split(r"(\d+(?:\.\d+)?)", str(text)) if t]


def variable_name(var: str) -> str:
    return A.VARIABLES.get(var, var)


def variable_key(var: str) -> tuple[int, str]:
    return (A.VARIABLE_ORDER.index(var) if var in A.VARIABLE_ORDER else len(A.VARIABLE_ORDER), var)


LINK = re.compile(r"(https?://[^\s<>\"'\]\[]+)|((?:doi:\s*)?10\.\d{4,9}/[^\s<>\"'\]\[,;]+)", re.I)


def safe_url(url: str) -> str:
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc or re.search(r"[\s<>\"'\\]", url):
        return ""
    return url


def linkify(text: str) -> list[dict[str, str]]:
    """Text split into segments; http(s) URLs and DOIs become links (DOIs to doi.org)."""
    out: list[dict[str, str]] = []
    pos = 0
    for m in LINK.finditer(text):
        token = m.group(0).rstrip(".,;:)")
        url = safe_url(token) if m.group(1) else C.doi_url(re.sub(r"^doi:\s*", "", token, flags=re.I))
        if not url:
            continue
        if m.start() > pos:
            out.append({"text": text[pos:m.start()], "url": ""})
        out.append({"text": token, "url": url})
        pos = m.start() + len(token)
    if pos < len(text):
        out.append({"text": text[pos:], "url": ""})
    return out


def as_list(v: Any) -> list[str]:
    """A string or a list of strings/numbers as a list of strings (a string is one item)."""
    if isinstance(v, str):
        return [v] if v.strip() else []
    return [str(x) for x in v if isinstance(x, (str, int, float)) and str(x).strip()] if isinstance(v, list) else []


# ----------------------------------------------------------------------------- reading a step

def resolve(step: Step, rel: str) -> Path | None:
    """A path from summary.json: relative to the app's top folder (the contract), or to the port
    folder above it (`<app>/...`). Never absolute, never outside the step's folder."""
    p = PurePosixPath(str(rel).replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or not p.parts:
        return None
    cand = step.folder.joinpath(*p.parts)
    if cand.is_file():
        return cand
    if len(p.parts) > 1 and p.parts[0] in (step.folder.name, step.app):
        cand = step.folder.joinpath(*p.parts[1:])
        if cand.is_file():
            return cand
    return None


def outside(rel: str) -> bool:
    p = PurePosixPath(str(rel).replace("\\", "/"))
    return p.is_absolute() or ".." in p.parts


def recordings_of(step: Step) -> dict[str, dict[str, Any]]:
    raw = step.summary.get("recordings")
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    if isinstance(raw, list):  # tolerated: a list of {recording_id, ...}
        return {str(r["recording_id"]): r for r in raw if isinstance(r, dict) and r.get("recording_id")}
    return {}


def prov_recordings(step: Step) -> dict[str, dict[str, Any]]:
    raw = step.provenance.get("recordings")
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict) else {}


def find_file(step: Step, name: str) -> Path | None:
    """A table by file name anywhere under the step's folder (conventions: find by name)."""
    try:
        for p in sorted(step.folder.rglob(name)):
            if p.is_file():
                return p
    except OSError:
        pass
    return None


def step_tables(step: Step) -> list[Path]:
    out = []
    try:
        for p in sorted(step.folder.rglob("*")):
            if p.suffix.lower() in TABLE_SUFFIXES and p.is_file():
                out.append(p)
    except OSError:
        pass
    return out


def channel_type(name: str) -> str:
    """The type of an NWB channel name (`ecg`, `ecg-2`, `nerve-1`: conventions.md)."""
    base = re.sub(r"-\d+$", "", str(name).strip().lower())
    return base if base in CHANNEL_TYPES else ""


def is_file_key(key: str) -> bool:
    """A provenance `recordings` key that is a source file path (physio-import lists input files it
    could not import that way), not a recording id."""
    return "/" in key or "\\" in key or bool(re.search(r"\.[A-Za-z0-9]{1,5}$", key))


def subject_of(rid: str) -> str:
    m = re.match(r"^sub-([A-Za-z0-9-]+)", rid)
    return m.group(1) if m else ""


# ----------------------------------------------------------------------------- recordings

def recordings_table(found: Found, steps: list[Step]) -> dict[str, dict[str, Any]]:
    """One entry per recording: physio-import's recordings.csv when its physio port is linked,
    else what its qc output and the other steps say (subject, species, duration, channel types)."""
    rows: dict[str, dict[str, Any]] = {}

    def row(rid: str) -> dict[str, Any]:
        return rows.setdefault(rid, {"recording_id": rid, "subject": "", "species": "", "duration_s": None,
                                     "recorded_s": None, "types": [], "source_format": "", "age": "", "sex": "",
                                     "from": set()})

    for d in found.datasets:
        for r in d.recordings:
            rid = r.get("recording_id")
            if not rid:
                continue
            e = row(rid)
            e.update({"subject": r.get("subject", ""), "species": r.get("species", ""),
                      "duration_s": num(r.get("duration_s")), "recorded_s": num(r.get("recorded_s")),
                      "source_format": r.get("source_format", ""), "age": r.get("age", ""), "sex": r.get("sex", "")})
            e["types"] = [t for t in (r.get("channel_types") or "").split("|") if t]
            e["from"].add("recordings.csv")
    imp = [s for s in steps if s.app == "physio-import"]
    for s in imp:
        for rid, r in recordings_of(s).items():
            e = row(rid)
            if e["duration_s"] is None:
                e["duration_s"] = num(r.get("duration_s"))
            if e["recorded_s"] is None:
                e["recorded_s"] = num(r.get("recorded_s"))
        qcp = find_file(s, "qc.csv")
        types: dict[str, list[str]] = {}
        for r in read_table(qcp) if qcp else []:
            t = channel_type(r.get("channel", ""))
            if r.get("recording_id") and t and t not in types.setdefault(r["recording_id"], []):
                types[r["recording_id"]].append(t)
        for rid, ts in types.items():
            if not row(rid)["types"]:
                row(rid)["types"] = ts
    for s in steps:
        for rid, p in prov_recordings(s).items():
            if is_file_key(rid):
                continue  # an input file that was not a recording
            e = row(rid)
            if not e["species"] and isinstance(p.get("species"), str):
                e["species"] = p["species"]
            if not e["subject"] and isinstance(p.get("subject"), (str, int)):
                e["subject"] = str(p["subject"])
        for rid, r in recordings_of(s).items():
            e = row(rid)
            if not e["species"] and isinstance(r.get("species"), str):
                e["species"] = r["species"]
            if not e["subject"] and isinstance(r.get("subject"), (str, int)) and str(r.get("subject")):
                e["subject"] = str(r["subject"])
    for rid, e in rows.items():
        if not e["subject"]:
            e["subject"] = subject_of(rid)
        order = {t: i for i, t in enumerate(CHANNEL_TYPES)}
        e["types"] = sorted(dict.fromkeys(e["types"]), key=lambda t: order.get(t, 99))
    return rows


# ----------------------------------------------------------------------------- QC (physio-import)

def qc_section(imp: list[Step], datasets: list[Dataset], rec_rows: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """One row per recording from physio-import's qc output: duration, channels, flagged channels
    with the reason, uncalibrated channels (when channels.csv is linked), NWB Inspector messages."""
    if not imp:
        return None
    per: dict[str, dict[str, Any]] = {}
    for s in imp:
        for rid, r in recordings_of(s).items():
            per.setdefault(rid, {}).update(r)
        qcp = find_file(s, "qc.csv")
        for r in read_table(qcp) if qcp else []:
            rid = r.get("recording_id", "")
            if not rid:
                continue
            d = per.setdefault(rid, {})
            if r.get("check") == "status" and r.get("value") and r.get("value") != "good":
                d.setdefault("_flagged", []).append(
                    f"{r.get('channel', '')} {r['value']}" + (f" ({r['note']})" if r.get("note") else ""))
            elif r.get("check") == "nwbinspector_messages":
                d["_inspector_levels"] = r.get("note", "")
    uncal: dict[str, list[str]] = {}
    for d in datasets:
        for c in d.channels:
            if str(c.get("calibrated", "")).lower() == "false" and c.get("type") in ("ecg", "bp", "resp", "ppg",
                                                                                      "pressure"):
                uncal.setdefault(c.get("recording_id", ""), []).append(c.get("channel", ""))
    rows = []
    for rid in list(rec_rows) + [r for r in per if r not in rec_rows]:
        if rid not in per:
            continue
        d, rr = per[rid], rec_rows.get(rid, {})
        flagged = d.get("_flagged", [])
        rows.append({
            "recording_id": rid,
            "duration": fmt(d.get("duration_s", rr.get("duration_s")), "dur"),
            "recorded": fmt(d.get("recorded_s", rr.get("recorded_s")), "dur"),
            "n_channels": fmt(d.get("n_channels"), "int"),
            "types": ", ".join(TYPE_NAMES.get(t, t) for t in rr.get("types", [])) or "–",
            "flagged": "; ".join(flagged) if flagged else ("none" if d.get("n_channels_flagged") in (0, None) else
                                                           f"{d['n_channels_flagged']} (see qc.csv)"),
            "n_flagged": len(flagged) if flagged else int(num(d.get("n_channels_flagged")) or 0),
            "uncalibrated": ", ".join(uncal.get(rid, [])),
            "inspector": fmt(d.get("nwbinspector_messages"), "int")
            + (f" ({d['_inspector_levels']})" if d.get("_inspector_levels") else ""),
            "trials": fmt(d.get("n_trials"), "int"), "markers": fmt(d.get("n_markers"), "int"),
        })
    return {"rows": rows, "has_uncal": bool(uncal), "n": len(rows),
            "with_flags": sum(1 for r in rows if r["n_flagged"]),
            "n_flagged": sum(r["n_flagged"] for r in rows)}


# ----------------------------------------------------------------------------- per-step pieces

def headline(app: str, recs: dict[str, dict[str, Any]], order: list[str]) -> dict[str, Any] | None:
    info = A.APPS.get(app, {})
    spec = list(info.get("headline") or [])
    dyn = info.get("dynamic_prefix")
    if dyn:
        keys: list[str] = []
        for r in recs.values():
            for k in r:
                if k.startswith(dyn[0]) and k not in keys:
                    keys.append(k)
        keys.sort(key=lambda k: variable_key(k[len(dyn[0]):]))
        spec += [(dyn[1].format(variable_name(k[len(dyn[0]):])), k, "num") for k in keys]
    cols = [(label, key, kind) for label, key, kind in spec if any(r.get(key) not in (None, "") for r in recs.values())]
    if not [c for c in cols if c[2] != "text"]:
        cols = generic_cols(recs)
    if not cols or not recs:
        return None
    rows = []
    for rid in order:
        if rid not in recs:
            continue
        r = recs[rid]
        rows.append([rid] + [fmt(r.get(key), kind) for _, key, kind in cols])
    return {"header": ["Recording"] + [c[0] for c in cols], "kinds": ["text"] + [c[2] for c in cols], "rows": rows}


def generic_cols(recs: dict[str, dict[str, Any]]) -> list[tuple[str, str, str]]:
    keys: list[str] = []
    for r in recs.values():
        for k, v in r.items():
            if k in keys or k in ("status", "seconds", "warnings", "recording_id"):
                continue
            if isinstance(v, bool) or (num(v) is not None and not isinstance(v, str)):
                keys.append(k)
    return [(humanise(k), k, "num") for k in keys[:GENERIC_COLS]]


def step_warnings(step: Step) -> tuple[list[str], list[dict[str, Any]]]:
    """(warnings, not-analysed groups): the step's warnings, recordings' own warnings, failed
    recordings; skipped recordings grouped by reason."""
    out: list[str] = []
    # A warning that only restates a skip ("<id>: skipped: <reason>") is shown under "Not analysed".
    restated = {f"{rid}: {r.get('status')}: {r.get('reason') or r.get('error') or ''}".rstrip(": ")
                for rid, r in prov_recordings(step).items() if str(r.get("status") or "").lower() not in OK_STATUS}
    for w in step.summary.get("warnings") or [] if isinstance(step.summary.get("warnings"), list) else []:
        text = w if isinstance(w, str) else "; ".join(f"{k}: {v}" for k, v in w.items()) if isinstance(w, dict) else str(w)
        if text not in out and text not in restated:
            out.append(text)
    for w in step.provenance.get("warnings") or [] if isinstance(step.provenance.get("warnings"), list) else []:
        if isinstance(w, str) and w not in out:
            out.append(w)
    for rid, r in recordings_of(step).items():
        for w in as_list(r.get("warnings")):
            msg = f"{rid}: {w}"
            if msg not in out:
                out.append(msg)
    skipped: dict[str, dict[str, list[str]]] = {}
    for rid, r in prov_recordings(step).items():
        status = str(r.get("status") or "").lower()
        reason = str(r.get("error") or r.get("reason") or "").strip()
        if status in ("failed", "error"):
            msg = f"{rid}: failed" + (f" ({reason})" if reason else "")
            if msg not in out:
                out.append(msg)
        elif status and status not in OK_STATUS:
            text = f"{status}: {reason}" if reason else status
            key = re.sub(r"\d+(\.\d+)?", "#", text)  # reasons that differ only in numbers are one group
            if is_file_key(rid):
                key, text = "file:" + key, f"input file not read as a recording ({text})"
            g = skipped.setdefault(key, {"texts": [], "ids": []})
            g["texts"].append(text)
            g["ids"].append(rid)
    groups = [{"reason": g["texts"][0] + (" (and similar)" if len(set(g["texts"])) > 1 else ""), "ids": g["ids"]}
              for g in skipped.values()]
    return out, groups


def not_analysed(step: Step) -> dict[str, str]:
    """recording_id -> 'skipped: reason' / 'failed: error' for the recordings table."""
    out = {}
    for rid, r in prov_recordings(step).items():
        status = str(r.get("status") or "").lower()
        if status and status not in OK_STATUS:
            reason = str(r.get("error") or r.get("reason") or "").strip()
            out[rid] = status + (f": {reason}" if reason else "")
    return out


def licence_of(step: Step) -> dict[str, Any] | None:
    """A usage restriction the step declares (provenance or summary `licence_notice`): a string, or
    {text, citations, url}. DOIs it names (in `citations`, bare in the text, or as doi.org links) are
    cited. Citations given as one string are one DOI."""
    ln = step.provenance.get("licence_notice") or step.summary.get("licence_notice")
    if not ln:
        return None
    if isinstance(ln, str):
        text, dois, url = ln.strip(), [], ""
    elif isinstance(ln, dict):
        text = str(ln.get("text") or ln.get("notice") or ln.get("summary") or "").strip()
        dois = [C.norm(d) for d in as_list(ln.get("citations") or ln.get("cite") or ln.get("dois")) if C.valid(d)]
        url = safe_url(str(ln.get("url") or ""))
    else:
        return None
    if not text and not url:
        return None
    segments = linkify(text)
    dois += [C.norm(unquote(s["url"])) for s in segments
             if re.match(r"https?://(dx\.)?doi\.org/", s["url"], re.I) and C.valid(unquote(s["url"]))]
    return {"text": text, "dois": list(dict.fromkeys(d.rstrip(".") for d in dois)), "url": url, "segments": segments}


def figures_of(step: Step, issues: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    listed = step.summary.get("figures") or []
    figs, missing = [], []
    for f in listed if isinstance(listed, list) else []:
        if isinstance(f, str):
            f = {"path": f}
        if not isinstance(f, dict) or not f.get("path"):
            issues.append({"step": step.label, "problem": f"a figures entry is not {{path, caption}}: {str(f)[:80]}"})
            continue
        caption = str(f.get("caption") or f.get("description") or "").strip()
        path = resolve(step, str(f["path"]))
        if path is None:
            missing.append(str(f["path"]))
            continue
        if not caption:
            issues.append({"step": step.label, "problem": f"figure {f['path']} has no caption"})
        flat = str(f["path"]).replace("\\", "/").strip("/").replace("/", "__")
        figs.append({"src_path": str(path), "rel": str(f["path"]), "caption": caption,
                     "dest": f"figures/{slug(step.label)}/{slug(flat)}"})
    return figs, missing


def tables_of(step: Step, issues: list[dict[str, str]]) -> list[dict[str, Any]]:
    """The tables the step listed in summary.json, then every other CSV/TSV under its folder; many
    unlisted files in one subfolder are one entry. `files` are the paths (relative to the step
    folder) to copy. A listed path outside the step's folder is noted, never followed."""
    out = []
    listed = step.summary.get("tables") or []
    seen = set()
    far = []
    for t in listed if isinstance(listed, list) else []:
        if isinstance(t, str):
            t = {"path": t}
        if not isinstance(t, dict) or not t.get("path"):
            continue
        if outside(str(t["path"])):
            far.append(str(t["path"]))
            continue
        p = resolve(step, str(t["path"]))
        rel = str(p.relative_to(step.folder)) if p is not None else str(t["path"])
        out.append({"rel": str(t["path"]), "caption": str(t.get("caption") or "").strip(), "exists": p is not None,
                    "files": [rel] if p is not None else []})
        if p is not None:
            seen.add(p.resolve())
    if far:
        issues.append({"step": step.label, "problem": "summary.json lists tables outside the app's top folder ("
                       + ", ".join(far) + "): paths are relative to the top folder and stay inside the port, so the "
                       "report cannot read or copy them"})
    groups: dict[str, list[str]] = {}
    for p in step_tables(step):
        if p.resolve() in seen:
            continue
        seen.add(p.resolve())
        rel = p.relative_to(step.folder)
        groups.setdefault(str(rel.parent), []).append(str(rel))
    for parent, files in groups.items():
        if parent != "." and len(files) > 3:
            out.append({"rel": parent + "/", "caption": f"{len(files)} files", "exists": True, "files": files})
        else:
            out += [{"rel": f, "caption": "", "exists": True, "files": [f]} for f in files]
    return out


def group_warnings(warnings: list[str], ids: set[str]) -> list[str]:
    """Identical per-recording warnings ("<recording_id>: text") said once, with the recordings."""
    by_text: dict[str, list[str]] = {}
    order: list[tuple[str, str]] = []
    for w in warnings:
        rid, sep, rest = w.partition(": ")
        if sep and rid in ids:
            if rest not in by_text:
                by_text[rest] = []
                order.append(("g", rest))
            by_text[rest].append(rid)
        else:
            order.append(("w", w))
    out = []
    for kind, text in order:
        if kind == "w":
            out.append(text)
        elif len(by_text[text]) == 1:
            out.append(f"{by_text[text][0]}: {text}")
        else:
            rids = by_text[text]
            out.append(f"{text} ({len(rids)} recordings: " + ", ".join(rids[:8]) + (", ..." if len(rids) > 8 else "") + ")")
    return out


def notices_of(step: Step) -> list[str]:
    out = []
    for k in NOTICE_KEYS:
        v = step.summary.get(k)
        if isinstance(v, str) and v.strip() and v.strip() not in out:
            out.append(v.strip())
    return out


# ----------------------------------------------------------------------------- key results

def _species(rec_rows: dict[str, dict[str, Any]], rid: str) -> str:
    return str(rec_rows.get(rid, {}).get("species") or "")


def step_reference_values(step: Step) -> list[dict[str, Any]]:
    """Reference values a step gives itself in summary.json `reference_ranges` (optional):
    [{key, species, text | low+high+unit, population, citations}]."""
    out = []
    raw = step.summary.get("reference_ranges")
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict) or not r.get("key"):
            continue
        text = str(r.get("text") or "").strip()
        if not text and num(r.get("low")) is not None and num(r.get("high")) is not None:
            text = f"{fmt(r['low'])}–{fmt(r['high'])}" + (f" {r['unit']}" if r.get("unit") else "")
        if not text:
            continue
        out.append({"app": step.app, "key": str(r["key"]), "species": str(r.get("species") or "human").lower(),
                    "text": text, "note": str(r.get("note") or ""), "population": str(r.get("population") or ""),
                    "dois": [C.norm(d) for d in as_list(r.get("citations") or r.get("doi")) if C.valid(d)],
                    "from_step": step.label})
    return out


def resting_table(step: Step | None, cols: list[tuple[str, str, str]], rec_rows: dict[str, dict[str, Any]],
                  order: list[str], refs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Per recording the resting (whole-recording) numbers of one step, with the reference values
    for the species present."""
    if step is None:
        return None
    recs = recordings_of(step)
    cols = [c for c in cols if any(r.get(c[1]) not in (None, "") for r in recs.values())]
    if not cols or not recs:
        return None
    rows = []
    for rid in order + [r for r in recs if r not in order]:
        if rid in recs and not any(row[0] == rid for row in rows):
            rows.append([rid, _species(rec_rows, rid) or "–"] + [fmt(recs[rid].get(k), kind) for _, k, kind in cols])
    species = {_species(rec_rows, rid) for rid in recs}
    keys = {k for _, k, _ in cols}
    shown = [r for r in refs if r["app"] == step.app and r["key"] in keys and r["species"] in species]
    label = {k: lab for lab, k, _ in cols}
    for r in shown:
        r["label"] = label[r["key"]]
    return {"header": ["Recording", "Species"] + [c[0] for c in cols], "kinds": ["text", "text"] + [c[2] for c in cols],
            "rows": rows, "refs": shown,
            "no_ref_species": sorted(s for s in species if s and not any(r["species"] == s for r in shown)
                                     and s != "human") + (["unknown"] if "" in species else [])}


REST_HRV = [("Mean HR (bpm)", "mean_hr_bpm", "num"), ("SDNN (ms)", "sdnn_ms", "num"), ("RMSSD (ms)", "rmssd_ms", "num"),
            ("LF/HF", "lf_hf", "num"), ("Beats", "n_beats", "int"), ("Artifact beats (%)", "pct_artifact", "num")]
REST_BP = [("Calibrated", "calibrated", "bool"), ("SBP (mmHg)", "sbp_mmhg", "num"), ("DBP (mmHg)", "dbp_mmhg", "num"),
           ("MAP (mmHg)", "map_mmhg", "num"), ("BRS sequence (ms/mmHg)", "brs_sequence_all", "num"),
           ("BRS alpha LF (ms/mmHg)", "brs_alpha_lf", "num"), ("BRS transfer LF (ms/mmHg)", "brs_transfer_lf", "num"),
           ("RSA peak-to-trough (ms)", "rsa_p2t_ms", "num"), ("Breathing rate (/min)", "resp_rate_bpm", "num")]


def param_name(key: str) -> str:
    """`frequency_hz` as `frequency`, `pulse_width_us` as `pulse width` (the unit is shown apart)."""
    return re.sub(r"_(hz|us|s|ua|ma)$", "", key).replace("_", " ")


def held_fixed(group: str, amp_unit: str = "") -> str:
    """`frequency_hz=10|pulse_width_us=500` as `frequency 10 Hz, pulse width 500 µs`."""
    if not group:
        return "–"
    out = []
    for part in group.split("|"):
        k, sep, v = part.partition("=")
        if not sep:
            out.append(part)
            continue
        unit = {"frequency_hz": "Hz", "pulse_width_us": "µs", "train_duration_s": "s"}.get(k, amp_unit if k == "amplitude" else "")
        name = param_name(k)
        out.append(f"{name} {v}" + (f" {unit}" if unit else ""))
    return ", ".join(out)


def dose_tables(step: Step | None, ev_step: Step | None) -> dict[str, Any] | None:
    """Thresholds, EC50 and fulcrum per subject, from fits.csv / fulcrum.csv (else from
    summary.json `subjects`)."""
    if step is None:
        return None
    fits = read_table(find_file(step, "fits.csv")) if find_file(step, "fits.csv") else []
    if not fits:
        for subj, d in (step.summary.get("subjects") or {}).items() if isinstance(step.summary.get("subjects"), dict) else []:
            for f in (d or {}).get("fits") or []:
                if isinstance(f, dict):
                    fits.append({"subject": subj, **{k: ("" if v is None else v) for k, v in f.items()}})
    ful = read_table(find_file(step, "fulcrum.csv")) if find_file(step, "fulcrum.csv") else []
    if not ful:
        for subj, d in (step.summary.get("subjects") or {}).items() if isinstance(step.summary.get("subjects"), dict) else []:
            for f in (d or {}).get("fulcrum") or []:
                if isinstance(f, dict):
                    ful.append({"subject": subj, **{k: ("" if v is None else v) for k, v in f.items()}})
    if not fits and not ful:
        return None
    amp_unit = ""
    for f in fits:
        if f.get("x") == "amplitude" and f.get("x_unit"):
            amp_unit = str(f["x_unit"])
            break
    if not amp_unit and ev_step is not None:
        for r in recordings_of(ev_step).values():
            if isinstance(r.get("amplitude_unit"), str) and r["amplitude_unit"] not in ("", "n/a"):
                amp_unit = r["amplitude_unit"]
                break

    def unit_of(f: dict[str, Any]) -> str:
        u = str(f.get("x_unit") or "")
        if not u and f.get("x") == "amplitude":
            u = amp_unit
        if not u and f.get("x") == "frequency_hz":
            u = "Hz"
        return u

    def ci(lo: Any, hi: Any) -> str:
        return f" ({fmt(lo)}–{fmt(hi)})" if num(lo) is not None and num(hi) is not None else ""

    def subj_key(s: str) -> tuple[int, list[Any]]:
        return (1 if s == "pooled" else 0, natural(s))

    fits.sort(key=lambda f: (subj_key(str(f.get("subject", ""))), variable_key(str(f.get("variable", ""))),
                             str(f.get("x", "")), natural(str(f.get("group", "")))))
    rows, raw = [], []
    for f in fits:
        u = unit_of(f)
        x = str(f.get("x") or "")
        thr = num(f.get("threshold"))
        rows.append([
            str(f.get("subject") or "–"), variable_name(str(f.get("variable", ""))),
            param_name(x) + (f" ({u})" if u else ""), held_fixed(str(f.get("group") or ""), amp_unit), str(f.get("model") or "–"),
            fmt(thr) if thr is not None else "none reached",
            (fmt(f.get("ec50")) + ci(f.get("ec50_ci_low"), f.get("ec50_ci_high"))) if num(f.get("ec50")) is not None else "–",
            fmt(f.get("top")), fmt(f.get("r2")), fmt(f.get("n_levels") or f.get("n"), "int"),
            str(f.get("threshold_criterion") or "–"),
        ])
        raw.append(f)
    fit_table = {"header": ["Subject", "Series", "Parameter varied", "Held fixed", "Model", "Threshold", "EC50 (95 % CI)",
                            "Maximum change (top)", "r²", "Levels", "Threshold criterion"],
                 "kinds": ["text", "text", "text", "text", "text", "num", "num", "num", "num", "int", "text"],
                 "rows": rows, "raw": raw} if rows else None
    ful.sort(key=lambda f: (subj_key(str(f.get("subject", ""))), variable_key(str(f.get("variable", ""))),
                            num(f.get("frequency_hz")) or 0))
    frows = [[str(f.get("subject") or "–"), variable_name(str(f.get("variable", ""))), fmt(f.get("frequency_hz")),
              fmt(f.get("amplitude_at_fulcrum")) + ci(f.get("ci_low"), f.get("ci_high")),
              str(f.get("method") or "–"), str(f.get("note") or "")] for f in ful]
    ful_table = {"header": ["Subject", "Series", "Frequency (Hz)", f"Amplitude at the fulcrum{f' ({amp_unit})' if amp_unit else ''}",
                            "Method", "Note"], "kinds": ["text", "text", "num", "num", "text", "text"],
                 "rows": frows, "raw": ful} if frows else None
    n_thr = sum(1 for f in fits if num(f.get("threshold")) is not None)
    n_ec50 = sum(1 for f in fits if num(f.get("ec50")) is not None)
    subjects = sorted({str(f.get("subject")) for f in fits + ful if f.get("subject") not in (None, "", "pooled")},
                      key=natural)
    return {"fits": fit_table, "fulcrum": ful_table, "n_fits": len(fits), "n_threshold": n_thr, "n_ec50": n_ec50,
            "subjects": subjects, "pooled": any(str(f.get("subject")) == "pooled" for f in fits)}


# ----------------------------------------------------------------------------- the model

def sort_key(step: Step) -> tuple[int, str]:
    return (A.ORDER.index(step.app) if step.app in A.ORDER else len(A.ORDER), step.label)


def build_section(s: Step, rec_rows: dict[str, dict[str, Any]], order: list[str], issues: list[dict[str, str]],
                  params: dict[str, Any]) -> dict[str, Any]:
    info = A.APPS.get(s.app, {})
    recs = recordings_of(s)
    if s.summary and "recordings" not in s.summary:
        issues.append({"step": s.label, "problem": "summary.json has no `recordings` object"})
    order_here = [r for r in order if r in recs] + [r for r in recs if r not in order]
    figs, missing = figures_of(s, issues)
    for m in missing:
        issues.append({"step": s.label, "problem": f"figure {m} is listed in summary.json but not in the output"})
    max_f = params.get("MAX_FIGURES", 40)
    warnings, skipped = step_warnings(s)
    warnings = group_warnings(warnings, set(recs) | set(rec_rows) | set(prov_recordings(s)))
    if missing:
        warnings.append(f"{len(missing)} figure(s) listed in summary.json are missing from the step's output: "
                        + ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else ""))
    prov = s.provenance
    tools = prov.get("tools") if isinstance(prov.get("tools"), dict) else {}
    params_ = prov.get("parameters") if isinstance(prov.get("parameters"), dict) else {}
    # Nested parameter values (species preset tables) are shown in provenance.json, not here.
    params_ = {k: v for k, v in params_.items() if not isinstance(v, (dict, list))}
    statuses = Counter(str(r.get("status") or "ok") for r in prov_recordings(s).values())
    title = info.get("title") or humanise(s.app)
    if "/" in s.label:
        title += f" ({s.label.split('/', 1)[1]})"
    lic = licence_of(s)
    return {
        "app": s.app, "label": s.label, "rel": s.rel, "title": title, "known": s.app in A.APPS,
        "version": str(prov.get("version") or s.summary.get("version") or ""), "variant": prov.get("variant") or "",
        "about": info.get("about", ""), "methods": info.get("methods", ""), "research": A.RESEARCH,
        "tables_dir": "tables/" + s.label,
        "notices": notices_of(s), "licence": lic,
        "warnings": warnings, "warnings_visible": WARN_VISIBLE, "skipped": skipped,
        "n_recordings": len(recs),
        "headline": headline(s.app, recs, order_here),
        "figures": figs[:max_f], "omitted": figs[max_f:], "missing": missing,
        "tables": tables_of(s, issues), "parameters": params_, "tools": tools,
        "citations": [C.norm(c) for c in as_list(prov.get("citations"))],
        "wall_seconds": num(prov.get("wall_seconds")), "peak_rss_mb": num(prov.get("peak_rss_mb")),
        "statuses": dict(statuses), "recs": recs, "step": s,
    }


def build(found: Found, params: dict[str, Any], version: str) -> dict[str, Any]:
    steps = sorted(found.steps, key=sort_key)
    issues: list[dict[str, str]] = []
    for s in steps:
        for p in s.problems:
            issues.append({"step": s.label, "problem": p})
        files = [k for k in prov_recordings(s) if is_file_key(k)]
        if files:
            issues.append({"step": s.label, "problem": f"provenance.json `recordings` has {len(files)} entr"
                           f"{'y' if len(files) == 1 else 'ies'} keyed by an input file path, not a recording id "
                           f"({', '.join(files[:3])}{', ...' if len(files) > 3 else ''}): shown as input files not "
                           "read, not as recordings"})

    rec_rows = recordings_table(found, steps)
    order = sorted(rec_rows, key=natural)
    first_of: dict[str, Step] = {}
    for s in steps:
        first_of.setdefault(s.app, s)
    for app in A.ORDER:
        n = sum(1 for s in steps if s.app == app)
        if n > 1:
            issues.append({"step": app, "problem": f"linked {n} times: the key results use the first "
                                                   f"({first_of[app].label}); every copy has its own section"})

    # Which steps cover which recording, and which skipped it and why.
    covered: dict[str, list[str]] = {rid: [] for rid in order}
    missing_steps: dict[str, list[str]] = {rid: [] for rid in order}
    for s in steps:
        short = A.APPS.get(s.app, {}).get("short", s.app) + (f" ({s.label.split('/', 1)[1]})" if "/" in s.label else "")
        skipped = not_analysed(s)
        for rid in list(recordings_of(s)) + [r for r in prov_recordings(s) if not is_file_key(r)]:
            if rid in skipped:
                txt = f"{short}: {skipped[rid]}"
                if txt not in missing_steps.setdefault(rid, []):
                    missing_steps[rid].append(txt)
            elif short not in covered.setdefault(rid, []):
                covered[rid].append(short)
    recordings = []
    for rid in order:
        r = rec_rows[rid]
        recordings.append({
            "recording_id": rid, "subject": r["subject"], "species": r["species"] or "–",
            "duration": fmt(r["duration_s"], "dur"),
            "recorded": fmt(r["recorded_s"], "dur") if r["recorded_s"] is not None and r["duration_s"] is not None
            and r["recorded_s"] < r["duration_s"] - 1 else "",
            "types": ", ".join(TYPE_NAMES.get(t, t) for t in r["types"]) or "–", "type_keys": r["types"],
            "age": r["age"], "sex": r["sex"],
            "steps": covered.get(rid, []), "not_analysed": missing_steps.get(rid, []),
        })

    # Sections, physio-import's QC first.
    sections = [build_section(s, rec_rows, order, issues, params) for s in steps]
    imp = [s for s in steps if s.app == "physio-import"]
    qc = qc_section(imp, found.datasets, rec_rows)
    if qc and sections and sections[0]["app"] == "physio-import":
        sections[0]["qc"] = qc
        sections[0]["headline"] = None  # the QC table shows the same numbers
    for i, sec in enumerate(sections, start=1):
        sec["index"] = i + 2  # 1 Recordings, 2 Key results
        sec["anchor"] = f"step-{slug(sec['label'])}"

    # Key results.
    refs_all = [dict(r) for r in A.REFERENCE_VALUES]
    for s in steps:
        refs_all = [r for r in refs_all if not any(sr["key"] == r["key"] and sr["app"] == r["app"] and sr["species"] == r["species"]
                                                   for sr in step_reference_values(s))] + step_reference_values(s)
    key = {
        "hrv": resting_table(first_of.get("ecg-hrv"), REST_HRV, rec_rows, order, refs_all),
        "bp": resting_table(first_of.get("bp-resp"), REST_BP, rec_rows, order, refs_all),
        "dose": dose_tables(first_of.get("stim-dose-response"), first_of.get("stim-events")),
        "caveat": A.REFERENCE_CAVEAT,
    }
    for k in ("hrv", "bp"):
        if key[k] is not None:
            sec = next(x for x in sections if x["step"] is first_of["ecg-hrv" if k == "hrv" else "bp-resp"])
            key[k]["anchor"] = sec["anchor"]
            key[k]["notices"] = sec["notices"]
    if key["dose"] is not None:
        sec = next(x for x in sections if x["step"] is first_of["stim-dose-response"])
        key["dose"]["anchor"] = sec["anchor"]
        key["dose"]["notices"] = sec["notices"]
    key["any"] = any(key[k] for k in ("hrv", "bp", "dose"))

    # References in order of first appearance: steps (with their licence DOIs), reference values, datasets.
    datasets = find_datasets(found, steps, params)
    references: list[dict[str, Any]] = []
    index_of: dict[str, int] = {}

    def cite(doi: str) -> int | None:
        d = C.norm(doi)
        if not d:
            return None
        if d not in index_of:
            e = C.entry(d) if C.valid(d) else {"doi": d, "url": "", "known": False, "authors": "", "title": "",
                                                 "where": "", "kind": "unknown", "short": d, "year": ""}
            e["n"] = len(references) + 1
            references.append(e)
            index_of[d] = e["n"]
        return index_of[d]

    for sec in sections:
        sec["refs"] = [n for n in (cite(d) for d in sec["citations"]) if n]
        if sec.get("licence"):
            sec["licence"]["refs"] = [n for n in (cite(d) for d in sec["licence"]["dois"]) if n]
            sec["refs"] = sorted(set(sec["refs"]) | set(sec["licence"]["refs"]))
    for k in ("hrv", "bp"):
        for r in (key[k] or {}).get("refs", []):
            r["n"] = [n for n in (cite(d) for d in r["dois"]) if n]
    for ds in datasets:
        ds["n"] = cite(ds["doi"])
        ds["with_refs"] = [n for n in (cite(d) for d in ds["with"]) if n]
    for r in references:
        if not r["known"]:
            issues.append({"step": "references", "problem": f"DOI {r['doi']} is not in the report's citation table: "
                                                             "listed DOI-only"})

    # At a glance: one row per recording across the steps (first label of each app).
    glance_cols = [(label, app, k, kind) for label, app, k, kind in A.GLANCE
                   if app in first_of and any(r.get(k) not in (None, "") for r in recordings_of(first_of[app]).values())]
    glance_rows = []
    for rid in order:
        cells, raw = [], []
        for _, app, k, kind in glance_cols:
            v = recordings_of(first_of[app]).get(rid, {}).get(k)
            cells.append(fmt(v, kind))
            raw.append(v)
        if any(v not in (None, "") for v in raw):
            glance_rows.append({"recording_id": rid, "cells": cells, "raw": raw})
    glance = {"header": ["Recording"] + [c[0] for c in glance_cols], "cols": glance_cols, "rows": glance_rows}

    licences = [{"step": s["title"], "label": s["label"], "anchor": s["anchor"], **s["licence"]}
                for s in sections if s.get("licence")]
    apps_linked = {s.app for s in steps}
    workflows = [name for name, marker in A.WORKFLOW_MARKERS.items() if marker & apps_linked]
    if not workflows and apps_linked & {"ecg-hrv", "bp-resp"}:
        workflows = [name for name in A.WORKFLOWS if name not in A.WORKFLOW_MARKERS]
    title = params.get("REPORT_TITLE") or ("Physiology report: " + " + ".join(workflows) if workflows
                                           else "Physiology report")

    acknowledgements, cite_steps = [], []
    for sec in sections:
        sw = C.software_of(sec["app"])
        if sw and not any(a["app"] == sec["app"] for a in acknowledgements):
            acknowledgements.append({"app": sec["app"], "software": sw})
        works = [{"short": references[n - 1]["short"], "n": n} for n in sec["refs"]]
        if works or sw:
            cite_steps.append({"title": sec["title"], "software": [x["title"] for x in sw], "works": works})
    ref_works = []
    for k in ("hrv", "bp"):
        for r in (key[k] or {}).get("refs", []):
            for n in r["n"]:
                if n not in [w["n"] for w in ref_works]:
                    ref_works.append({"short": references[n - 1]["short"], "n": n})
    if ref_works:
        cite_steps.append({"title": "Published reference values", "software": [], "works": ref_works})
    apps_cited = []
    for sec in sections:
        info = C.app_info(sec["app"])
        k2 = (sec["app"], sec["version"])
        if k2 not in [(a["app"], a["version"]) for a in apps_cited]:
            apps_cited.append({"app": sec["app"], "version": sec["version"],
                               "repository": info.get("repository") or (f"https://github.com/pennsieve-apps/{sec['app']}"
                                                                        if sec["app"] in A.ORDER else "")})
    return {
        "title": title, "version": version, "parameters": params, "workflows": workflows,
        "recordings": recordings, "has_age": any(r["age"] for r in recordings),
        "has_sex": any(r["sex"] for r in recordings), "has_recorded": any(r["recorded"] for r in recordings),
        "has_dataset": bool(found.datasets),
        "sections": sections, "key": key, "glance": glance, "datasets": datasets, "references": references,
        "licences": licences, "issues": issues, "acknowledgements": acknowledgements, "apps_cited": apps_cited,
        "cite_steps": cite_steps, "n_figures": sum(len(s["figures"]) for s in sections),
        "missing_apps": [a for a in A.ORDER if a not in apps_linked and any(
            a in apps and (name in workflows) for name, apps in A.WORKFLOWS.items())],
        "port": A.PORT,
    }


def find_datasets(found: Found, steps: list[Step], params: dict[str, Any]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    def add(doi: str, how: str) -> None:
        d = C.norm(doi)
        if not C.valid(d) or d in out:
            return
        info = A.DATASETS.get(d, {})
        e = C.entry(d)
        out[d] = {"doi": d, "how": how, "licence": info.get("licence", ""), "with": list(info.get("with", [])),
                  "title": e["title"] or d, "creators": e["authors"], "year": e["year"], "known": e["known"],
                  "url": e["url"], "short": e["short"], "publisher": (C.lookup(d) or {}).get("publisher") or ""}

    for d in re.split(r"[\s,;]+", params.get("DATASET_DOIS") or ""):
        if d:
            add(d, "DATASET_DOIS parameter")
    paths: list[str] = []
    provs = [s.provenance for s in steps if s.app == "physio-import"] + [d.provenance for d in found.datasets]
    for p in provs:
        paths += as_list(p.get("inputs"))
        for r in (p.get("recordings") or {}).values() if isinstance(p.get("recordings"), dict) else []:
            if isinstance(r, dict):
                paths += as_list(r.get("source"))
    for d in found.datasets:
        paths += [r.get("source_path", "") for r in d.recordings]
    for pattern, doi in A.DATASET_PATHS:
        if any(re.search(pattern, p.split("#", 1)[0]) for p in paths):
            add(doi, "recognised from the source file paths")
    for ds in out.values():
        ds["with"] = [w for w in ds["with"] if C.norm(w) not in out]
    return list(out.values())
