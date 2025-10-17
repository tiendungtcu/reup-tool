#!/bin/bash

# Bash script to create a virtual environment, install dependencies, and run a Python file

# Define variables
venv_name="venv"
python_file="autobot.py"

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python3 is not installed or not found in PATH."
    exit 1
fi

# Create virtual environment
echo "Creating virtual environment '$venv_name'..."
python3.13 -m venv "$venv_name"

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
    pip install -r requirements.txt
else
    echo "Warning: requirements.txt not found. Skipping dependency installation."
fi

# Install pytest-playwright and its dependencies
echo "Installing pytest-playwright and its dependencies..."
pip install --upgrade pip
pip install pytest-playwright patchright
patchright install chromium
patchright install chrome

# Check if the Python file exists and run it
if [ -f "$python_file" ]; then
    echo "Running Python script '$python_file'..."
    python3 "$python_file"
else
    echo "Error: Python file '$python_file' not found."
    exit 1
fi

# Deactivate virtual environment
echo "Deactivating virtual environment..."
deactivate