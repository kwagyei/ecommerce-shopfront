#!/usr/bin/env bash
# Render runs this on every deploy.
set -o errexit

pip install -r requirements.txt
# Refuse to release a misconfigured build, e.g. one missing DJANGO_SECRET_KEY.
python manage.py check --deploy --fail-level ERROR
python manage.py collectstatic --no-input
python manage.py migrate

# Seeds an empty catalog only; never overwrites stock, prices or withdrawals.
python manage.py seed
