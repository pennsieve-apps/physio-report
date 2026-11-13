#!/bin/sh
# Run the image on a demo's real step outputs, as the platform would (read-only root, any uid,
# no network, HOME/TMPDIR under /tmp, 2 GB), and write data/work/<demo>/physio-report/.
#
#   scripts/run_demo.sh d349 [stim|hrv]
#
# The second argument picks the workflow whose steps are linked: `stim` (Cardiovascular Response
# to Nerve Stimulation: qc, events, hrv, bp, responses; the default for d349 and d655) or `hrv`
# (Heart Rate Variability and Baroreflex: qc, hrv, bp; the default otherwise). Each step found
# under data/work/<demo>/<app>/ is mounted at its port folder; steps not there yet are left out
# (the report renders whatever is linked) and named on stdout. Prints the cgroup peak memory.
set -eu
DEMO=${1:?usage: run_demo.sh <demo> [stim|hrv]}
case "$DEMO" in d349|d655) WF=${2:-stim} ;; *) WF=${2:-hrv} ;; esac
DATA=${DATA:-$(cd "$(dirname "$0")/../../workflow-physiology/data/work" && pwd)}
W="$DATA/$DEMO"
OUT=${OUT:-$W/physio-report}
IMAGE=${IMAGE:-physio-report:dev}
mkdir -p "$OUT"
set -- --rm --platform linux/amd64 --read-only --user 65534:65534 --tmpfs /tmp:mode=1777 --network none \
  --memory 2g -e HOME=/tmp/w/home -e TMPDIR=/tmp/w/tmp -e INPUT_DIR=/tmp/s/input -e OUTPUT_DIR=/tmp/s/output \
  -v "$OUT":/tmp/s/output
if [ -d "$W/physio-import/qc" ]; then set -- "$@" -v "$W/physio-import/qc":/tmp/s/input/qc:ro
else echo "not linked (missing): physio-import qc"; fi
if [ "$WF" = stim ]; then PAIRS="events:stim-events hrv:ecg-hrv bp:bp-resp responses:stim-dose-response"
else PAIRS="hrv:ecg-hrv bp:bp-resp"; fi
for pair in $PAIRS; do
  port=${pair%%:*}; app=${pair#*:}
  # The demo folder is <app>/<port>/<app>/... (an app with one output writes the port folder).
  if [ -d "$W/$app/$port/$app" ]; then set -- "$@" -v "$W/$app/$port":/tmp/s/input/$port:ro
  elif [ -d "$W/$app/$app" ]; then set -- "$@" -v "$W/$app":/tmp/s/input/$port:ro
  elif [ -f "$W/$app/summary.json" ]; then set -- "$@" -v "$W/$app":/tmp/s/input/$port/$app:ro
  else echo "not linked (missing): $app"; fi
done
docker run "$@" --entrypoint sh "$IMAGE" -c 'python3 -m processor.main; rc=$?; echo "cgroup memory.peak $(cat /sys/fs/cgroup/memory.peak 2>/dev/null) bytes"; exit $rc'
