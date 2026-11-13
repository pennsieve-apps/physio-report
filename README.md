# physio-report

This app writes the report at the end of the cardiovascular and autonomic physiology workflows. **The analyses in
it are other people's methods, packaged as Pennsieve apps; the report credits them**: each step's section names
what the step does, and the References list the works each step cites, among them NeuroKit2 (Dominique Makowski
and colleagues), WFDB for Python (MIT Laboratory for Computational Physiology), Neo (the NeuralEnsemble
community), PyNWB (the Neurodata Without Borders project), the baroreflex sequence method of Parati and colleagues
and the neural fulcrum of Ardell and colleagues, with full author lists from the apps' CITATION.cff files,
verified against Crossref, DataCite and PubMed. The published reference values next to the resting numbers are
those collected by Fred Shaffer and J. P. Ginsberg (2017, from the systematic review of David Nunan, Gavin
Sandercock and David Brodie, 2010) and the age regression of Attila Kardos and colleagues (2001). The report
itself is rendered with [WeasyPrint](https://github.com/Kozea/WeasyPrint) (created by Simon Sapin, maintained by
CourtBouillon), [Jinja](https://github.com/pallets/jinja) (Pallets) and
[Pillow](https://github.com/python-pillow/Pillow) (Jeffrey A. Clark and contributors). **Pennsieve built the
report; it did not develop the methods it reports on.** The demo reports were made from Pennsieve Discover datasets
349 (Oliver Armitage and colleagues), 655 (Shane A Bender and colleagues) and 406 (M Khawar Ali and colleagues), the
PhysioNet Fantasia Database (Nikhil Iyengar and colleagues) and the PhysioNet Autonomic Aging dataset (Andy
Schumann and Karl-Jürgen Bär); see [Citations](#citations).

The last step of both physiology workflows:

- **Cardiovascular Response to Nerve Stimulation:** `physio-import → stim-events → {ecg-hrv, bp-resp} → stim-dose-response → physio-report`
- **Heart Rate Variability and Baroreflex:** `physio-import → {ecg-hrv, bp-resp} → physio-report`

**For a physiologist.** Link the outputs of the steps you ran and you get one report you can read, keep with the
data and send to a colleague: an HTML page that opens offline and the same report as a PDF. It opens with a box
saying what everything in it is: **research output, not a clinical finding**, and gathers every step's
**licence notice** at the top. Then:

1. **Recordings**: subject, species, duration (and the time covered by samples when the recording has gaps),
   the signals physio-import found (ECG, BP, respiration, stimulation, device heart rate, nerve, ...), which steps
   have results for each recording, and **which steps skipped it and why** (a recording without blood pressure is
   skipped by bp-resp, not failed). An **at-a-glance** table has one headline number per step per recording.
2. **Key results**:
   - heart rate and HRV over each whole recording (mean HR, SDNN, RMSSD, LF/HF, beats, artifact share);
   - blood pressure (SBP, DBP, MAP, calibrated or not), spontaneous baroreflex sensitivity (sequence, alpha LF,
     transfer LF), RSA and breathing rate;
   - for human recordings, the **published reference values** for healthy adults next to them (below), with
     the caveat that they come from 5-minute supine recordings; none are built in for other species;
   - per subject the **dose-response fits** (parameter varied, the others held fixed, model, threshold and its
     criterion, EC50 with its confidence interval, maximum change, r², levels, the step's note) and the **neural
     fulcrum**, with stim-dose-response's caveat about what the fulcrum means in acute preparations. A threshold
     that is only an upper bound (`threshold_bound=upper`: the next lower level was not tested or not analysed)
     is shown as "≤"; a fit blanked because the response changes sign says so; groups with one tested level are
     counted, not listed (they stay in `dose_response.csv`);
   - bp-resp's pressure checks (level steps, drift, channel status, channel choice) next to the pressures.
3. One section per linked step, in workflow order, each starting with the step's own **method caveat** (its
   summary.json `notice`) and licence notice: physio-import's signal quality (flagged channels with the reason,
   uncalibrated channels, NWB Inspector messages and the CRITICAL ones kept for missing subject metadata, input
   files that were not recordings), bp-resp's checks to read before its numbers (pressure level steps and
   drift, channel status, which channel was chosen when there were several), stim-events' trains and
   parameters, ecg-hrv, bp-resp and stim-dose-response; then every figure the step chose, in its order, with
   **the caption the step wrote** (each says what to look at), its warnings, the recordings it skipped and why,
   the tables it wrote and its parameters.
4. Methods (a sentence per step you can adapt), software versions, run times and memory, References,
   Acknowledgements (upstream software and datasets) and **how to cite**: the original works for each step,
   the datasets, then the apps with their versions.

**For a data scientist.** The report reads only the shared contract of `workflow-physiology/docs/conventions.md`:
each app's top folder `<app>/` (or `<app>/<LABEL>/`) with `provenance.json` and `summary.json` (`recordings`
keyed by recording id, `figures` `[{path, caption}]`, `tables`, `warnings`, optional `notice`; stim-dose-response's
`subjects` and `fits.csv`/`fulcrum.csv`; bp-resp's `qc.csv` checks), and physio-import's `recordings.csv` and
`channels.csv` (the copies in its `qc` port, or its `physio` port when merged in; the NWB files are never opened). Everything is found by file name and content,
recursively, following symlinks: ports in their own folders, everything merged at the input root, or any mix.
Figure and table paths are taken relative to the app's top folder (paths relative to the port folder are accepted
too); absolute paths and `..` are never followed. The known apps get curated tables (columns whose keys no
recording has are dropped, so a renamed key loses a column, not the section); any other app is rendered
generically from its numeric per-recording values. Numbers are copied, never recomputed: integers exactly, other
numbers to four significant digits, 0-1 fractions as percentages. DOIs in each step's `provenance.citations` (and
in a `licence_notice`) are resolved from a citation table bundled at build time (`processor/references.json`,
written by `scripts/build_citations.py` from the sibling apps' verified CITATION.cff files and, for any other DOI
the steps cite, from Crossref/DataCite/PubMed); a DOI not in it is listed DOI-only, never filled in at run time
(the app has no network). A step may give its own reference values as summary.json `reference_ranges`
(`[{key, species, low, high, unit | text, population, citations}]`); they replace the built-in ones for that
measure and species. Where a step's output departs from the contract (a figure listed but missing or unreadable,
no caption, no summary.json, a table path outside the step's folder) the report still renders what it can and lists the problem under "Notes on the inputs".

## Ports

| Port | Direction | Content |
|---|---|---|
| `qc` | in (optional) | physio-import's `qc` output: `physio-import/summary.json`, `recordings.csv` and `channels.csv` (copies of the physio port's), `qc.csv`, `nwbinspector.csv`, overview figures, `provenance.json` (with `skipped_files`). |
| `events` | in (optional) | stim-events: `stim-events/summary.json`, `events.tsv`, `stim_summary.csv`, `qc.csv`, timeline figures. |
| `hrv` | in (optional) | ecg-hrv: `ecg-hrv/summary.json`, `hrv.csv`, `beats.csv`, `series.csv`, `qc.csv`, `features.csv`, figures. |
| `bp` | in (optional) | bp-resp: `bp-resp/summary.json`, `bp_beats.csv`, `breaths.csv`, `brs.csv`, `rsa.csv`, `series.csv`, `qc.csv`, figures. |
| `responses` | in (optional) | stim-dose-response: `stim-dose-response/summary.json` (with `subjects`), `responses.csv`, `fits.csv`, `surface.csv`, `fulcrum.csv`, figures. |
| `report` | out | `physio-report/`: `report.html`, `report.pdf`, `figures/<step>/*.png`, `tables/`, `summary.json`, `provenance.json`. |

All inputs are optional and use `placement: subfolder`; at least one step must be linked. The same app ends both
workflows: the workflow is recognised from the linked steps (stim-events or stim-dose-response: the stimulation
workflow, else the HRV workflow), and the steps of that workflow that are not linked are named at the top. An app
linked twice under different `LABEL`s gets two sections and separate figure and table folders; the key results use
the first.

## Parameters

| Name | Default | What it does |
|---|---|---|
| `REPORT_TITLE` | empty | Title. Empty: "Physiology report: <workflow>". |
| `MAX_FIGURES` | `40` | Figures shown per step in the page and the PDF, in the step's order. The rest are copied next to the page and linked from it. `0` shows none. |
| `DATASET_DOIS` | empty | DOIs of the datasets analysed (comma-separated), credited and cited. The demo datasets are also recognised from physio-import's source paths; Fantasia and Autonomic Aging are cited with their papers and PhysioNet (Goldberger et al. 2000), as PhysioNet asks. |
| `WRITE_PDF` | `true` | Also write `report.pdf`. |

### Reference values (built in, human recordings only)

| Measure | Value | Population | Source |
|---|---|---|---|
| Mean HR | 52–76 bpm (mean NN 785–1,160 ms, converted as 60,000 / NN) | healthy adults, short-term (≈5 min) recordings, range across 30 studies | Shaffer & Ginsberg 2017, Table 6, from Nunan et al. 2010 |
| SDNN | 32–93 ms (mean 50, SD 16) | same, 27 studies | same |
| RMSSD | 19–75 ms (mean 42, SD 15) | same, 15 studies | same |
| LF/HF | 1.1–11.6 (mean 2.8, SD 2.6) | same, 25 studies | same |
| BRS, sequence method | ln BRS = 3.24 − 0.03 × age: ≈14.0, 7.7 and 4.2 ms/mmHg at 20, 40 and 60 years (r² = 0.23) | 1134 healthy volunteers aged 18–60, 10 min Finapres BP and ECG | Kardos et al. 2001, abstract |

The numbers were read in the open-access full text of Shaffer & Ginsberg (PMC5624990) and the PubMed abstract of
Kardos et al. (doi:10.1161/01.HYP.37.3.911, PMID 11244017) on 2026-11-13. They are shown for orientation, never used to flag a recording:
whole-recording values from long recordings are not comparable with 5-minute values (SDNN grows with length), and
there are no comparable published values built in for pig, dog, rabbit, rat or mouse.

## Outputs

`OUTPUT_DIR/physio-report/` (the one output port, `report`):

- `report.html`: inline CSS, no scripts, nothing loaded from elsewhere (DOIs and repositories are plain links);
  figures are PNG files in `figures/<step>/` next to it, so keep the folder together. Long warning lists show the
  first eight and fold the rest.
- `report.pdf`: the same content on A4 (WeasyPrint, DejaVu fonts), everything unfolded, figures converted to JPEG
  at most 1200 px wide; every page footer repeats "research output, not a clinical finding".
- `tables/`:
  - `recordings.csv`: `recording_id, subject, species, duration, channel_types, steps_with_results, not_analysed`;
  - `overview.csv`: the at-a-glance table as numbers (`recording_id`, `<app>:<key>` ...);
  - `headline.csv`: every per-recording value of every step's summary.json, long format
    (`recording_id, step, metric, value`; lists `|`-joined, nested values as `metric.key`);
  - `qc_summary.csv`: the signal-quality table;
  - `resting_hrv.csv`, `resting_bp.csv`: the key-result tables as numbers (`recording_id, species, <keys>`);
  - `reference_values.csv`: the reference values shown (`step, metric, species, reference, note, population, dois`);
  - `dose_response.csv`, `fulcrum.csv`: stim-dose-response's fits and fulcrum rows as shown (all columns);
  - `<step>/...`: a copy of every CSV/TSV each step wrote, keeping its layout (and `physio-import/physio/`
    `recordings.csv`, `channels.csv`, `events.tsv` when the physio port is merged in).
- `summary.json` (recordings with the steps that cover and skipped them, steps not linked, counts, warnings) and
  `provenance.json` (conventions.md keys).

Exit codes: `0` ok; `1` nothing to report on (no step output linked), or the PDF could not be written (the page,
tables and JSON are written first, and the error is logged and listed in summary.json); `2` bad parameters.

## Runtime

`cpu: 1024`, `memory: 2048` MiB, `computeTypes: [standard]`, `timeoutSeconds: 900`: within the Lambda limits, so the
platform can run it as a Lambda step; it is Lambda-safe (writes only `OUTPUT_DIR` and `TMPDIR`, makes
`HOME`/`TMPDIR` when missing, keeps the fontconfig cache in the image's read-only `/var/cache/fontconfig` and any
run-time cache under `$TMPDIR`, runs as any uid). Measured in the image (linux/amd64 under emulation on an M-series
Mac), read-only root, uid 65534, `--memory 2g`, `--network none`, with `scripts/run_demo.sh`:

| Input | Steps linked | Recordings | Figures shown | Wall time | Peak RSS | cgroup memory.peak | PDF |
|---|---|---|---|---|---|---|---|
| Discover 349 (stimulation workflow) | all five | 1 | 8 | 2.0 s | 130 MB | 122 MB | 0.7 MB, 17 pages |
| Discover 655 (stimulation workflow) | all five | 3 | 16 | 2.4 s | 126 MB | 129 MB | 1.3 MB, 18 pages |
| Autonomic Aging (HRV workflow) | qc, hrv, bp | 3 | 15 | 2.2 s | 126 MB | 129 MB | 1.5 MB, 17 pages |
| Fantasia (HRV workflow) | qc, hrv, bp | 6 | 28 | 2.9 s | 145 MB | 190 MB | 3.1 MB, 28 pages |
| Discover 406 (HRV workflow) | qc, hrv, bp | 20 | 60 | 4.1 s | 135 MB | 159 MB | 4.6 MB, 37 pages |
| Synthetic fixture | all five | 3 | 16 | 1.7 s | 110 MB | 102 MB | 0.3 MB, 18 pages |

Memory grows with the largest figure and the PDF's layout, not with the recordings: the report never opens an NWB
file. Wall time is the step's own (`provenance.json`); the container adds about half a second. Image: 297 MB, 71 MB
compressed. Output size is dominated by the copied figures and tables (Fantasia: 46 MB,
most of it ecg-hrv's beat-by-beat `beats.csv` and `series.csv` of six 2-hour recordings).

## Validation

The report has no method of its own to validate; it was checked on the real outputs of the upstream apps for the
five demos (the three below, plus Discover 655 and 406), against the apps' own summary.json, and on the synthetic
fixture (`tests/`, 27 tests, the PDF test in the image):

- **Discover 349** (pig, 20 trains over 50–2500 µA x 2–30 Hz): one recording; physio-import, stim-events (20
  trains, amplitude and frequency varied), ecg-hrv (mean HR 71.25 bpm, SDNN 31.92 ms, device HR mean absolute
  difference 0.83 bpm), bp-resp (skipped: no blood pressure or respiration channel, shown as not analysed, not as a
  failure) and stim-dose-response (27 fits, 20 with a threshold, 8 of them upper bounds, none with an EC50, 2 blanked because the response changes sign; neural fulcrum at 1,751 µA
  for the ECG heart rate and 1,714 µA for the device heart rate at 30 Hz). No reference values: pig.
- **Autonomic Aging** (human, calibrated NIBP): three recordings with HRV, pressures and BRS next to the
  reference values, and bp-resp's level-step and drift checks next to the pressures; physio-import's three
  non-recording files (licence, checksums, subject table) are listed as input files not read.
- **Fantasia** (human, 2 h each): six recordings with HRV and RSA; the four f2 records' BP is uncalibrated, so
  bp-resp's notice is shown and the pressure and BRS columns are left out.

Every figure listed by the steps exists and has a caption in the `{path, caption}` shape of the contract; every
DOI the steps cite is in the bundled table (no DOI-only references).

## Limitations

- It reports what the steps wrote. It does not check that a number is right, re-run a statistic or compare
  recordings; a wrong caption or number upstream is a wrong caption or number in the report.
- Reference values are built in for human adults only, from short supine recordings; they are not comparable
  with whole-recording values from long recordings, with children, with anaesthetised preparations or with
  other species, and the report never flags a recording against them.
- With an older physio-import whose `qc` port has no `recordings.csv`/`channels.csv` copies, the recordings table
  takes durations, channel types and species from its summary, qc.csv and the steps' provenance; age, sex and
  which channels are uncalibrated then come only from the steps' notices.
- The key results use the first `LABEL` of an app that is linked more than once.
- Datasets are credited only when given in `DATASET_DOIS` or recognised from physio-import's source paths
  (the demo datasets).
- A cited DOI that is not in the bundled table is shown DOI-only; rebuild the table (`make citations`) after a
  sibling app adds a citation.
- Wide tables in the PDF use a small font; the HTML page scrolls them instead.

## Development

```
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
make test        # pytest on the synthetic fixture (tests/make_fixture.py); the PDF test needs Pango
make run         # the image over the fixture, read-only, uid 65534, no network
make demo DEMO=d349
make citations validate verify
```

`tests/make_fixture.py` writes every app's outputs for three recordings (a resting human recording with ECG,
calibrated BP and respiration; a human ECG-only recording that bp-resp skips; a pig recording with a 4 x 3
amplitude x frequency grid of stimulation trains, uncalibrated BP and a device heart rate), in the `linked` (one
folder per port) and `flat` (merged, with physio-import's `physio` port index) layouts; it needs only the Python
standard library (it is also the release review's input generator). The tests cover both layouts, symlinked
ports, subsets of steps, only the `qc` port, a step without `qc`, dose-response numbers from summary.json when the
tables are missing, step-given reference values, missing and corrupt figures, a step with zero recordings, the
same app under two LABELs, unsafe figure paths, invalid JSON, a previous report linked back in, licence citations
given as one string, and bad parameters.

## Licences

Apache-2.0 (this app). Bundled components and their licences are in [THIRD_PARTY.md](THIRD_PARTY.md): Jinja and
MarkupSafe (BSD-3-Clause), WeasyPrint and its CourtBouillon libraries (BSD-3-Clause), Pillow (MIT-CMU), fontTools
(MIT), Pyphen (code only, used under its MPL 1.1 option; its dictionaries are removed), and the Debian
Pango/HarfBuzz/fontconfig/FreeType/GLib libraries and DejaVu fonts. The figures, numbers and tables in a report
belong to the steps that made them and to the data's licence (Discover 349, 655 and 406: CC BY 4.0; Fantasia:
ODC-By 1.0; Autonomic Aging: ODbL 1.0).

## Citations

The report adds no method of its own; cite the works of each step, which the report lists under "How to cite".
Please cite these works if you use this app's reference values or its demo output. Verified on Crossref/DataCite
and PubMed; full author lists in CITATION.cff.

- Shaffer F, Ginsberg JP. An Overview of Heart Rate Variability Metrics and Norms. Frontiers in Public Health
  2017;5:258. doi:[10.3389/fpubh.2017.00258](https://doi.org/10.3389/fpubh.2017.00258), PMID 29034226
- Nunan D, Sandercock GRH, Brodie DA. A Quantitative Systematic Review of Normal Values for Short-Term Heart Rate
  Variability in Healthy Adults. Pacing and Clinical Electrophysiology 2010;33(11):1407-1417.
  doi:[10.1111/j.1540-8159.2010.02841.x](https://doi.org/10.1111/j.1540-8159.2010.02841.x), PMID 20663071
- Kardos A, Watterich G, de Menezes R, Csanády M, Casadei B, Rudas L. Determinants of Spontaneous Baroreflex
  Sensitivity in a Healthy Working Population. Hypertension 2001;37(3):911-916.
  doi:[10.1161/01.HYP.37.3.911](https://doi.org/10.1161/01.HYP.37.3.911), PMID 11244017
- Armitage O, Sarkans E, Wernisch L, Fortier-Poisson P, Berthon A, Tessier-Larivière O. Influence of vagus nerve
  stimulation on cardiac activity in pigs. SPARC Portal 2023. doi:[10.26275/dm5l-tspb](https://doi.org/10.26275/dm5l-tspb)
- Bender SA, Green DB, Thakkar VS, Zimmerman HL, Elazab M, Kilgore KL, Vrabec TL. Single-electrode bidirectional
  control of heart rate via vagus nerve modulation in rat model. SPARC Portal 2026.
  doi:[10.26275/5cwo-mkpz](https://doi.org/10.26275/5cwo-mkpz)
- Ali MK, Gong S, Nojkov B, Burnett C, Chen JD. Best parameters of heart rate variability for assessing autonomic
  responses to brief rectal distention in patients with irritable bowel syndrome. SPARC Portal 2024.
  doi:[10.26275/nung-b9bm](https://doi.org/10.26275/nung-b9bm)
- Iyengar N, Peng C-K, Morin R, Goldberger AL, Lipsitz LA. Fantasia Database. PhysioNet 1994.
  doi:[10.13026/C2RG61](https://doi.org/10.13026/C2RG61)
- Iyengar N, Peng CK, Morin R, Goldberger AL, Lipsitz LA. Age-related alterations in the fractal scaling of cardiac
  interbeat interval dynamics. American Journal of Physiology-Regulatory, Integrative and Comparative Physiology
  1996;271(4):R1078-R1084. doi:[10.1152/ajpregu.1996.271.4.R1078](https://doi.org/10.1152/ajpregu.1996.271.4.R1078), PMID 8898003
- Schumann A, Bär K. Autonomic Aging: A dataset to quantify changes of cardiovascular autonomic function during
  healthy aging. PhysioNet 2021. doi:[10.13026/2hsy-t491](https://doi.org/10.13026/2hsy-t491)
- Schumann A, Bär K-J. Autonomic aging – A dataset to quantify changes of cardiovascular autonomic function during
  healthy aging. Scientific Data 2022;9:95. doi:[10.1038/s41597-022-01202-y](https://doi.org/10.1038/s41597-022-01202-y), PMID 35322044
- Goldberger AL, Amaral LAN, Glass L, Hausdorff JM, Ivanov PCh, Mark RG, Mietus JE, Moody GB, Peng C-K, Stanley
  HE. PhysioBank, PhysioToolkit, and PhysioNet. Circulation 2000;101(23):e215-e220.
  doi:[10.1161/01.CIR.101.23.e215](https://doi.org/10.1161/01.CIR.101.23.e215), PMID 10851218
- Software: WeasyPrint (Simon Sapin; CourtBouillon), https://github.com/Kozea/WeasyPrint; Jinja (Pallets),
  https://github.com/pallets/jinja; Pillow (Jeffrey A. Clark and contributors),
  https://github.com/python-pillow/Pillow.

## Acknowledgements

The methods in every report are those of the upstream projects each step packages (Neo, WFDB for Python,
pyEDFlib, PyNWB and NWB Inspector, NeuroKit2, SciPy, statsmodels; see each app's README) and of the authors of the
methods they implement. The demo data come from Pennsieve Discover (datasets 349, 655 and 406) and PhysioNet (Fantasia,
Autonomic Aging); PhysioNet asks that Goldberger et al. 2000 be cited with its databases.
