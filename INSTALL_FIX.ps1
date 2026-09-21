$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = "I:\DFM"

if (-not (Test-Path $target)) {
    throw "DFM folder not found: $target"
}

Write-Host "Stopping is required before replacement." -ForegroundColor Yellow
Write-Host "Make sure uvicorn is stopped (Ctrl+C)." -ForegroundColor Yellow

Copy-Item "$target\gerber_viewer.py" "$target\gerber_viewer.py.backup_$(Get-Date -Format yyyyMMdd_HHmmss)" -ErrorAction SilentlyContinue
Copy-Item "$target\gerber_viewer.html" "$target\gerber_viewer.html.backup_$(Get-Date -Format yyyyMMdd_HHmmss)" -ErrorAction SilentlyContinue

Copy-Item "$root\gerber_viewer.py" "$target\gerber_viewer.py" -Force
Copy-Item "$root\gerber_viewer.html" "$target\gerber_viewer.html" -Force

python -m py_compile "$target\gerber_viewer.py"

Write-Host ""
Write-Host "Viewer files replaced successfully." -ForegroundColor Green
Write-Host "IMPORTANT: restart uvicorn and hard-refresh the browser (Ctrl+F5)." -ForegroundColor Yellow
