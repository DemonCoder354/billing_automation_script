<#
.SYNOPSIS
    Builds the three programs into stand-alone .exe files and packs a release zip.

.DESCRIPTION
    1. Creates .venv (if missing) and installs requirements-dev.txt.
    2. Runs pyflakes and the tests.
    3. Builds PDFTickets.exe, AutoWork.exe and WeekFolders.exe with PyInstaller (one file, no console).
    4. Packs dist\ into release\BillingAutomation-<version>-win64.zip.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File build.ps1
#>
param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    py -3.11 -m venv .venv
}
& $python -m pip install --disable-pip-version-check -q -r requirements-dev.txt
if ($LASTEXITCODE) { throw "pip install failed" }

if (-not $SkipTests) {
    & $python -m pyflakes src tests
    if ($LASTEXITCODE) { throw "pyflakes found problems" }
    & $python -m pytest -q
    if ($LASTEXITCODE) { throw "tests failed" }
}

$version = (& $python -c "import sys; sys.path.insert(0, 'src'); import billing_automation as b; print(b.__version__)").Trim()
$apps = @(
    @{ Name = "PDFTickets";  Script = "scripts\pdf_tickets.pyw" },
    @{ Name = "AutoWork";    Script = "scripts\auto_work.pyw" },
    @{ Name = "WeekFolders"; Script = "scripts\week_folders.pyw" }
)

if (Test-Path dist) { Remove-Item -Recurse -Force dist }
foreach ($app in $apps) {
    Write-Host "Building $($app.Name).exe ..."
    & $python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name $app.Name `
        --paths "$PSScriptRoot\src" `
        --add-data "$PSScriptRoot\src\billing_automation\resources;billing_automation\resources" `
        --workpath build --specpath build --distpath dist `
        $app.Script
    if ($LASTEXITCODE) { throw "PyInstaller failed for $($app.Name)" }
}

Copy-Item README.md, doctors.example.txt dist\
New-Item -ItemType Directory -Force release | Out-Null
$zip = "release\BillingAutomation-$version-win64.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path dist\* -DestinationPath $zip
Write-Host "Done: $zip"
