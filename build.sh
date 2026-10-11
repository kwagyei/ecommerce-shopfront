#!/usr/bin/env bash
# Render runs this on every deploy.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

# Idempotent: refreshes the demo catalog without duplicating it.
python manage.py seed
