param(
    [string]$Target = "I:\DFM"
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path $PSScriptRoot).Path
$targetResolved = $null

if (Test-Path $Target) {
    $targetResolved = (Resolve-Path $Target).Path
}

Write-Host "DFM Viewer fixed installer"
Write-Host "Source: $root"
Write-Host "Target: $Target"

if (-not (Test-Path $Target)) {
    throw "Target folder does not exist: $Target"
}

$files = @(
    "main.py",
    "gerber_viewer.py",
    "gerber_viewer.html"
)

foreach ($file in $files) {
    $src = Join-Path $root $file
    if (-not (Test-Path $src)) {
        throw "Missing package file: $src"
    }
}

$sourceSameAsTarget = $false
try {
    $sourceSameAsTarget = (
        (Resolve-Path $root).Path.TrimEnd('\') -ieq
        (Resolve-Path $Target).Path.TrimEnd('\')
    )
} catch {}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = Join-Path $Target "backup_viewer_$stamp"
New-Item -ItemType Directory -Path $backup -Force | Out-Null

Write-Host "Backup folder: $backup"

foreach ($file in $files) {
    $dst = Join-Path $Target $file

    if (Test-Path $dst) {
        Copy-Item $dst (Join-Path $backup $file) -Force
    }

    if ($sourceSameAsTarget) {
        Write-Host "Already in target: $file"
    } else {
        Copy-Item (Join-Path $root $file) $dst -Force
        Write-Host "Installed: $file"
    }
}

Write-Host ""
Write-Host "Checking Python syntax..."

Push-Location $Target
try {
    & python -m py_compile .\main.py .\gerber_viewer.py

    if ($LASTEXITCODE -ne 0) {
        throw "Python syntax validation failed."
    }

    Write-Host "Python syntax: OK"

    Write-Host "Checking imports..."
    & python -c "import main; import gerber_viewer; print('IMPORT_OK')"

    if ($LASTEXITCODE -ne 0) {
        throw "Python import validation failed."
    }

    Write-Host "Imports: OK"
}
catch {
    Write-Host ""
    Write-Host "INSTALLATION FAILED - restoring backup..." -ForegroundColor Red

    foreach ($file in $files) {
        $srcBackup = Join-Path $backup $file
        $dst = Join-Path $Target $file

        if (Test-Path $srcBackup) {
            Copy-Item $srcBackup $dst -Force
        }
    }

    throw
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "=============================================="
Write-Host "INSTALLATION COMPLETE"
Write-Host "=============================================="
Write-Host "Backup: $backup"
Write-Host ""
Write-Host "Start your server normally, then open:"
Write-Host "http://127.0.0.1:8000/gerber_viewer.html?project_id=<PROJECT_ID>"
