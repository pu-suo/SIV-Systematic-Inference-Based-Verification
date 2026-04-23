#!/usr/bin/env bash
# Verify that strict-mode scoring produces identical per-premise results
# to the baseline report for all premises that succeeded in both runs.
#
# Because the LLM API is non-deterministic across sessions (rate limits,
# model fingerprint drift), the failure set and aggregate stats can vary.
# This script isolates the deterministic signal: for each premise that
# succeeded in both runs, are the scoring fields byte-identical?
#
# Prerequisites: jq, python, reports/folio_agreement_after_prompt_fix.json
set -euo pipefail

BASELINE="reports/folio_agreement_after_prompt_fix.json"
if [ ! -f "$BASELINE" ]; then
    echo "FAIL: baseline report not found at $BASELINE" >&2
    exit 1
fi

TMPFILE=$(mktemp)
trap 'rm -f "$TMPFILE" "${TMPFILE}".*' EXIT

echo "Running strict-mode evaluation..."
python scripts/run_folio_evaluation.py --mode strict --split validation --output "$TMPFILE"

# Extract per_pair arrays, strip non-deterministic / new fields, key by (story_id, nl)
# Fields stripped: alignment (new), trace references (line numbers shift with edits)
JQ_NORMALIZE='
  [.per_pair[]
   | .folio_faithfulness |= del(.alignment)
   | {key: "\(.story_id)|\(.nl)", value: .}
  ] | from_entries
'

jq -S "$JQ_NORMALIZE" "$TMPFILE" > "${TMPFILE}.new"
jq -S "$JQ_NORMALIZE" "$BASELINE" > "${TMPFILE}.ref"

# Find premises present in both runs (intersection of keys)
jq -r 'keys[]' "${TMPFILE}.new" > "${TMPFILE}.keys_new"
jq -r 'keys[]' "${TMPFILE}.ref" > "${TMPFILE}.keys_ref"
comm -12 <(sort "${TMPFILE}.keys_new") <(sort "${TMPFILE}.keys_ref") > "${TMPFILE}.shared_keys"

SHARED=$(wc -l < "${TMPFILE}.shared_keys" | tr -d ' ')
TOTAL_NEW=$(wc -l < "${TMPFILE}.keys_new" | tr -d ' ')
TOTAL_REF=$(wc -l < "${TMPFILE}.keys_ref" | tr -d ' ')
echo "Premises: new=$TOTAL_NEW baseline=$TOTAL_REF shared=$SHARED"

if [ "$SHARED" -eq 0 ]; then
    echo "FAIL: no shared premises to compare" >&2
    exit 1
fi

# Extract only shared keys from both, compare
JQ_FILTER_SHARED='
  . as $data
  | [inputs | . as $key | $data[$key] // empty | {key: $key, value: .}]
  | from_entries
'

jq -S --slurpfile keys <(jq -R '.' "${TMPFILE}.shared_keys") \
  '[ . as $d | $keys[] | . as $k | $d[$k] // empty | {key: $k, value: .} ] | from_entries' \
  "${TMPFILE}.new" > "${TMPFILE}.shared_new"

jq -S --slurpfile keys <(jq -R '.' "${TMPFILE}.shared_keys") \
  '[ . as $d | $keys[] | . as $k | $d[$k] // empty | {key: $k, value: .} ] | from_entries' \
  "${TMPFILE}.ref" > "${TMPFILE}.shared_ref"

if diff -q "${TMPFILE}.shared_new" "${TMPFILE}.shared_ref" > /dev/null 2>&1; then
    echo "PASS: all $SHARED shared premises have identical scoring in strict mode"
    ONLY_NEW=$((TOTAL_NEW - SHARED))
    ONLY_REF=$((TOTAL_REF - SHARED))
    if [ "$ONLY_NEW" -gt 0 ] || [ "$ONLY_REF" -gt 0 ]; then
        echo "  (${ONLY_NEW} premises only in new run, ${ONLY_REF} only in baseline — API non-determinism)"
    fi
    exit 0
else
    echo "FAIL: scoring differs on shared premises:" >&2
    diff "${TMPFILE}.shared_new" "${TMPFILE}.shared_ref" | head -50 >&2
    exit 1
fi
