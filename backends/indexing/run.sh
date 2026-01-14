#!/bin/bash
# Local development runner
# PLEASE SET THESE VARIABLES IN YOUR SHELL OR .env FILE
# DO NOT COMMIT SECRETS HERE

# export LAWA_DB_PG_HOST=localhost
# export LAWA_DB_PG_PORT=5432
# export LAWA_DB_PG_USER=postgres
# export LAWA_DB_PG_PASSWORD=postgres
# export LAWA_DB_PG_DATABASE=lawa_platform

lsof -ti:8000 | xargs kill -9 2>/dev/null || true
source env/bin/activate
python3 start_api.py