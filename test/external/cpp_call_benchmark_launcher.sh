#!/bin/sh
set -eu

case "$(basename "$0")" in
  baseline-runner) target=${FAULTDEBUG_BENCH_BASELINE:?} ;;
  instrumented-runner) target=${FAULTDEBUG_BENCH_INSTRUMENTED:?} ;;
  *) echo "unknown benchmark launcher name" >&2; exit 64 ;;
esac

if [ "$#" -ne 3 ]; then
  echo "usage: benchmark-runner ARTIFACT_DIR WORKERS ITERATIONS" >&2
  exit 64
fi

artifact_dir=$1
workers=$2
iterations=$3
exec "${FAULTDEBUG_BENCH_PYTHON:?}" -m faultdebug.cli run \
  --collect-success --artifact-dir "$artifact_dir" -- \
  "$target" "$workers" "$iterations"
