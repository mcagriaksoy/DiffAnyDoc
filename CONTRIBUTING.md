# Contributing Guidelines

Thank you for considering contributing to this project! To maintain code quality, consistency, and a smooth release cycle, please review the workflow and guidelines outlined below.

---

## 1. Branch Strategy & Release Workflow

We follow a structured branching model:

* **`development`**: The default active development branch. All feature branches, bug fixes, and improvements must target this branch.
* **`main`**: Represents the stable production releases only.
  * Direct commits to `main` are strictly prohibited.
  * Merges into `main` occur **only during a release** and are merged from `development`.
  * A release is triggered exclusively when **a new feature set is completed** or **a critical hotfix is required**. The decision to cut a release and merge into `main` rests solely with project administrators.

---

## 2. Getting Started & Development Workflow

1. **Fork or Branch:**
   * Create a dedicated branch off of `development`:
     ```bash
     git checkout development
     git pull origin development
     git checkout -b feature/your-feature-name  # or fix/your-bug-fix
     ```
   * Use clear prefixes for branch names: `feature/`, `fix/`, `refactor/`, or `docs/`.

2. **Environment Setup:**
   * Set up and activate an isolated virtual environment:
     ```bash
     python -m venv .venv
     source .venv/bin/activate  # On Windows: .venv\Scripts\activate
     pip install -r requirements.txt
     pip install -r requirements-dev.txt  # If dev dependencies exist
     ```

3. **Coding Standards:**
   * **PEP 8:** Write clean, idiomatic Python complying with PEP 8.
   * **Formatting & Linting:** Run code formatters and linters (`black`, `flake8`, or `ruff`) before committing.
   * **Separation of Concerns:** Keep UI components (Views) strictly decoupled from core business logic (Models/Controllers). Design reusable, modular widgets.
   * **Type Annotations
