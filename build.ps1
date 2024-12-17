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

# Ensure shiv and pyinstaller are installed
$deps = @("pyinstaller")
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

# Build CLI Windows binary
Write-Host "Building Windows binary..."
pip install .
pyinstaller --onefile --strip --noconfirm --clean --exclude-module PySide6 --exclude-module tkinter --name BWAutofillerWindowsCLI $upx_flag bitwardenautofiller.py

# Build GUI Windows binary
Write-Host "Building GUI Windows binary..."
pip install .[gui]
pyinstaller --onefile --strip --noconfirm --clean --exclude-module tkinter --add-data "fillericon.png:." --name BWAutofillerWindowsGUI $upx_flag bwautofillergui.py

Write-Host "Build complete!"
