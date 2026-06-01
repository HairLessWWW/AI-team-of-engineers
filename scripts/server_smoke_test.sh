#!/usr/bin/env bash
set -euo pipefail

cd /opt/ai-team-of-engineers
export PYTHONPATH=/opt/ai-team-of-engineers/src

.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ai_engineering_platform telegram-check
