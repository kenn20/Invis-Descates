#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${TEST_DATABASE_URL:?Set TEST_DATABASE_URL to an isolated PostgreSQL database; this gate must not skip database tests}"
"${PYTHON_BIN:-python}" -m pytest service/tests -q
npm --prefix plugin test
npm --prefix plugin run typecheck
npm --prefix plugin run build
git diff --check
