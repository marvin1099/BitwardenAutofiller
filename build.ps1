# Build.ps1: PowerShell script for building BitwardenAutofiller

# Change working dir to the script directory
Set-Location -Path (Split-Path -Path $MyInvocation.MyCommand.Definition -Parent)

# Check for Python installation
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python is not installed or not in PATH. Please install Python."
    exit 1
}

# A virtual environment is not needed on windows
# If you want this you can add it below this line


# Upgrade pip
Write-Host "Upgrading pip..."
python -m  pip install --upgrade pip

# Install dependencies from setup.py
Write-Host "Installing dependencies from setup.py..."
pip install -e .

# Ensure shiv and pyinstaller are installed
$deps = @("shiv", "pyinstaller")
foreach ($dep in $deps) {
    if (-not (pip show $dep | Out-Null)) {
        Write-Host "Installing $dep..."
        pip install $dep
    }
}

# Check for UPX
$upxPath = Get-Command upx -ErrorAction SilentlyContinue
if ($upx_path) {
    $upx_dir = Split-Path -Parent $upx_path.Path
    $upx_flag = "--noupx --upx-dir `"$upx_dir`""
    Write-Output "UPX found at $upx_dir"
} else {
    $upx_flag = ""
    Write-Output "UPX not found. Skipping UPX integration."
}

# Build Windows binary
Write-Host "Building Windows binary..."
pyinstaller --onefile --strip --clean --name BitwardenAutofillerWindows $upxFlag bitwardenautofiller.py

# Building the universal .pyz is disabled on windows as it did not finish successfully
# Write-Host "Building universal .pyz..."
# shiv -o dist/BitwardenAutofiller.pyz -e bitwardenautofiller.main:main .

Write-Host "Build complete!"
