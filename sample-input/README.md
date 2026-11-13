# Sample input

physio-report reads the outputs of the other physiology apps, not raw recordings. To get real input:

1. Stage the demo data (`workflow-physiology/scripts/fetch-sample-data.sh`): Pennsieve Discover datasets 349
   (pig vagus nerve stimulation grid, doi:10.26275/dm5l-tspb), 655 (rat heart-rate control,
   doi:10.26275/5cwo-mkpz) and 406 (human ECG, doi:10.26275/nung-b9bm), and the PhysioNet Fantasia
   (doi:10.13026/C2RG61) and Autonomic Aging (doi:10.13026/2hsy-t491) databases.
2. Run physio-import on them, then the steps of either workflow: stim-events, ecg-hrv, bp-resp and
   stim-dose-response (Cardiovascular Response to Nerve Stimulation), or ecg-hrv and bp-resp (Heart Rate
   Variability and Baroreflex). Their outputs land in `workflow-physiology/data/work/<demo>/<app>/`.
3. `make demo DEMO=d349` (or `scripts/run_demo.sh fantasia`) mounts whatever is there into the report's ports
   (`qc`, `events`, `hrv`, `bp`, `responses`) and writes `data/work/<demo>/physio-report/physio-report/`.

Without the demo data, `make fixture` writes a small synthetic set of every app's outputs to
`data/fixture/linked/` (one folder per port) and `data/fixture/flat/` (merged, with physio-import's `physio`
port index), and `make run` renders it.
