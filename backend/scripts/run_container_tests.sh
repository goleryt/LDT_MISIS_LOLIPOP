#!/bin/sh
set -eu
test "$ENVIRONMENT" = test
test "$POSTGRES_DB" = ldt_test
python -m pip install --no-cache-dir --target /tmp/testdeps pytest==9.1.1
export PYTHONPATH=/tmp/testdeps:/app
python -m alembic upgrade head
python -m alembic check
python -m pytest -q -p no:cacheprovider
