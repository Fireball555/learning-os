#!/usr/bin/env bash
# Rebuild the shop schema + seed and freeze questions.json. Uses ADMIN_DATABASE_URL from .env.
# WARNING: --wipe-app also deletes all learner data. Never run with --wipe-app after the pretest.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
python db/generate_seed.py
psql "$ADMIN_DATABASE_URL" -q -v ON_ERROR_STOP=1 -f db/01_schema.sql -f db/02_seed.sql
psql "$ADMIN_DATABASE_URL" -q -v ON_ERROR_STOP=1 -c "GRANT USAGE ON SCHEMA shop TO learner_ro; GRANT SELECT ON ALL TABLES IN SCHEMA shop TO learner_ro;"
if [[ "${1:-}" == "--wipe-app" ]]; then
  psql "$ADMIN_DATABASE_URL" -q -c "TRUNCATE app.attempts, app.question_views, app.hints, app.survey, app.events, app.learners RESTART IDENTITY CASCADE;"
fi
python scripts/build_questions.py
