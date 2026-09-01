#! /usr/bin/env bash

set -e
set -x

# Run migrations
alembic upgrade head

# Create initial data in DB, right now it is only setting up the first user
python app/initial_data.py
