# Usage: make <target> [ENV=dev|prod]. ENV defaults to dev (http://share-expense.local).
# Each environment is one compose file with every service it needs: docker-compose.$(ENV).yml.
# The shared nginx-proxy stays outside: it serves every project on the machine.
ENV ?= dev
ifeq ($(filter $(ENV),dev prod),)
$(error ENV must be dev or prod, not "$(ENV)")
endif
ENV_FILE := $(if $(filter prod,$(ENV)),.env.prod,.env)
COMPOSE := docker compose --env-file $(ENV_FILE) -f docker-compose.$(ENV).yml
# Tests, lint and migration files need the dev image (it has the dev tools and the mounted code).
DEV := docker compose --env-file .env -f docker-compose.dev.yml

up: $(ENV_FILE)   ## Build if needed and start every service (ENV=prod for production)
	$(COMPOSE) up -d --build
	@$(COMPOSE) ps
down:             ## Stop every service
	$(COMPOSE) down
restart:          ## Restart every service
	$(COMPOSE) restart
rebuild: $(ENV_FILE)  ## Rebuild images and recreate containers
	$(COMPOSE) up -d --build --force-recreate
ps:               ## Show service status
	$(COMPOSE) ps
logs:             ## Follow web logs
	$(COMPOSE) logs -f web
migrate:          ## Apply migrations
	$(COMPOSE) exec web python manage.py migrate
superuser:        ## Create the admin account
	$(COMPOSE) exec web python manage.py createsuperuser
shell:            ## Bash in the web container
	$(COMPOSE) exec web bash
migrations:       ## Generate migrations from model changes (dev only)
	$(DEV) exec web python manage.py makemigrations
test:             ## Run all tests against the real Postgres (dev only)
	$(DEV) exec web pytest -q --tb=short
lint:             ## ruff check + format check (dev only)
	$(DEV) exec web ruff check . && $(DEV) exec web ruff format --check .
clean:            ## Stop and DELETE the database volume (dev only)
	$(DEV) down -v
help:             ## List targets
	@grep -E '^[a-z]+:.*##' Makefile | sed -E 's/:[^#]*##/ -/'

# First dev run: start from the documented defaults. Production values are never guessed.
.env:
	cp .env.example .env
.env.prod:
	@echo "Missing .env.prod: copy .env.example and fill in the production values (see DOCKER_SETUP.md)." && exit 1

.PHONY: up down restart rebuild ps logs migrate superuser shell migrations test lint clean help
