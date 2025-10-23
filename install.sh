#!/bin/bash

set -euo pipefail

# Bash script to create a virtual environment, install dependencies, and optionally run the bot

# Define variables
venv_name="${VENV_NAME:-venv}"
python_file="autobot.py"
run_autobot="${RUN_AUTOBOT:-1}"

# Determine which Python binary to use
if [ -n "${PYTHON_BIN:-}" ]; then
    python_bin="$PYTHON_BIN"
else
    python_bin="$(command -v python3.13 || true)"
    if [ -z "$python_bin" ]; then
        python_bin="$(command -v python3 || true)"
    fi
    if [ -z "$python_bin" ]; then
        python_bin="$(command -v python || true)"
    fi
fi

if [ -z "${python_bin:-}" ]; then
    echo "Error: No suitable Python interpreter found. Please install Python 3.10+ (3.13 recommended)."
    exit 1
fi

echo "Using Python interpreter: $python_bin"

# Create virtual environment
if [ ! -d "$venv_name" ]; then
    echo "Creating virtual environment '$venv_name'..."
    "$python_bin" -m venv "$venv_name"
else
    echo "Virtual environment '$venv_name' already exists. Reusing it."
fi

# Activate virtual environment
if [ -f "$venv_name/bin/activate" ]; then
    echo "Activating virtual environment..."
    source "$venv_name/bin/activate"
else
    echo "Error: Failed to find virtual environment activation script."
    exit 1
fi

# Check if requirements.txt exists and install dependencies
if [ -f "requirements.txt" ]; then
    echo "Installing dependencies from requirements.txt..."
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
else
    echo "Warning: requirements.txt not found. Skipping dependency installation."
fi

# Install pytest-playwright/patchright browsers if requested
if [ "${SKIP_PLAYWRIGHT_INSTALL:-0}" != "1" ]; then
    echo "Installing pytest-playwright and browser dependencies..."
    python -m pip install pytest-playwright patchright
    if command -v patchright &>/dev/null; then
        patchright install chromium || true
        patchright install chrome || true
    else
        echo "Warning: patchright CLI not found in PATH. Skipping browser downloads."
    fi
else
    echo "Skipping browser downloads because SKIP_PLAYWRIGHT_INSTALL=1"
fi

# Check if the Python file exists and optionally run it
if [ "$run_autobot" = "1" ]; then
    if [ -f "$python_file" ]; then
        echo "Running Python script '$python_file'..."
        python "$python_file"
    else
        echo "Error: Python file '$python_file' not found."
        deactivate
        exit 1
    fi
else
    echo "RUN_AUTOBOT is set to $run_autobot; skipping execution of '$python_file'."
fi

# Deactivate virtual environment
echo "Deactivating virtual environment..."
deactivate