#!/usr/bin/env bash
# A lancer avant chaque publication : numero de version, syntaxe, tests du robot et de l'appli.
set -e
cd "$(dirname "$0")/.."
python3 tools/bump_version.py
for f in docs/app.js docs/model.js docs/live.js docs/compose.js docs/cloud.js docs/fx.js docs/sw.js; do node --check "$f"; done
python3 -c "import ast; [ast.parse(open(f).read()) for f in ('robot/run.py','robot/model.py','robot/teams.py','robot/learn.py')]"
python3 tests/test_robot.py
python3 tests/test_app.py
