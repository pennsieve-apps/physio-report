"""
What the report knows about the physiology apps: their order in the workflows, a title, a paragraph
on what each does (for a physiologist), a methods sentence, which of their summary.json
per-recording numbers are the headline numbers, the published reference values shown next to the
resting numbers, and the demo datasets.

Everything else about a step (its figures and captions, warnings, numbers) is read from its own
summary.json and provenance.json; an app that is not listed here is rendered generically.

Headline columns are (label, key, kind); kind is how the number is written: `int`, `num` (four
significant digits), `rate` (two decimals), `pct` (a 0-1 fraction as a percentage), `dur` (seconds
as a duration), `bool`, `text`. Columns whose key no recording has are left out, so an app that
renames a key loses one column, not the section; when none is present the section falls back to
the generic table.
"""
from __future__ import annotations

WORKFLOWS = {
    "Cardiovascular Response to Nerve Stimulation": ["physio-import", "stim-events", "ecg-hrv", "bp-resp",
                                                     "stim-dose-response"],
    "Heart Rate Variability and Baroreflex": ["physio-import", "ecg-hrv", "bp-resp"],
}
# A workflow is named when one of its own apps is linked (physio-import and the shared steps say
# nothing about which one ran).
WORKFLOW_MARKERS = {"Cardiovascular Response to Nerve Stimulation": {"stim-events", "stim-dose-response"}}

ORDER = ["physio-import", "stim-events", "ecg-hrv", "bp-resp", "stim-dose-response"]

# Input port of each app (conventions.md, Ports).
PORT = {"physio-import": "qc", "stim-events": "events", "ecg-hrv": "hrv", "bp-resp": "bp",
        "stim-dose-response": "responses"}

RESEARCH = "Research output, not a clinical finding."

APPS: dict[str, dict] = {
    "physio-import": {
        "title": "Import and signal quality",
        "short": "Import",
        "about": (
            "physio-import read each recording from its acquisition format, decided the type of every channel (ECG, "
            "blood pressure, respiration, nerve, stimulation, device heart rate, ...) from a mapping file, the channel "
            "name or its content, applied the calibration the source gives, and wrote one NWB file per recording, "
            "checked with NWB Inspector. The checks below flag channels that are flat, saturated (clipped at the "
            "amplifier's or transducer's limits) or noisy. A flagged channel, an uncalibrated pressure or a "
            "recording with long gaps deserves a look at its overview figure before its results are interpreted."),
        "methods": (
            "Recordings were imported with physio-import (Neo, WFDB for Python, pyEDFlib and other readers), channels "
            "typed and calibrated, written as NWB 2.x files (PyNWB) and checked with NWB Inspector and per-channel "
            "flat, saturation and noise checks"),
        "headline": [
            ("Duration", "duration_s", "dur"),
            ("Covered by samples", "recorded_s", "dur"),
            ("Channels", "n_channels", "int"),
            ("Channels flagged", "n_channels_flagged", "int"),
            ("Trials", "n_trials", "int"),
            ("Markers", "n_markers", "int"),
            ("NWB Inspector messages", "nwbinspector_messages", "int"),
        ],
    },
    "stim-events": {
        "title": "Stimulation epochs",
        "short": "Stimulation",
        "about": (
            "stim-events found every stimulation train and its parameters (amplitude, pulse width, frequency, "
            "duration, polarity, waveform) from the sources the recording has, in priority order: per-trial "
            "parameters stored in the file, a parameter table, trigger, monitor or envelope channels, imported "
            "markers, file and folder names, and SDS metadata. One row per train; where a table and a channel "
            "disagree the table wins and the disagreement is listed in its checks. Check the timeline figure against "
            "the protocol before reading the responses."),
        "methods": (
            "Stimulation trains and their parameters were found with stim-events (threshold crossings with "
            "hysteresis on trigger channels, pulses grouped into trains by the inter-pulse gap, per-trial parameters "
            "from the source file and parameter tables) and written as a BIDS-style events table"),
        "headline": [
            ("Trains", "n_stimulations", "int"),
            ("Blocks", "n_blocks", "int"),
            ("Baseline epochs", "n_baseline", "int"),
            ("Parameters varied", "parameters_varied", "text"),
            ("Amplitude from", "amplitude_min", "num"),
            ("Amplitude to", "amplitude_max", "num"),
            ("Unit", "amplitude_unit", "text"),
            ("Frequency from (Hz)", "frequency_hz_min", "num"),
            ("Frequency to (Hz)", "frequency_hz_max", "num"),
            ("Stimulation time", "total_stimulation_s", "dur"),
            ("Sources", "sources", "text"),
            ("Check flags", "n_qc_flags", "int"),
        ],
    },
    "ecg-hrv": {
        "title": "Heart rate and heart rate variability",
        "short": "ECG/HRV",
        "about": (
            "ecg-hrv detected R-peaks in the ECG with NeuroKit2 (with a second detector, WFDB's XQRS, for an "
            "agreement check), labelled ectopic and artifact beats and left them out, and computed heart rate and the "
            "Task Force heart rate variability measures (time domain, frequency domain with the species' bands, "
            "non-linear) over the whole recording and, when stimulation events were linked, before, during and "
            "after each train. HRV over a whole long recording is not comparable with published 5-minute values: "
            "SDNN in particular grows with the length of the recording. A device heart-rate channel, when present, "
            "is compared with the ECG-derived heart rate."),
        "methods": (
            "R-peaks were detected with ecg-hrv (NeuroKit2 ecg_clean and ecg_peaks with species-preset filter band "
            "and refractory period, WFDB XQRS as a second detector), beats labelled with NeuroKit2's signal_fixpeaks, "
            "and HRV computed with NeuroKit2 (hrv_time, hrv_frequency with species bands, hrv_nonlinear)"),
        "headline": [
            ("Beats", "n_beats", "int"),
            ("Mean HR (bpm)", "mean_hr_bpm", "num"),
            ("SDNN (ms)", "sdnn_ms", "num"),
            ("RMSSD (ms)", "rmssd_ms", "num"),
            ("LF/HF", "lf_hf", "num"),
            ("Artifact beats (%)", "pct_artifact", "num"),
            ("Ectopic beats (%)", "pct_ectopic", "num"),
            ("Detector agreement", "detector_agreement", "pct"),
            ("Signal quality", "signal_quality", "num"),
            ("Stimulation windows", "n_stimulation_windows", "int"),
            ("Device HR mean abs. difference (bpm)", "hr_device_mae_bpm", "num"),
        ],
    },
    "bp-resp": {
        "title": "Blood pressure, respiration and baroreflex",
        "short": "BP/resp",
        "about": (
            "bp-resp found each arterial pressure beat (systolic peak, diastolic trough, mean pressure as the "
            "integral over the beat, pulse pressure), each breath (NeuroKit2's respiration processing), the "
            "spontaneous baroreflex sensitivity by the sequence method (Parati et al. 1988) and the spectral alpha "
            "index and transfer-function gain (as compared in the EuroBaVar study), and respiratory sinus arrhythmia "
            "(peak-to-trough and Porges-Bohrer). An uncalibrated pressure channel gives beat timing only: no "
            "pressures in mmHg and no baroreflex slopes. BRS estimates differ between methods; compare like with "
            "like."),
        "methods": (
            "Arterial pressure beats, respiration and spontaneous baroreflex sensitivity were computed with bp-resp "
            "(pressure beats by slope-sum onset detection, mean pressure as the beat integral, NeuroKit2 rsp_process, "
            "sequence method with lags of 0-2 beats and r >= 0.8, spectral alpha and transfer-function gain with "
            "coherence >= 0.5, NeuroKit2 hrv_rsa)"),
        "headline": [
            ("Calibrated", "calibrated", "bool"),
            ("Pressure beats", "bp_beats", "int"),
            ("SBP (mmHg)", "sbp_mmhg", "num"),
            ("DBP (mmHg)", "dbp_mmhg", "num"),
            ("MAP (mmHg)", "map_mmhg", "num"),
            ("Pulse pressure (mmHg)", "pp_mmhg", "num"),
            ("Pulse rate (bpm)", "pulse_rate_bpm", "num"),
            ("Artifact beats (%)", "bp_pct_artifact", "num"),
            ("Breathing rate (/min)", "resp_rate_bpm", "num"),
            ("BRS sequence (ms/mmHg)", "brs_sequence_all", "num"),
            ("Sequences", "brs_n_sequences", "int"),
            ("BRS alpha LF (ms/mmHg)", "brs_alpha_lf", "num"),
            ("BRS alpha HF (ms/mmHg)", "brs_alpha_hf", "num"),
            ("BRS transfer LF (ms/mmHg)", "brs_transfer_lf", "num"),
            ("RSA peak-to-trough (ms)", "rsa_p2t_ms", "num"),
            ("RSA Porges-Bohrer (ln ms²)", "rsa_porges_bohrer", "num"),
            ("RR intervals from", "rr_source", "text"),
        ],
    },
    "stim-dose-response": {
        "title": "Responses to stimulation and dose-response",
        "short": "Dose-response",
        "about": (
            "stim-dose-response compared every physiological series it was given (heart rate, RR interval, "
            "pressures, breathing) before, during and after each stimulation train, left out trains whose windows "
            "overlap another train or have too few valid samples, and fitted the response against the parameter "
            "that varies (Hill or Boltzmann sigmoid, linear, or none, chosen by AIC with at least four levels): "
            "threshold, EC50, maximum. Where heart-rate responses change sign across amplitude at one frequency it "
            "gives the amplitude of the crossing (the neural fulcrum of Ardell et al. 2017, whose original "
            "definition is for chronic, duty-cycled vagus nerve stimulation in conscious animals). Thresholds and "
            "EC50s describe these recordings under these conditions (anaesthesia, electrode, species); they are not "
            "dosing recommendations."),
        "methods": (
            "Responses to each train were computed with stim-dose-response (baseline, during and after means, peak "
            "change, recovery), and dose-response curves fitted with SciPy curve_fit (Hill, Boltzmann, linear, none; "
            "AIC model choice; bootstrap confidence intervals)"),
        "headline": [
            ("Subject", "subject", "text"),
            ("Trains", "n_trains", "int"),
            ("Trains used", "n_trains_included", "int"),
            ("Series", "variables", "text"),
        ],
        # Plus every max_abs_delta_<variable> key, labelled with VARIABLES (model.headline).
        "dynamic_prefix": ("max_abs_delta_", "Largest change: {}"),
    },
}

# The shared series variables (conventions.md, series.csv), as a physiologist reads them.
VARIABLES = {
    "hr_bpm": "heart rate (ECG), bpm", "rr_ms": "RR interval, ms", "hr_device_bpm": "heart rate (device), bpm",
    "sbp_mmhg": "systolic pressure, mmHg", "dbp_mmhg": "diastolic pressure, mmHg", "map_mmhg": "mean pressure, mmHg",
    "pp_mmhg": "pulse pressure, mmHg", "resp_rate_bpm": "breathing rate, /min", "resp_amp": "breath amplitude",
}
VARIABLE_ORDER = list(VARIABLES)

# One row per recording across the steps: what a physiologist looks at first. (label, app, key, kind)
GLANCE = [
    ("Channels flagged", "physio-import", "n_channels_flagged", "int"),
    ("Trains", "stim-events", "n_stimulations", "int"),
    ("Mean HR (bpm)", "ecg-hrv", "mean_hr_bpm", "num"),
    ("SDNN (ms)", "ecg-hrv", "sdnn_ms", "num"),
    ("RMSSD (ms)", "ecg-hrv", "rmssd_ms", "num"),
    ("MAP (mmHg)", "bp-resp", "map_mmhg", "num"),
    ("BRS sequence (ms/mmHg)", "bp-resp", "brs_sequence_all", "num"),
    ("Breathing rate (/min)", "bp-resp", "resp_rate_bpm", "num"),
    ("Trains used", "stim-dose-response", "n_trains_included", "int"),
]

# ----------------------------------------------------------------------------- reference values
# Published values shown next to the resting numbers, for human recordings only (no comparable
# published ranges are built in for other species). Every number is copied from the cited paper:
#  - Shaffer & Ginsberg 2017, Table 6 ("Nunan et al. (17) short-term norms"; read in the open-access
#    full text, PMC5624990, 2026-11-13): healthy adults, short-term (about 5 min) recordings,
#    the range column. Nunan et al. 2010 is the systematic review the table reproduces.
#  - Kardos et al. 2001, abstract (PubMed 11244017): lnBRS = 3.24 - 0.03 x age, spontaneous
#    sequence method, 10 min Finapres BP + ECG, 1134 healthy volunteers aged 18-60.
NUNAN = ["10.3389/fpubh.2017.00258", "10.1111/j.1540-8159.2010.02841.x"]
KARDOS = ["10.1161/01.HYP.37.3.911"]
REFERENCE_VALUES = [
    {"app": "ecg-hrv", "key": "mean_hr_bpm", "species": "human", "text": "52–76 bpm",
     "note": "from the mean NN interval, 785–1,160 ms; heart rate = 60,000 / NN",
     "population": "healthy adults, short-term (≈5 min) recordings; range across 30 studies", "dois": NUNAN},
    {"app": "ecg-hrv", "key": "sdnn_ms", "species": "human", "text": "32–93 ms", "note": "mean (SD) 50 (16) ms",
     "population": "healthy adults, short-term (≈5 min) recordings; range across 27 studies", "dois": NUNAN},
    {"app": "ecg-hrv", "key": "rmssd_ms", "species": "human", "text": "19–75 ms", "note": "mean (SD) 42 (15) ms",
     "population": "healthy adults, short-term (≈5 min) recordings; range across 15 studies", "dois": NUNAN},
    {"app": "ecg-hrv", "key": "lf_hf", "species": "human", "text": "1.1–11.6", "note": "mean (SD) 2.8 (2.6)",
     "population": "healthy adults, short-term (≈5 min) recordings; range across 25 studies", "dois": NUNAN},
    {"app": "bp-resp", "key": "brs_sequence_all", "species": "human",
     "text": "≈14.0 (age 20), 7.7 (age 40), 4.2 ms/mmHg (age 60)",
     "note": "expected value from ln BRS = 3.24 − 0.03 × age (r² = 0.23: wide spread around it)",
     "population": "1134 healthy volunteers aged 18–60, sequence method, 10 min Finapres BP and ECG", "dois": KARDOS},
]
REFERENCE_CAVEAT = (
    "Published values for healthy adults, shown for orientation only. They come from short (about 5-minute), mostly "
    "supine recordings; whole-recording values from long recordings are not comparable (SDNN grows with recording "
    "length), and the values differ with age, posture, breathing, medication and method. There are no comparable "
    "published values built in for other species: compare animal recordings with your own controls. A value outside "
    "a range is not a clinical finding.")

# ----------------------------------------------------------------------------- datasets
# Demo datasets: their licence (as conventions.md, the data README and the landing pages give it)
# and the works their authors ask to be cited with them. Who made them is read from the bundled
# citation table (the DataCite record), never typed here.
PHYSIONET = "10.1161/01.CIR.101.23.e215"
DATASETS = {
    "10.26275/dm5l-tspb": {"licence": "CC BY 4.0", "with": []},
    "10.26275/5cwo-mkpz": {"licence": "CC BY 4.0", "with": []},
    "10.26275/nung-b9bm": {"licence": "CC BY 4.0", "with": []},
    "10.13026/c2rg61": {"licence": "ODC-By 1.0", "with": ["10.1152/ajpregu.1996.271.4.R1078", PHYSIONET]},
    "10.13026/2hsy-t491": {"licence": "ODbL 1.0", "with": ["10.1038/s41597-022-01202-y", PHYSIONET]},
}
# Source paths (physio-import's provenance inputs and recording sources) that identify a demo
# dataset when DATASET_DOIS does not name it: the staged folder names of workflow-physiology and
# the datasets' own file names.
DATASET_PATHS = [
    (r"(^|/)discover-349/", "10.26275/dm5l-tspb"),
    (r"(^|/)discover-655/", "10.26275/5cwo-mkpz"),
    (r"(^|/)discover-406/", "10.26275/nung-b9bm"),
    (r"(^|/)fantasia/|(^|/)f[12][oy]\d\d(\.(hea|dat|ecg))?$", "10.13026/c2rg61"),
    (r"(^|/)autonomic-aging/", "10.13026/2hsy-t491"),
]
