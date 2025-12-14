# Contributing to USA Stock Finder

Thank you for your interest in contributing to USA Stock Finder!

## How to Contribute

1.  **Fork the repository**
2.  **Create a feature branch** (`git checkout -b feature/AmazingFeature`)
3.  **Commit your changes** (`git commit -m 'Add some AmazingFeature'`)
4.  **Push to the branch** (`git push origin feature/AmazingFeature`)
5.  **Open a Pull Request**

## Development Setup

1.  Clone the repository:
    ```bash
    git clone https://github.com/k11tos/usa_stock_finder.git
    cd usa_stock_finder
    ```

2.  Create a virtual environment:
    ```bash
    python -m venv env
    source env/bin/activate
    ```

3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    pip install -r requirements_dev.txt
    ```

4.  Run tests to ensure everything is working:
    ```bash
    pytest
    ```

## Code Style

- We use `black` for formatting.
- We use `pylint` for linting.
- We use type hints (`mypy`) wherever possible.

Please ensure your code passes all tests before submitting a PR.
