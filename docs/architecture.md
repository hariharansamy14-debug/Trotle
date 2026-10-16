# Architecture

The system is structured as a simple monorepo with a React frontend and a Python FastAPI backend. The backend stores metadata in SQLAlchemy models and keeps document text and evidence references in the relational database. The frontend consumes a consistent API for auth, sources, chat, evidence, reports, and admin functions.

Key modules:

- app/api: auth, sources, documents, chat, evidence, reports, admin routes
- app/models: database entities and schema relationships
- app/services: file extraction, retrieval, and evidence handling
- app/core: configuration and JWT helper functions
- frontend/src: app shell, pages, and UI interactions
