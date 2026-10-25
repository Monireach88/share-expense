# Usage: make <target>. Dev runs in Docker behind the shared nginx-proxy (http://share-expense.local).
ENV_FILE := .env
COMPOSE := docker compose --env-file $(ENV_FILE) -f docker-compose.dev.yml

dev:            ## Start the dev environment
	$(COMPOSE) up -d
down:           ## Stop it
	$(COMPOSE) down
rebuild:        ## Rebuild images and recreate containers
	$(COMPOSE) up -d --build --force-recreate
logs:           ## Follow web logs
	$(COMPOSE) logs -f web
migrate:        ## Apply migrations
	$(COMPOSE) exec web python manage.py migrate
migrations:     ## Generate migrations from model changes
	$(COMPOSE) exec web python manage.py makemigrations
superuser:      ## Create the admin account
	$(COMPOSE) exec web python manage.py createsuperuser
shell:          ## Shell in the web container
	$(COMPOSE) exec web bash
test:           ## Run all tests against the real Postgres
	$(COMPOSE) exec web pytest -q --tb=short
lint:           ## Lint
	$(COMPOSE) exec web ruff check . && $(COMPOSE) exec web ruff format --check .
clean:          ## Stop and delete the database volume
	$(COMPOSE) down -v
help:
	@grep -E '^[a-z]+:.*##' Makefile | sed 's/:.*##/ -/'

.PHONY: dev down rebuild logs migrate migrations superuser shell test lint clean help
