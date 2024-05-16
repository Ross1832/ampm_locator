# Variables
PROJECT_NAME := packaging_locator
DOCKER_COMPOSE := docker compose
DJANGO_MANAGE := $(DOCKER_COMPOSE) exec web python manage.py
ENV_FILE := .env

.DEFAULT_GOAL := help

help:
	@echo "Usage: make <target>"
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# Docker commands
build: ## Build Docker images
	@$(DOCKER_COMPOSE) build

up: ## Start Docker containers
	@$(DOCKER_COMPOSE) up -d

down: ## Stop Docker containers
	@$(DOCKER_COMPOSE) down

logs: ## View logs from Docker containers
	@$(DOCKER_COMPOSE) logs

logs-web: ## View logs from the web container
	@$(DOCKER_COMPOSE) logs web

logs-db: ## View logs from the db container
	@$(DOCKER_COMPOSE) logs db

# Django management commands
migrate: ## Apply Django migrations
	@$(DJANGO_MANAGE) migrate

makemigrations: ## Apply Django makemigrations
	@$(DJANGO_MANAGE) makemigrations

createsuperuser: ## Create a Django superuser
	@$(DJANGO_MANAGE) createsuperuser

collectstatic: ## Collect static files
	@$(DJANGO_MANAGE) collectstatic --noinput

shell: ## Open a Django shell
	@$(DJANGO_MANAGE) shell

test: ## Run Django tests
	@$(DJANGO_MANAGE) test

# Utility commands
clean: ## Clean up Docker artifacts
	@$(DOCKER_COMPOSE) down -v --rmi all --remove-orphans

restart: ## Restart Docker containers
	@$(DOCKER_COMPOSE) restart

.PHONY: help build up down logs logs-web logs-db migrate createsuperuser collectstatic shell test clean restart
