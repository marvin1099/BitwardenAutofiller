#!/usr/bin/env bash
# Build.sh: Bash script for building BitwardenAutofiller

# Change working dir to the script directory
cd "$(dirname "$0")"

# Ensure Python is installed
if ! command -v python &> /dev/null; then
    echo "Python is not installed or not in PATH. Please install Python."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies from setup.py
echo "Installing dependencies from setup.py..."
pip install -e .

# Ensure shiv and pyinstaller are installed
for dep in shiv pyinstaller; do
    if ! pip show "$dep" > /dev/null 2>&1; then
        echo "Installing $dep..."
        pip install "$dep"
    fi
done

# Check for UPX
if command -v upx &> /dev/null; then
    upx_dir=$(dirname "$(command -v upx)")
    echo "UPX found at $upx_dir"
    upx_flag="--upx-dir $upx_dir"
else
    echo "UPX not found. Skipping UPX integration."
    upx_flag=""
fi


# Build Linux binary
echo "Building Linux binary..."
pyinstaller --onefile --strip --noconfirm --clean --name BitwardenAutofillerLinux $upx_flag bitwardenautofiller.py

# Build universal .pyz
echo "Building universal .pyz..."
shiv -o dist/BitwardenAutofiller.pyz -e bitwardenautofiller.main:main .

echo "Build complete!"
