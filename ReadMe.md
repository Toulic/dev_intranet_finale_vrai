# :shield: Plateforme Scolaire Sécurisée (Promo 2026)

[![Security and Quality Audit](https://github.com/TON_USER/TON_REPO/actions/workflows/main.yml/badge.svg)](https://github.com/TON_USER/TON_REPO/actions)

Ce projet est une application web de gestion scolaire (notes, absences, messagerie) développée avec **Flask** et **MySQL**, entièrement durcie contre les cyberattaques les plus courantes.

## :rocket: Fonctionnalités
- **Gestion des rôles (RBAC)** : Accès différenciés pour les Administrateurs, Professeurs et Élèves.
- **Messagerie Interne** : Communication sécurisée entre utilisateurs.
- **Gestion des Notes** : Interface dédiée pour la saisie et la consultation.

## :tools: Stack Technique
- **Backend** : Python 3.10, Flask
- **Base de données** : MySQL 8.0
- **Conteneurisation** : Docker & Docker-Compose
- **CI/CD** : GitHub Actions (Flake8, Bandit, Pip-audit, OWASP ZAP)

## :package: Installation et Lancement

### Pré-requis
- Docker et Docker-Compose installés.
- Git.

Lancer avec Docker : 

	docker-compose up --build -d
	docker-compose exec app python init_db.py

Accéder à l'application :
    
	Rendez-vous sur https://localhost


Projet réalisé dans le cadre du module de Développement Web sécurisé - 2026.


