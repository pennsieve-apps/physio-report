"""The report on the synthetic fixture: every layout, every subset of steps, and broken inputs."""
from __future__ import annotations

import csv
import html
import json
import os
import re
import shutil
from pathlib import Path

import pytest

from processor import main as M
from tests import make_fixture as F

PARAMS = {"REPORT_TITLE": "", "MAX_FIGURES": 40, "DATASET_DOIS": "", "WRITE_PDF": False}
ALL = ["physio-import"] + list(F.APPS)


def weasyprint_works() -> bool:
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 - missing Pango on a dev machine
        return False


def run(inp: Path, out: Path, **params) -> tuple[int, str, Path]:
    rc = M.run(inp, out, {**PARAMS, **params})
    rep = out / "physio-report"
    page = (rep / "report.html").read_text(encoding="utf-8") if (rep / "report.html").exists() else ""
    return rc, page, rep


def text(page: str) -> str:
    t = re.sub(r"<style.*?</style>", "", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


@pytest.fixture()
def linked(tmp_path: Path) -> Path:
    return F.write(tmp_path / "in", "linked")


def test_full_linked_report(linked: Path, tmp_path: Path) -> None:
    rc, page, rep = run(linked, tmp_path / "out")
    assert rc == 0
    t = text(page)
    assert "Physiology report: Cardiovascular Response to Nerve Stimulation" in t
    for rid in F.IDS:
        assert rid in t
    # Sections in workflow order, after Recordings and Key results.
    order = [t.index(x) for x in ("1. Recordings", "2. Key results", "3. Import and signal quality",
                                  "4. Stimulation epochs", "5. Heart rate and heart rate variability",
                                  "6. Blood pressure, respiration and baroreflex",
                                  "7. Responses to stimulation and dose-response", "References The works each step",
                                  "How to cite The methods")]
    assert order == sorted(order)
    # Recordings: species, signals, skipped steps with the reason (missing signals are not failures).
    assert "ECG, BP, stimulation, device HR" in t
    assert "BP/resp: skipped: no blood pressure or respiration channel" in t
    assert "Stimulation: skipped: no stimulation found" in t
    # A skipped input file (physio-import's skipped_files) is not a recording.
    assert "input file not read as a recording: no time column" in t and "lab-export/notes.txt" in t
    assert not re.search(r"<td>lab-export/notes.txt</td>", page)
    # QC from physio-import: the flagged channel and why.
    assert "1 with at least one flagged channel" in t and "bp saturated (3.1% of samples" in t
    # Resting HRV with the human reference values, none for the pig.
    assert "Heart rate and heart rate variability (whole recording)" in t
    assert "32–93 ms" in t and "19–75 ms" in t and "52–76 bpm" in t
    assert "No published reference values are built in for pig recordings" in t
    # BP and BRS with the Kardos reference; uncalibrated pig BP has no pressures.
    assert "BRS sequence (ms/mmHg)" in t and "11.3" in t and "3.24 − 0.03 × age" in t
    # Dose-response: threshold, EC50 with CI, fulcrum, the held-fixed parameter as words.
    assert "812.4 (640.2–1,021)" in t and "frequency 30 Hz" in t and "Amplitude at the fulcrum (uA)" in t
    assert "612.5" in t and "none reached" in t
    assert "Threshold criterion (from fits.csv): heart rate (ECG), bpm: auto: 5% of baseline" in t
    # Every step's notice box, the licence notice at the top and in its section, the test link only.
    assert page.count("<h4>Read this first</h4>") == 4
    assert page.count("Test terms: example parameter tables") == 2
    assert '<a href="https://example.org/terms">' in page and 'href="javascript' not in page
    # Figures in order with the steps' captions (16 figures, one path relative to the port folder).
    assert len(re.findall(r"<img ", page)) == 16
    assert "Figure 16." in t and "Subject p1: mean change in heart rate per amplitude x frequency" in t
    # References: step citations, reference-value sources, nothing DOI-only.
    for title in ("NeuroKit2: A Python toolbox", "Defining the neural fulcrum", "An Overview of Heart Rate Variability",
                  "Determinants of Spontaneous Baroreflex Sensitivity", "Quantitative Systematic Review of Normal Values"):
        assert title in t, title
    assert "DOI only" not in t and "Nunan et al. 2010" in t
    assert "doi:10.1109/TAC.1974.1100705" in t  # the citing step's casing, not the record's lowercase
    assert "parameter groups (rows of fits.csv" in t and "5 parameter groups" in t and "2 with a fitted model" in t
    # Acknowledgements name the tool behind each cited software paper.
    ack = t.split("Acknowledgements These analyses")[1].split("How to cite")[0]
    assert "ecg-hrv : NeuroKit2 (Makowski et al. 2021 [" in ack and "Neo (Garcia et al. 2014 [" in ack
    assert "Heart rate and heart rate variability : NeuroKit2, WFDB for Python." in t
    assert "Waveform Database Software Package" not in ack and ack.count("WFDB for Python") == 3
    assert "Research output, not a clinical finding" in t
    assert "Notes on the inputs" not in t  # the fixture follows the contract
    # Recordings and channels from the qc port's copies: age, uncalibrated channels, CRITICAL kept.
    assert "as physio-import listed them" in t and "P3M" in t and "Uncalibrated" in t
    assert "CRITICAL kept (missing subject metadata): check_subject_age" in t
    # Dose table: an upper-bound threshold, a blanked fit, the one-level group left out.
    assert "≤ 1,000" in t and "fit blanked: the response changes sign" in t
    assert "1 group with fewer than two levels of the parameter analysed" in t
    # bp-resp's checks next to the pressures and in its section.
    assert "1 level step; SBP drift +34 mmHg" in t and "Checks to read before the numbers" in t
    assert "ecg channel: ecg" in t


def test_tables_and_json(linked: Path, tmp_path: Path) -> None:
    rc, _, rep = run(linked, tmp_path / "out")
    assert rc == 0
    tab = rep / "tables"
    for name in ("recordings.csv", "overview.csv", "headline.csv", "qc_summary.csv", "resting_hrv.csv",
                 "resting_bp.csv", "reference_values.csv", "dose_response.csv", "fulcrum.csv",
                 "ecg-hrv/hrv.csv", "bp-resp/brs.csv", "stim-dose-response/fits.csv", "stim-events/events.tsv",
                 "physio-import/qc.csv"):
        assert (tab / name).is_file(), name
    with open(tab / "dose_response.csv") as fh:
        rows = list(csv.DictReader(fh))
    assert any(r["ec50"] == "812.4" for r in rows)
    with open(tab / "recordings.csv") as fh:
        recs = {r["recording_id"]: r for r in csv.DictReader(fh)}
    assert recs[F.P1]["species"] == "pig" and recs[F.H2]["channel_types"] == "ecg"
    summ = json.loads((rep / "summary.json").read_text())
    prov = json.loads((rep / "provenance.json").read_text())
    assert summ["app"] == prov["app"] == "physio-report"
    assert set(prov) >= {"app", "version", "variant", "tools", "parameters", "inputs", "started", "finished",
                         "wall_seconds", "peak_rss_mb", "threads", "recordings", "citations", "licence_notice"}
    assert summ["steps_not_linked"] == [] and summ["n_unknown_dois"] == 0
    with open(tab / "dose_response.csv") as fh:
        assert len(list(csv.DictReader(fh))) == 5  # every fit, the one-level group included


def test_flat_layout_with_physio_port(tmp_path: Path) -> None:
    """Everything merged at the root, physio-import's physio port included: its recordings.csv and
    channels.csv feed the recordings table and the uncalibrated column."""
    flat = F.write(tmp_path / "in", "flat")
    rc, page, rep = run(flat, tmp_path / "out")
    assert rc == 0
    t = text(page)
    assert "as physio-import listed them" in t and "7. Responses to stimulation" in t
    assert "Uncalibrated" in t and "ecg, bp" in t  # the pig's uncalibrated ECG and BP, from channels.csv
    assert "P3M" in t  # age from recordings.csv
    assert len(re.findall(r"<img ", page)) == 16
    assert (rep / "tables" / "physio-import" / "physio" / "channels.csv").is_file()


def test_symlinked_ports(tmp_path: Path) -> None:
    real = F.write(tmp_path / "real", "linked")
    inp = tmp_path / "in"
    inp.mkdir()
    for p in real.iterdir():
        os.symlink(p, inp / p.name)
    rc, page, _ = run(inp, tmp_path / "out")
    assert rc == 0 and "7. Responses to stimulation and dose-response" in text(page)


@pytest.mark.parametrize("apps", [["ecg-hrv"], ["ecg-hrv", "bp-resp"], ["stim-events"], ["stim-dose-response"],
                                  ["bp-resp"]])
def test_any_subset_of_steps(tmp_path: Path, apps: list[str]) -> None:
    inp = F.write(tmp_path / "in", "linked", apps=apps)
    rc, page, _ = run(inp, tmp_path / "out")
    assert rc == 0
    t = text(page)
    assert "Signal quality per recording" in t
    from processor.apps import APPS
    for app in F.APPS:
        present = re.search(r"\d+\. " + re.escape(APPS[app]["title"]), t) is not None
        assert present == (app in apps), app


def test_hrv_workflow_names_missing_steps(tmp_path: Path) -> None:
    inp = F.write(tmp_path / "in", "linked", apps=["ecg-hrv"])
    rc, page, rep = run(inp, tmp_path / "out")
    assert rc == 0
    t = text(page)
    assert "Physiology report: Heart Rate Variability and Baroreflex" in t
    assert "Not linked bp-resp (port bp )" in t
    assert json.loads((rep / "summary.json").read_text())["steps_not_linked"] == ["bp-resp"]
    assert "Thresholds, EC50" not in t


def test_only_qc_port(tmp_path: Path) -> None:
    inp = F.write(tmp_path / "in", "linked", apps=[])
    rc, page, _ = run(inp, tmp_path / "out")
    assert rc == 0
    t = text(page)
    assert "Signal quality per recording" in t and "None of the linked steps has resting heart rate" in t


def test_outside_table_paths_are_noted(linked: Path, tmp_path: Path) -> None:
    p = linked / "qc" / "physio-import" / "summary.json"
    s = json.loads(p.read_text())
    s["tables"].append({"path": "../../physio/events.tsv", "caption": "outside"})
    p.write_text(json.dumps(s))
    rc, page, _ = run(linked, tmp_path / "out")
    assert rc == 0 and "lists tables outside the app's top folder (../../physio/events.tsv)" in text(page)


def test_one_step_without_qc(tmp_path: Path) -> None:
    inp = F.write(tmp_path / "in", "linked", apps=["stim-dose-response"], qc=False)
    rc, page, _ = run(inp, tmp_path / "out")
    assert rc == 0
    t = text(page)
    assert "as the linked steps describe them" in t and F.P1 in t and "812.4" in t
    assert "Signal quality per recording" not in t


def test_assumed_species_is_unknown(linked: Path, tmp_path: Path) -> None:
    """ecg-hrv writes "human" with species_from "default (human)" when it had no species: the report
    shows unknown and gives that recording no reference values."""
    qc = linked / "qc" / "physio-import"
    for name in ("recordings.csv",):
        rows = list(csv.DictReader(open(qc / name)))
        for r in rows:
            r["species"] = ""
        with open(qc / name, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    for port, app in (("qc", "physio-import"), ("hrv", "ecg-hrv"), ("bp", "bp-resp"), ("events", "stim-events"),
                      ("responses", "stim-dose-response")):
        p = linked / port / app / "provenance.json"
        d = json.loads(p.read_text())
        for r in d["recordings"].values():
            r["species"] = "" if app in ("physio-import", "stim-events") else "human"
            if app == "ecg-hrv":
                r["species_from"] = "default (human)"
            elif app == "bp-resp":
                r["species_source"] = "species unknown: human preset used (set SPECIES)"
        if app == "stim-dose-response":
            d["windows"] = {rid: {"species_source": "default (no species in the inputs)"} for rid in d["recordings"]}
        p.write_text(json.dumps(d))
    p = linked / "responses" / "stim-dose-response" / "summary.json"
    d = json.loads(p.read_text())
    for r in d["recordings"].values():
        r["species"] = "human"
    p.write_text(json.dumps(d))
    rc, page, rep = run(linked, tmp_path / "out")
    t = text(page)
    assert rc == 0
    key = t.split("2. Key results")[1].split("3. Import")[0]
    assert f"{F.H1} h01 unknown" in t and f"{F.H1} unknown" in key and f"{F.H1} human" not in key
    assert "32–93 ms" not in t and "Recordings of unknown species get no reference values" in t
    assert not (rep / "tables" / "reference_values.csv").exists()


def test_dose_from_summary_when_tables_missing(linked: Path, tmp_path: Path) -> None:
    for name in ("fits.csv", "fulcrum.csv"):
        (linked / "responses" / "stim-dose-response" / name).unlink()
    rc, page, _ = run(linked, tmp_path / "out")
    assert rc == 0
    t = text(page)
    assert "812.4 (640.2–1,021)" in t and "612.5" in t


def test_step_reference_ranges_win(linked: Path, tmp_path: Path) -> None:
    p = linked / "hrv" / "ecg-hrv" / "summary.json"
    s = json.loads(p.read_text())
    s["reference_ranges"] = [{"key": "rmssd_ms", "species": "pig", "low": 10, "high": 40, "unit": "ms",
                              "population": "anaesthetised pigs (test)", "citations": "10.3389/fphys.2018.01390"},
                             {"key": "sdnn_ms", "species": "human", "text": "20–60 ms (test)"}]
    p.write_text(json.dumps(s))
    rc, page, _ = run(linked, tmp_path / "out")
    t = text(page)
    assert rc == 0 and "10–40 ms" in t and "anaesthetised pigs (test)" in t and "given by ecg-hrv" in t
    assert "20–60 ms (test)" in t and "32–93 ms" not in t


def test_missing_figure_and_corrupt_figure(linked: Path, tmp_path: Path) -> None:
    (linked / "hrv" / "ecg-hrv" / "figures" / f"{F.H1}_hrv.png").unlink()
    (linked / "bp" / "bp-resp" / "figures" / f"{F.H1}_brs.png").write_bytes(b"not a png")
    rc, page, _ = run(linked, tmp_path / "out")
    assert rc == 0
    t = text(page)
    assert "listed in summary.json are missing" in t and "could not be read as an image" in t
    assert "Notes on the inputs" in t


def test_zero_recordings_step(linked: Path, tmp_path: Path) -> None:
    p = linked / "bp" / "bp-resp" / "summary.json"
    s = json.loads(p.read_text())
    s["recordings"], s["figures"] = {}, []
    p.write_text(json.dumps(s))
    rc, page, _ = run(linked, tmp_path / "out")
    assert rc == 0
    assert "This step reported no recordings" in text(page)


def test_label_subfolders(tmp_path: Path) -> None:
    inp = F.write(tmp_path / "in", "linked", apps=["stim-events"])
    F.ecg_hrv(inp / "hrv" / "ecg-hrv" / "neurokit")
    F.ecg_hrv(inp / "hrv" / "ecg-hrv" / "pantompkins")
    rc, page, rep = run(inp, tmp_path / "out")
    assert rc == 0
    t = text(page)
    assert "Heart rate and heart rate variability (neurokit)" in t and "(pantompkins)" in t
    assert (rep / "figures" / "ecg-hrv_neurokit").is_dir() and (rep / "tables" / "ecg-hrv/pantompkins/hrv.csv").is_file()
    assert "linked 2 times" in t


def test_unsafe_paths_and_bad_json(linked: Path, tmp_path: Path) -> None:
    p = linked / "hrv" / "ecg-hrv" / "summary.json"
    s = json.loads(p.read_text())
    s["figures"].append({"path": "../../qc/physio-import/qc.csv", "caption": "escape"})
    s["figures"].append({"path": "/etc/passwd", "caption": "absolute"})
    s["figures"].append("not-a-dict-but-a-path.png")
    p.write_text(json.dumps(s))
    (linked / "bp" / "bp-resp" / "summary.json").write_text("{not json")
    rc, page, rep = run(linked, tmp_path / "out")
    assert rc == 0
    assert not list(rep.rglob("passwd"))
    assert "6. Blood pressure, respiration and baroreflex" in text(page)  # still a section, from provenance.json


def test_max_figures_and_datasets(linked: Path, tmp_path: Path) -> None:
    rc, page, rep = run(linked, tmp_path / "out", MAX_FIGURES=1, DATASET_DOIS="10.13026/C2RG61")
    assert rc == 0
    t = text(page)
    assert len(re.findall(r"<img ", page)) == 5
    assert "more figures of this step (MAX_FIGURES = 1)" in t
    assert (rep / "figures" / "stim-dose-response" / "figures__p1_hr_bpm_surface.png").is_file()
    # Fantasia with its companion paper and PhysioNet; authors from the bundled DataCite record.
    assert "Fantasia Database" in t and "Age-related alterations in the fractal scaling" in t
    assert "PhysioBank, PhysioToolkit, and PhysioNet" in t and "ODC-By 1.0" in t and "Iyengar N" in t


def test_dataset_recognised_from_source_paths(linked: Path, tmp_path: Path) -> None:
    p = linked / "qc" / "physio-import" / "provenance.json"
    s = json.loads(p.read_text())
    s["inputs"] = ["discover-349/files/primary/sub-2/subject-2.hdf5"]
    p.write_text(json.dumps(s))
    rc, page, _ = run(linked, tmp_path / "out")
    t = text(page)
    assert rc == 0 and "Influence of vagus nerve stimulation on cardiac activity in pigs" in t and "CC BY 4.0" in t


def test_previous_report_is_ignored(linked: Path, tmp_path: Path) -> None:
    run(linked, tmp_path / "out1")
    shutil.copytree(tmp_path / "out1" / "physio-report", linked / "old" / "physio-report")
    rc, page, _ = run(linked, tmp_path / "out2")
    assert rc == 0 and "physio-report 0" not in text(page).split("How to cite")[0]


def test_no_input_and_bad_parameters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "empty").mkdir()
    assert run(tmp_path / "empty", tmp_path / "out")[0] == 1
    monkeypatch.setenv("INPUT_DIR", str(tmp_path / "empty"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    for name, value in (("MAX_FIGURES", "many"), ("MAX_FIGURES", "-1"), ("WRITE_PDF", "maybe"),
                        ("DATASET_DOIS", "not-a-doi")):
        monkeypatch.setenv(name, value)
        assert M.main() == 2
        monkeypatch.delenv(name)


def test_licence_citations_string_is_one_doi(linked: Path, tmp_path: Path) -> None:
    p = linked / "events" / "stim-events" / "provenance.json"
    s = json.loads(p.read_text())
    s["licence_notice"] = {"text": "Terms apply.", "citations": "10.1161/01.HYP.12.2.214"}
    p.write_text(json.dumps(s))
    rc, page, _ = run(linked, tmp_path / "out")
    t = text(page)
    assert rc == 0 and "Terms apply. Please cite [" in t and "DOI only" not in t


def test_reference_formatting() -> None:
    from processor.citations import entry, software_name

    e = entry("10.1111/j.1540-8159.2010.02841.x")
    assert e["authors"].startswith("Nunan D, Sandercock GRH") and e["short"] == "Nunan et al. 2010"
    assert entry("10.1016/j.biopsycho.2011.11.009")["end"] == ""
    assert software_name("uwmadison-chm/bioread: 2.1.2") == "bioread"


@pytest.mark.skipif(not weasyprint_works(), reason="WeasyPrint needs Pango (in the image)")
def test_pdf(linked: Path, tmp_path: Path) -> None:
    rc, _, rep = run(linked, tmp_path / "out", WRITE_PDF=True)
    assert rc == 0
    pdf = (rep / "report.pdf").read_bytes()
    assert pdf.startswith(b"%PDF") and len(pdf) > 20_000


def test_pdf_footer_title_is_css_escaped(linked: Path, tmp_path: Path) -> None:
    from processor import model as Mo
    from processor.inputs import find
    from processor.render import css_string, html

    assert str(css_string('A & B "x" </style>')) == 'A & B \\22 x\\22  \\3c /style\\3e '
    m = Mo.build(find(linked), {**PARAMS, "REPORT_TITLE": "ECG & BP"}, "0")
    m.update(generated="", warnings_total=0)
    assert 'content: "ECG & BP · research' in html(m, pdf=True)
