$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path -Path $MyInvocation.MyCommand.Definition -Parent)

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv is required to build Bitwarden Autofiller."
    exit 1
}

uv build
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
