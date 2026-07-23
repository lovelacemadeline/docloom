#!/usr/bin/env bash
# Parity harness: byte-diff `docloom check` against the original crosssense
# checker on the crosssense corpus. Both run from the crosssense repo root so
# git-derived data (ls-files, last-commit dates, branch diff) is identical.
set -uo pipefail

DOCWEAVE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CROSSSENSE="${CROSSSENSE_REPO:-$HOME/Documents/CrossSense/development/crosssense-v3-server}"
OUT="${PARITY_OUT:-$DOCWEAVE_DIR/parity/out}"
mkdir -p "$OUT"

run_pair() {
    local label="$1"; shift
    local flags=("$@")
    (cd "$CROSSSENSE" && uv run python scripts/check_doc_conventions.py ${flags[@]+"${flags[@]}"}) \
        >"$OUT/original-$label.txt" 2>&1
    local orig_rc=$?
    (cd "$CROSSSENSE" && uv --project "$DOCWEAVE_DIR" run docloom check \
        --root "$CROSSSENSE" --config "$DOCWEAVE_DIR/examples/crosssense.toml" ${flags[@]+"${flags[@]}"}) \
        >"$OUT/docloom-$label.txt" 2>&1
    local dw_rc=$?
    if diff -u "$OUT/original-$label.txt" "$OUT/docloom-$label.txt" >"$OUT/diff-$label.txt"; then
        echo "PARITY OK   [$label]  (exit: original=$orig_rc docloom=$dw_rc)"
    else
        echo "PARITY FAIL [$label]  (exit: original=$orig_rc docloom=$dw_rc) — see $OUT/diff-$label.txt"
    fi
    [ "$orig_rc" = "$dw_rc" ] || echo "  EXIT-CODE MISMATCH [$label]: $orig_rc vs $dw_rc"
}

run_pair strict
run_pair summary --summary
run_pair valid-if-present --valid-if-present
