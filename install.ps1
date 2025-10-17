# PowerShell script to create a virtual environment, install dependencies, and run a Python file

# Define variables
$venvName = "venv"
$pythonFile = "autobot.py"

# Check if Python is installed
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python is not installed or not found in PATH."
    exit 1
}

# Create virtual environment
Write-Host "Creating virtual environment '$venvName'..."
python3.13 -m venv $venvName

# Activate virtual environment
$venvActivateScript = Join-Path $venvName "Scripts\Activate.ps1"
if (Test-Path $venvActivateScript) {
    Write-Host "Activating virtual environment..."
    & $venvActivateScript
} else {
    Write-Error "Failed to find virtual environment activation script."
    exit 1
}

# Check if requirements.txt exists and install dependencies
if (Test-Path "requirements.txt") {
    Write-Host "Installing dependencies from requirements.txt..."
    pip install -r requirements.txt
} else {
    Write-Warning "requirements.txt not found. Skipping dependency installation."
}

# Install pytest-playwright and its dependencies
echo "Installing pytest-playwright and its dependencies..."
pip install --upgrade pip
pip install pytest-playwright patchright
patchright install chromium
patchright install chrome

# Check if the Python file exists and run it
if (Test-Path $pythonFile) {
    Write-Host "Running Python script '$pythonFile'..."
    python $pythonFile
} else {
    Write-Error "Python file '$pythonFile' not found."
    exit 1
}

# Deactivate virtual environment
Write-Host "Deactivating virtual environment..."
deactivate