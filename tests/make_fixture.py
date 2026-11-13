"""
Synthetic inputs for the report: for every app of the two physiology workflows, its top folder with
provenance.json, summary.json (recordings, figures with captions, tables, warnings, notice), small
PNG figures and CSV tables shaped as conventions.md describes and as the finished apps write them
(physio-import's qc port, stim-events, ecg-hrv, bp-resp, stim-dose-response). Standard library
only. Also used by app.yml `review.generate`.

Three recordings:
- sub-h01_rec-rest: human, resting, ECG + calibrated BP + respiration (HRV workflow);
- sub-h02_rec-rest: human, ECG only: bp-resp skips it (missing signal, not a failure);
- sub-p1_rec-vns: pig, ECG + device HR + uncalibrated BP + stimulation trigger, a 4 x 3 grid of
  vagus nerve stimulation trains (amplitude x frequency) with a planted bradycardia that grows
  with amplitude; stim-dose-response fits a threshold and EC50 and finds a fulcrum at 30 Hz.

Deliberate quirks the tests rely on: stim-events declares a test `licence_notice` (with a link and
a DOI); physio-import lists a skipped input file in `skipped_files` and keeps CRITICAL NWB Inspector
messages about missing subject metadata (as the real app does); stim-events and stim-dose-response
skip the human recordings (no stimulation); stim-dose-response has an upper-bound threshold, a fit
blanked because the response changes sign, and a group with one tested level; bp-resp flags a
pressure level step, a drift and a channel choice; one ecg-hrv figure path is relative to the port
folder (`ecg-hrv/figures/...`).

    python -m tests.make_fixture OUT [--layout linked|flat|both]

linked: OUT/linked/<port>/<app>/... (qc/physio-import with its recordings.csv and channels.csv
copies, events/stim-events, hrv/ecg-hrv, bp/bp-resp, responses/stim-dose-response), as a compute
node lays out the report's INPUT_DIR;
flat: everything side by side at OUT/flat/, with physio-import's physio port (recordings.csv,
channels.csv, provenance.json) merged at the root.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import struct
from pathlib import Path

RECS = [
    {"recording_id": "sub-h01_rec-rest", "subject": "h01", "species": "human", "duration_s": 1800.0,
     "types": ["ecg", "bp", "resp"], "age": "", "sex": ""},
    {"recording_id": "sub-h02_rec-rest", "subject": "h02", "species": "human", "duration_s": 600.0,
     "types": ["ecg"], "age": "", "sex": ""},
    {"recording_id": "sub-p1_rec-vns", "subject": "p1", "species": "pig", "duration_s": 432.8, "recorded_s": 361.5,
     "types": ["ecg", "bp", "hr", "stim"], "age": "P3M", "sex": "F"},
]
IDS = [r["recording_id"] for r in RECS]
H1, H2, P1 = IDS
STARTED = "2026-11-13T12:00:00Z"
FINISHED = "2026-11-13T12:00:10Z"
AMPS = [250, 500, 1000, 2000]          # uA
FREQS = [2, 10, 30]                    # Hz

CITES = {
    "physio-import": ["10.7554/eLife.78362", "10.3389/fninf.2014.00010", "10.13026/9njx-6322",
                      "10.1161/01.CIR.101.23.e215"],
    "stim-events": ["10.7554/eLife.78362", "10.1038/sdata.2016.44"],
    "ecg-hrv": ["10.3758/s13428-020-01516-y", "10.13026/9njx-6322", "10.1161/01.CIR.93.5.1043",
                "10.1080/03091902.2019.1640306", "10.3389/fphys.2018.01390"],
    "bp-resp": ["10.3758/s13428-020-01516-y", "10.1109/CIC.2003.1291140", "10.1161/01.HYP.12.2.214",
                "10.1152/ajpregu.00709.2002", "10.1088/1361-6579/aad7e6", "10.1016/j.biopsycho.2011.11.009",
                "10.7554/eLife.78362"],
    "stim-dose-response": ["10.1038/s41592-019-0686-2", "10.1109/TAC.1974.1100705", "10.1214/aos/1176344552",
                           "10.1113/JP274678"],
}
# A licence notice with a link and a DOI, and a string that must never become a link.
LICENCE = ("Test terms: example parameter tables for non-commercial research only; see https://example.org/terms "
           "and cite 10.1113/JP274678. Not a link: javascript:alert(1).")
FULCRUM_NOTICE = ("Research outputs: responses, thresholds and EC50 values describe these recordings and are not "
                  "clinical findings or dosing recommendations. The neural fulcrum was defined by Ardell et al. (2017) "
                  "for chronic, duty-cycled vagus nerve stimulation in conscious animals.")


# ----------------------------------------------------------------------------- writers

def wjson(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8")


def wcsv(path: Path, header: list[str], rows: list[list], delimiter: str = ",") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=delimiter, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def png(path: Path, title: str, w: int = 480, h: int = 260) -> None:
    """A small PNG drawn with the standard library only (the review generator image has no
    Pillow): a framed panel with a zig-zag trace, its shade derived from the title."""
    import zlib

    path.parent.mkdir(parents=True, exist_ok=True)
    shade = 200 + sum(title.encode()) % 50
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            border = x < 3 or y < 3 or x >= w - 3 or y >= h - 3
            trace = abs(y - (h // 2 + ((x // 10) % 2 * 2 - 1) * (x % 10) * 4)) < 2
            row += bytes((31, 78, 140) if border else (200, 80, 40) if trace else (shade, shade, 252))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def prov(app: str, recordings: dict, params: dict, tools: dict | None = None, **extra) -> dict:
    p = {"app": app, "version": "0.1.0", "variant": None,
         "tools": {"python": "3.12.16", **(tools or {"numpy": "2.5.4"})},
         "parameters": params, "inputs": ["physio/recordings.csv"], "started": STARTED, "finished": FINISHED,
         "wall_seconds": 3.2, "peak_rss_mb": 250.0, "threads": {"requested": 0, "used": 1, "why": "test"},
         "recordings": recordings, "citations": CITES.get(app, []), "licence_notice": None}
    p.update(extra)
    return p


def ok(**kw) -> dict:
    return {"status": "ok", "seconds": 1.0, **kw}


def skipped(reason: str, **kw) -> dict:
    return {"status": "skipped", "seconds": 0.1, "reason": reason, **kw}


def species(rid: str) -> str:
    return next(r["species"] for r in RECS if r["recording_id"] == rid)


# ----------------------------------------------------------------------------- the apps

def physio_import(physio: Path | None, qc: Path) -> None:
    """physio-import's qc port (qc/physio-import/...) and, when given, its physio port index."""
    recs_prov = {r["recording_id"]: ok(species=r["species"], source=f"lab-export/{r['subject']}/rec.edf")
                 for r in RECS}
    p = prov("physio-import", recs_prov, {"SPECIES": "auto", "FIGURES": "true", "INSPECTOR": "true", "THREADS": "0"},
             # An input file that is not a recording, as the app lists it.
             skipped_files={"lab-export/notes.txt": {"status": "skipped", "source_format": "txt", "reason":
                                                     "no time column (Time, t, Time (s), ...) and SAMPLING_RATE not set"}},
             tools={"pynwb": "4.2.0", "neo": "0.14.6", "wfdb": "4.3.1", "nwbinspector": "0.7.2"},
             inputs=["lab-export/h01/rec.edf", "lab-export/h02/rec.edf", "lab-export/p1/rec.edf"])
    top = qc / "physio-import"
    # The physio port's index, and its copies in the qc port (recordings.csv, channels.csv).
    for folder in ([physio] if physio is not None else []) + [top]:
        wcsv(folder / "recordings.csv",
             ["recording_id", "subject", "session", "label", "path", "species", "start_time", "duration_s",
              "recorded_s", "n_segments", "channel_types", "source_format", "source_path", "metadata_source", "age",
              "sex", "task", "run"],
             [[r["recording_id"], r["subject"], "", r["recording_id"].split("rec-")[1],
               f"sub-{r['subject']}/{r['recording_id']}.nwb", r["species"], "", r["duration_s"],
               r.get("recorded_s", r["duration_s"]), 1, "|".join(r["types"]), "edf", f"lab-export/{r['subject']}/rec.edf",
               "file", r["age"], r["sex"], "", ""] for r in RECS])
        rows = []
        for r in RECS:
            for t in r["types"]:
                cal = "false" if (r["recording_id"] == P1 and t in ("bp", "ecg")) else "true"
                rows.append([r["recording_id"], t, t, t.upper(), {"ecg": "V", "bp": "mmHg", "hr": "bpm"}.get(t, "a.u."),
                             1000, 1000, cal, 1, "", "name", "good", ""])
        wcsv(folder / "channels.csv", ["recording_id", "channel", "type", "original_name", "unit", "sampling_rate_hz",
                                       "n_samples", "calibrated", "scale", "site", "typing", "status",
                                       "status_description"], rows)
    if physio is not None:
        wcsv(physio / "events.tsv", ["recording_id", "onset", "duration", "trial_type", "label"], [], delimiter="\t")
        wjson(physio / "provenance.json", p)
    qrows = []
    for r in RECS:
        for t in r["types"]:
            qrows.append([r["recording_id"], t, "n_samples", 1000, ""])
            status = "saturated" if (r["recording_id"] == H1 and t == "bp") else "good"
            qrows.append([r["recording_id"], t, "status", status,
                          "3.1% of samples stuck at the maximum (300) in runs of 30 samples or more" if status != "good"
                          else ""])
        qrows.append([r["recording_id"], "", "nwbinspector_messages", 3, "BEST_PRACTICE_SUGGESTION, CRITICAL"])
        qrows.append([r["recording_id"], "", "nwbinspector_critical_kept", "check_subject_age",
                      "Subject is missing age and date_of_birth. (missing subject metadata: reported, the recording is kept)"])
    wcsv(top / "qc.csv", ["recording_id", "channel", "check", "value", "note"], qrows)
    wcsv(top / "nwbinspector.csv", ["recording_id", "importance", "check", "object", "message"],
         [[H1, "BEST_PRACTICE_SUGGESTION", "check_description", "Subject subject", "Description is missing."]])
    figs = []
    for r in RECS:
        rel = f"figures/{r['recording_id']}_overview.png"
        png(top / rel, r["recording_id"] + "overview")
        figs.append({"path": rel, "caption": f"{r['recording_id']}: every channel imported, the whole recording on the "
                     "left and a 10 s zoom on the right. Check that each channel looks like the signal its type says."})
    wjson(top / "summary.json", {
        "app": "physio-import", "version": "0.1.0",
        "recordings": {r["recording_id"]: {"n_channels": len(r["types"]), "duration_s": r["duration_s"],
                                           "recorded_s": r.get("recorded_s", r["duration_s"]), "n_markers": 0,
                                           "n_trials": 12 if r["recording_id"] == P1 else 0,
                                           "n_channels_flagged": 1 if r["recording_id"] == H1 else 0,
                                           "nwbinspector_messages": 3} for r in RECS},
        "figures": figs,
        "tables": [{"path": "recordings.csv", "caption": "One row per recording (copy of the physio port's)."},
                   {"path": "channels.csv", "caption": "One row per channel (copy of the physio port's)."},
                   {"path": "qc.csv", "caption": "Per-channel checks."},
                   {"path": "nwbinspector.csv", "caption": "NWB Inspector messages."}],
        "warnings": [f"{H1}: bp (BP) saturated: 3.1% of samples stuck at the maximum (300) in runs of 30 samples or "
                     "more: clipped amplifier or transducer?"],
        "notice": "Uncalibrated ECG or blood pressure in 1 recording(s): their amplitudes are relative (timing and "
                  "shape only).",
    })
    wjson(top / "provenance.json", p)


def trains() -> list[dict]:
    out, t = [], 10.0
    for f in FREQS:
        for a in AMPS:
            out.append({"onset": t, "amplitude": a, "frequency_hz": f})
            t += 25.0
    return out


def stim_events(top: Path) -> None:
    rows = []
    for i, tr in enumerate(trains(), 1):
        rows.append([P1, f"{tr['onset']:.3f}", "5", "stimulation", f"stim-{i:04d}", tr["amplitude"], "uA", 500,
                     tr["frequency_hz"], 5, "n/a", "n/a", int(5 * tr["frequency_hz"]), "cathodic", "biphasic",
                     "cervical vagus right", "n/a", "n/a", "n/a", "hdf5-attrs|trigger"])
    wcsv(top / "events.tsv", ["recording_id", "onset", "duration", "trial_type", "event_id", "amplitude",
                              "amplitude_unit", "pulse_width_us", "frequency_hz", "train_duration_s", "train_on_s",
                              "train_off_s", "n_pulses", "polarity", "waveform", "site", "contact", "condition",
                              "label", "source"], rows, delimiter="\t")
    wcsv(top / "stim_summary.csv", ["recording_id", "n_stimulations", "parameters_varied", "ranges"],
         [[P1, 12, "amplitude|frequency_hz", "amplitude 250-2000 uA; frequency_hz 2-30"]])
    wcsv(top / "qc.csv", ["recording_id", "check", "value", "note"],
         [[P1, "stim_channel", "stim", "trigger, threshold 0.5"]])
    png(top / f"figures/{P1}_timeline.png", "timeline")
    reason = ("no stimulation found: no stimulation channel with pulses or epochs, no parameter table rows, no "
              "stimulation markers and no parameters in the file or folder names")
    wjson(top / "summary.json", {
        "app": "stim-events", "version": "0.1.0",
        "recordings": {P1: {"n_stimulations": 12, "n_blocks": 0, "n_baseline": 0,
                            "parameters_varied": ["amplitude", "frequency_hz"], "amplitude_min": 250.0,
                            "amplitude_max": 2000.0, "amplitude_unit": "uA", "frequency_hz_min": 2.0,
                            "frequency_hz_max": 30.0, "total_stimulation_s": 60.0, "sources": ["hdf5-attrs", "trigger"],
                            "n_qc_flags": 0}},
        "figures": [{"path": f"figures/{P1}_timeline.png", "caption": f"{P1}: every stimulation train found, one row "
                     "per pulse frequency, coloured by amplitude. Check that the trains match the protocol."}],
        "tables": [{"path": "events.tsv", "caption": "One row per stimulation train with its parameters."},
                   {"path": "stim_summary.csv", "caption": "Per recording: trains and parameter ranges."},
                   {"path": "qc.csv", "caption": "Checks."}],
        "warnings": [],
    })
    wjson(top / "provenance.json", prov(
        "stim-events", {H1: skipped(reason, species="human"), H2: skipped(reason, species="human"),
                        P1: ok(species="pig", sources=["hdf5-attrs", "trigger"])},
        {"TRAIN_GAP_S": "2", "MIN_GAP_S": "10"}, licence_notice=LICENCE))


HRV = {H1: {"n_beats": 2150, "mean_hr_bpm": 71.7, "sdnn_ms": 48.2, "rmssd_ms": 35.1, "lf_hf": 1.9, "pct_artifact": 0.4,
            "pct_ectopic": 0.1, "detector_agreement": 0.998, "signal_quality": 0.91, "n_stimulation_windows": 0},
       H2: {"n_beats": 640, "mean_hr_bpm": 64.0, "sdnn_ms": 102.0, "rmssd_ms": 81.5, "lf_hf": 0.8, "pct_artifact": 1.2,
            "pct_ectopic": 0.0, "detector_agreement": 0.991, "signal_quality": 0.84, "n_stimulation_windows": 0},
       P1: {"n_beats": 430, "mean_hr_bpm": 71.25, "sdnn_ms": 31.92, "rmssd_ms": 23.74, "lf_hf": 2.449,
            "pct_artifact": 0.47, "pct_ectopic": 0.0, "detector_agreement": 1.0, "signal_quality": 0.826,
            "n_stimulation_windows": 36, "hr_device_mae_bpm": 0.83}}


def ecg_hrv(top: Path) -> None:
    beats, series, hrv, qc, feats, figs = [], [], [], [], [], []
    for rid, h in HRV.items():
        rr = 60000.0 / h["mean_hr_bpm"]
        for b in range(1, 21):
            beats.append([rid, b, round(b * rr / 1000, 3), round(rr, 1), "N", "neurokit"])
        for k in range(40):
            series.append([rid, k * 0.25, "hr_bpm", h["mean_hr_bpm"], "true"])
        for metric, key in (("mean_nn", None), ("sdnn", "sdnn_ms"), ("rmssd", "rmssd_ms"), ("lf_hf", "lf_hf")):
            hrv.append([rid, "recording", metric, round(rr, 1) if key is None else h[key], h["n_beats"], 1800])
        qc.append([rid, "neurokit", h["n_beats"], h["pct_ectopic"], h["pct_artifact"], h["detector_agreement"],
                   h["signal_quality"]])
        feats.append([rid, "ecg", "hrv_rmssd", h["rmssd_ms"]])
        for what in ("heart-rate", "hrv"):
            rel = f"figures/{rid}_{what}.png"
            png(top / rel, rid + what)
            # One path relative to the port folder (tolerated): ecg-hrv/figures/...
            figs.append({"path": ("ecg-hrv/" + rel) if (rid == H2 and what == "hrv") else rel,
                         "caption": f"{rid}: {'heart rate beat by beat' if what == 'heart-rate' else 'Poincare plot and RR spectrum'}; "
                                    "check that every QRS complex carries one circle."})
    wcsv(top / "beats.csv", ["recording_id", "beat", "time_s", "rr_ms", "label", "detector"], beats)
    wcsv(top / "series.csv", ["recording_id", "time_s", "variable", "value", "valid"], series)
    wcsv(top / "hrv.csv", ["recording_id", "scope", "metric", "value", "n_beats", "window_s"], hrv)
    wcsv(top / "qc.csv", ["recording_id", "detector", "n_beats", "pct_ectopic", "pct_artifact",
                          "agreement_with_second_detector", "signal_quality"], qc)
    wcsv(top / "features.csv", ["recording_id", "channel", "feature", "value"], feats)
    wjson(top / "summary.json", {
        "app": "ecg-hrv", "version": "0.1.0", "recordings": HRV, "figures": figs,
        "tables": [{"path": n, "caption": f"{n} of ecg-hrv"} for n in
                   ("beats.csv", "series.csv", "hrv.csv", "qc.csv", "features.csv")],
        "warnings": [],
        "notice": "Research output: heart rate and HRV computed automatically from the ECG, for research; not a "
                  "clinical ECG or rhythm interpretation. ECG uncalibrated in 1 recording(s): timing-derived measures "
                  "only.",
    })
    wjson(top / "provenance.json", prov(
        "ecg-hrv", {rid: ok(species=species(rid), channel="ecg", calibrated=rid != P1) for rid in HRV},
        {"SPECIES": "auto", "DETECTOR": "neurokit", "SPECIES_PRESETS": {"pig": {"hf_hz": [0.09, 2.0]}}},
        tools={"neurokit2": "0.3.0", "wfdb": "4.3.1"}))


BP = {H1: {"calibrated": True, "bp_beats": 2140, "bp_pct_artifact": 0.6, "pulse_rate_bpm": 71.5, "sbp_mmhg": 121.4,
           "dbp_mmhg": 72.3, "map_mmhg": 90.1, "pp_mmhg": 49.1, "resp_rate_bpm": 14.2, "resp_amplitude": 0.41,
           "resp_amplitude_unit": "a.u.", "rr_source": "hrv", "brs_sequence_all": 11.3, "brs_n_sequences": 84,
           "brs_alpha_lf": 9.8, "brs_alpha_hf": 14.6, "brs_transfer_lf": 8.9, "rsa_p2t_ms": 61.2,
           "rsa_porges_bohrer": 6.1},
      P1: {"calibrated": False, "bp_beats": 428, "bp_pct_artifact": 1.1, "pulse_rate_bpm": 71.0, "rr_source": None}}


def bp_resp(top: Path) -> None:
    beats, brs, rsa, figs = [], [], [], []
    for rid, h in BP.items():
        for b in range(1, 11):
            beats.append([rid, b, b * 0.84, h.get("sbp_mmhg", ""), h.get("dbp_mmhg", ""), h.get("map_mmhg", ""),
                          h.get("pp_mmhg", ""), str(h["calibrated"]).lower(), b * 0.84 - 0.2, 840, "N"])
        for m in ("sequence-up", "sequence-down", "sequence-all", "alpha-lf", "alpha-hf", "transfer-lf"):
            v = h.get({"sequence-all": "brs_sequence_all", "alpha-lf": "brs_alpha_lf", "alpha-hf": "brs_alpha_hf",
                       "transfer-lf": "brs_transfer_lf"}.get(m, "_"), "")
            brs.append([rid, m, v, 84 if v != "" else "", 0.7 if v != "" else "", "true" if v != "" else "false", 0,
                        h["rr_source"] or "", "" if v != "" else "blood pressure uncalibrated (no mmHg)"])
        rsa.append([rid, "p2t", h.get("rsa_p2t_ms", ""), "ms", 400 if rid == H1 else "",
                    "" if rid == H1 else "no respiration channel"])
        rel = f"figures/{rid}_bp.png"
        png(top / rel, rid + "bp")
        figs.append({"path": rel, "caption": f"{rid}: beat-to-beat systolic, diastolic and mean pressure; look for "
                                             "steps or drift that suggest a calibration change."})
        if rid == H1:
            png(top / f"figures/{rid}_brs.png", rid + "brs")
            figs.append({"path": f"figures/{rid}_brs.png", "caption": f"{rid}: baroreflex sequences (RR against SBP); "
                                                                       "steeper lines mean a stronger baroreflex."})
    wcsv(top / "bp_beats.csv", ["recording_id", "beat", "time_s", "sbp_mmhg", "dbp_mmhg", "map_mmhg", "pp_mmhg",
                                "calibrated", "onset_s", "ibi_ms", "label"], beats)
    wcsv(top / "breaths.csv", ["recording_id", "breath", "onset_s", "duration_s", "rate_bpm", "amplitude",
                               "inspiration_s", "expiration_s", "label"], [[H1, 1, 2.0, 4.2, 14.2, 0.41, 1.6, 2.6, "N"]])
    wcsv(top / "series.csv", ["recording_id", "time_s", "variable", "value", "valid"],
         [[H1, k * 0.25, "map_mmhg", 90.1, "true"] for k in range(20)])
    wcsv(top / "brs.csv", ["recording_id", "method", "value_ms_per_mmhg", "n", "coherence", "valid", "lag_beats",
                           "rr_source", "note"], brs)
    wcsv(top / "rsa.csv", ["recording_id", "method", "value", "unit", "n_breaths", "note"], rsa)
    wcsv(top / "qc.csv", ["recording_id", "check", "value", "note"], [
        [P1, "calibrated", "false", "timing only"],
        [H1, "bp_level_steps", 1, "abrupt level changes of the systolic pressure (> 8 mmHg): 76 s (-8 mmHg); absolute "
                                  "pressure levels are doubtful, beat-to-beat changes (BRS) less affected"],
        [H1, "bp_drift", 34, "median systolic pressure of the last 2 min minus the first 2 min (mmHg)"],
        [P1, "ecg_channel_choice", "ecg", "2 ECG channels: the one with the higher signal quality"]])
    wcsv(top / "features.csv", ["recording_id", "channel", "feature", "value"], [[H1, "", "brs_sequence_all", 11.3]])
    wjson(top / "summary.json", {
        "app": "bp-resp", "version": "0.1.0", "recordings": BP, "figures": figs,
        "tables": [{"path": n, "caption": f"{n} of bp-resp"} for n in
                   ("bp_beats.csv", "breaths.csv", "series.csv", "brs.csv", "rsa.csv", "qc.csv", "features.csv")],
        "warnings": [],
        "notice": f"Blood pressure is uncalibrated in {P1}: pulse timing only; no pressures in mmHg and no baroreflex "
                  "sensitivity for these recordings.",
    })
    wjson(top / "provenance.json", prov(
        "bp-resp", {H1: ok(species="human", calibrated=True), P1: ok(species="pig", calibrated=False),
                    H2: skipped("no blood pressure or respiration channel", species="human")},
        {"SPECIES": "auto", "SSF_THRESHOLD": "0.5"}, tools={"neurokit2": "0.3.0"}))


def hr_delta(amp: float, freq: float) -> float:
    """The planted response: tachycardia at low amplitude turning into a bradycardia that grows with
    amplitude (sigmoid, EC50 800 uA), stronger at higher frequency."""
    brady = -12.0 * (freq / 30.0) / (1.0 + (800.0 / amp) ** 3)
    return round(brady + 2.0 * (freq / 30.0), 3)


def stim_dose_response(top: Path) -> None:
    resp, fits, surface, fulcrum = [], [], [], []
    for i, tr in enumerate(trains(), 1):
        d = hr_delta(tr["amplitude"], tr["frequency_hz"])
        resp.append([P1, f"stim-{i:04d}", "hr_bpm", 71.0, 71.0 + d, 71.2, d, round(100 * d / 71.0, 3), d, 3.2, 6.1,
                     1.0, "p1", "bpm", "ecg-hrv", tr["onset"], 5, "stimulation", "true", "", tr["amplitude"], "uA",
                     500, tr["frequency_hz"]])
        surface.append(["p1", "hr_bpm", tr["amplitude"], tr["frequency_hz"], d, "", 1, "", "stimulation", "bpm", "pig"])
    # 30 Hz: a Hill fit. 10 Hz: the response changes sign (fulcrum): the monotone fit is blanked.
    # 2 Hz: a threshold that is only an upper bound. Plus a group with one tested level (no fit).
    for f in FREQS:
        fitted, blank = f == 30, f == 10
        fits.append(["p1", P1, "hr_bpm", "amplitude", "uA", f"frequency_hz={f}", "hill" if fitted else
                     ("none" if blank else "linear"), 500 if fitted else (1000 if f == 2 else ""),
                     "auto: 5% of baseline (3.55 bpm) > 3 SD of baseline (1.2 bpm)",
                     812.4 if fitted else "", -10.1 if fitted else ("" if blank else -1.2), 2.0 if fitted else "",
                     3.0 if fitted else "", 0.97 if fitted else ("" if blank else 0.41), 4, 21.3, "bpm", "stimulation",
                     4, 1, 3.55, "decrease", 640.2 if fitted else "", 1020.7 if fitted else "",
                     "upper" if f == 2 else ("bracketed" if fitted else ""),
                     "the response changes sign along x (fulcrum.csv): the monotone fit's slope, top and EC50 are "
                     "left empty" if blank else ("threshold is an upper bound: the next lower tested level was not "
                                                 "analysed or not tested" if f == 2 else "")])
    fits.append(["p1", P1, "rr_ms", "frequency_hz", "Hz", "amplitude=2000", "none", "", "auto", "", "", "", "", "", 3,
                 "", "ms", "stimulation", 3, 1, 42.0, "", "", "", "", "no level exceeded the criterion"])
    fits.append(["p1", P1, "hr_bpm", "pulse_width_us", "us", "amplitude=2000;frequency_hz=30", "none", "", "auto", "", "",
                 "", "", "", 1, "", "bpm", "stimulation", 1, 1, 3.55, "", "", "", "",
                 "only one level of x was tested in this group: no fit, no threshold"])
    fulcrum.append(["p1", "hr_bpm", 30, 612.5, "linear interpolation between the bracketing level means", "", "",
                    "frequency_hz=30", P1, "250|500|1000|2000", "1.9|0.6|-5.1|-8.9", "pig",
                    "tachycardia to bradycardia; no CI: one train per level"])
    wcsv(top / "responses.csv", ["recording_id", "event_id", "variable", "baseline", "during", "after", "delta",
                                 "pct_change", "peak_delta", "time_to_peak_s", "recovery_s", "valid_fraction", "subject",
                                 "unit", "series_source", "onset", "duration", "trial_type", "included",
                                 "exclusion_reason", "amplitude", "amplitude_unit", "pulse_width_us", "frequency_hz"], resp)
    wcsv(top / "fits.csv", ["subject", "recording_id", "variable", "x", "x_unit", "group", "model", "threshold",
                            "threshold_criterion", "ec50", "top", "bottom", "slope", "r2", "n", "aic", "unit",
                            "trial_type", "n_levels", "n_subjects", "criterion_value", "direction", "ec50_ci_low",
                            "ec50_ci_high", "threshold_bound", "note"], fits)
    wcsv(top / "surface.csv", ["subject", "variable", "amplitude", "frequency_hz", "mean_delta", "sd", "n", "group",
                               "trial_type", "unit", "species"], surface)
    wcsv(top / "fulcrum.csv", ["subject", "variable", "frequency_hz", "amplitude_at_fulcrum", "method", "ci_low",
                               "ci_high", "group", "recording_id", "levels", "level_means", "species", "note"], fulcrum)
    wcsv(top / "features.csv", ["recording_id", "channel", "feature", "value"],
         [[P1, "", "dose_ec50_hr_bpm_amplitude_frequency_hz_30", 812.4]])
    figs = []
    for what, cap in (("timecourse", "change in heart rate from its baseline, aligned to train onset, one line per "
                                     "amplitude; look for the size, direction and timing of the response"),
                      ("dose_response", "change in heart rate against amplitude with the chosen model; dotted lines "
                                        "mark the threshold, diamonds the EC50"),
                      ("surface", "mean change in heart rate per amplitude x frequency; look for where the response "
                                  "changes direction")):
        rel = f"figures/p1_hr_bpm_{what}.png"
        png(top / rel, what)
        figs.append({"path": rel, "caption": f"Subject p1: {cap}."})
    reason = "no stimulation events for this recording in events.tsv"
    wjson(top / "summary.json", {
        "app": "stim-dose-response", "version": "0.1.0",
        "recordings": {P1: {"subject": "p1", "species": "pig", "status": "ok", "n_trains": 12, "n_trains_included": 12,
                            "variables": ["hr_bpm", "rr_ms"], "max_abs_delta_hr_bpm": -9.92,
                            "max_abs_delta_rr_ms": 151.3},
                       H1: {"subject": "h01", "species": "human", "status": "skipped", "reason": reason},
                       H2: {"subject": "h02", "species": "human", "status": "skipped", "reason": reason}},
        "subjects": {"p1": {"fits": [{"variable": "hr_bpm", "x": "amplitude", "group": "frequency_hz=30",
                                      "model": "hill", "threshold": 500.0, "ec50": 812.4, "ec50_ci_low": 640.2,
                                      "ec50_ci_high": 1020.7, "top": -10.1, "r2": 0.97, "n": 4, "n_levels": 4,
                                      "unit": "bpm"}],
                            "fulcrum": [{"variable": "hr_bpm", "frequency_hz": 30, "amplitude_at_fulcrum": 612.5,
                                         "ci_low": None, "ci_high": None, "group": "frequency_hz=30"}]}},
        "figures": figs,
        "tables": [{"path": n, "caption": f"{n} of stim-dose-response"} for n in
                   ("responses.csv", "fits.csv", "surface.csv", "fulcrum.csv")],
        "warnings": [],
        "notice": FULCRUM_NOTICE,
    })
    wjson(top / "provenance.json", prov(
        "stim-dose-response", {P1: ok(species="pig", subject="p1"), H1: skipped(reason, species="human"),
                               H2: skipped(reason, species="human")},
        {"SPECIES": "auto", "BASELINE_S": "auto", "MIN_LEVELS": "4", "SEED": "42"},
        tools={"scipy": "1.18.1", "statsmodels": "0.15.0"}))


APPS = {"stim-events": ("events", stim_events), "ecg-hrv": ("hrv", ecg_hrv), "bp-resp": ("bp", bp_resp),
        "stim-dose-response": ("responses", stim_dose_response)}


def write(root: Path, layout: str = "linked", apps: list[str] | None = None, qc: bool = True) -> Path:
    """Write one layout under root; returns the input folder."""
    apps = list(APPS) if apps is None else apps
    base = root / layout
    if layout == "linked":
        if qc:
            physio_import(None, base / "qc")
        for app in apps:
            port, fn = APPS[app]
            fn(base / port / app)
    else:
        if qc:
            physio_import(base, base)
        for app in apps:
            APPS[app][1](base / app)
    return base


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--layout", choices=["linked", "flat", "both"], default="linked")
    args = ap.parse_args()
    for layout in (("linked", "flat") if args.layout == "both" else (args.layout,)):
        print("wrote", write(args.out, layout))


if __name__ == "__main__":
    main()
