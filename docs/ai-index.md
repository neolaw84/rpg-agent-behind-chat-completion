# AI & Developer Guidance Index

Welcome to the RPG Agent Behind Chat Completion repository! This file serves as the main index for developer and AI rules, conventions, and workflows.

## Project Structure
- `src/rpg_agent/`: Main source package.
- `tests/`: Project unit and integration tests.
- `notebooks/`: Jupyter notebooks for experiments and prototyping.
- `docs/`: Project documentation.

## Guidelines
- Follow standard PEP 8 coding styles.
- Use `pytest` for running test suites.
- **Virtual Environment (`venv`)**:
  - Always use a virtual environment named `venv` located in the repository root.
  - If `venv` does not exist:
    - Build it using an existing Python 3.12 conda environment named `py312`.
    - If the `py312` conda environment does not exist but `conda` is available, create the `py312` environment first.
    - If `conda` is not available, use whatever Python environment is available and print out a warning.
