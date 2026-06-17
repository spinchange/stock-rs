# Build the trimmed, self-contained RS.exe bundle.
#   1. PyInstaller from RS.spec (excludes unused Qt modules + heavy unused packages)
#   2. Prune WebEngine/Qt translations down to English (saves ~50 MB)
# Run:  pwsh -File build.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root
$py = "C:\Users\executor\.pyenv\pyenv-win\versions\3.12.10\python.exe"

# Stop any running instance so its files aren't locked (WebEngine spawns children).
Get-Process RS, QtWebEngineProcess -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 600

# Explicit dist/work paths so output never nests relative to a stray CWD.
& $py -m PyInstaller --noconfirm `
    --distpath (Join-Path $root "dist") `
    --workpath (Join-Path $root "build") `
    (Join-Path $root "RS.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Keep only English translations.
$tr = Join-Path $root "dist\RS\_internal\PySide6\translations"
Get-ChildItem "$tr\qtwebengine_locales\*.pak" |
    Where-Object { $_.Name -notin @("en-US.pak", "en-GB.pak") } | Remove-Item -Force
Get-ChildItem "$tr\*.qm" | Where-Object { $_.Name -notlike "*_en.qm" } | Remove-Item -Force

$bytes = (Get-ChildItem (Join-Path $root "dist\RS") -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("Build complete. dist\RS size: {0:N0} MB" -f ($bytes / 1MB))
