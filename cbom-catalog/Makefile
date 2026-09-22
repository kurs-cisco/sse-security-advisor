.PHONY: up down migrate ingest service-impact refresh force-refresh inventory test logs

up:
	docker compose up -d postgres migrate api web

down:
	docker compose down

migrate:
	docker compose run --rm migrate

ingest:
	docker compose --profile tools run --rm ingest

service-impact:
	docker compose --profile tools run --rm service-impact

refresh: ingest

force-refresh:
	docker compose --profile tools run --rm ingest cbom-catalog ingest /data/SSE_CBOMS --collection sse-cboms --force-reprocess

inventory:
	docker compose --profile tools run --rm ingest cbom-catalog inventory /data/SSE_CBOMS --pretty

test:
	PYTHONPATH=src python -m unittest discover -s tests -v

logs:
	docker compose logs -f web api postgres
