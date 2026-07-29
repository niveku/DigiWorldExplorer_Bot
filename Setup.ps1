[CmdletBinding()]
param(
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$venvDir = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
function Show-RobinThorBanner {
    try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch {}

    $logo = @(
        '██████╗  ██████╗ ██████╗ ██╗███╗   ██╗████████╗██╗  ██╗ ██████╗ ██████╗ '
        '██╔══██╗██╔═══██╗██╔══██╗██║████╗  ██║╚══██╔══╝██║  ██║██╔═══██╗██╔══██╗'
        '██████╔╝██║   ██║██████╔╝██║██╔██╗ ██║   ██║   ███████║██║   ██║██████╔╝'
        '██╔══██╗██║   ██║██╔══██╗██║██║╚██╗██║   ██║   ██╔══██║██║   ██║██╔══██╗'
        '██║  ██║╚██████╔╝██████╔╝██║██║ ╚████║   ██║   ██║  ██║╚██████╔╝██║  ██║'
        '╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝'
    )
    $versionPath = Join-Path $PSScriptRoot 'VERSION'
    $version = if (Test-Path -LiteralPath $versionPath) { (Get-Content -LiteralPath $versionPath -Raw).Trim() } else { 'dev' }
    $subtitle = "[ Digimon UP - DigiWorldExplorer_Bot v$version ]"
    $guildLine = '✨ EXCLUSIVE FOR GERMON MEMBERS ✨'
    $contentWidth = ($logo | ForEach-Object Length | Measure-Object -Maximum).Maximum

    function Center-BannerText([string]$Text) {
        $left = [Math]::Max(0, [Math]::Floor(($contentWidth - $Text.Length) / 2))
        return ((' ' * $left) + $Text).PadRight($contentWidth)
    }

    Write-Host ''
    Write-Host ('╔' + ('═' * ($contentWidth + 2)) + '╗') -ForegroundColor Yellow
    Write-Host ('║ ' + (' ' * $contentWidth) + ' ║') -ForegroundColor Yellow
    foreach ($line in $logo) {
        Write-Host ('║ ' + $line.PadRight($contentWidth) + ' ║') -ForegroundColor Yellow
    }
    Write-Host ('║ ' + (' ' * $contentWidth) + ' ║') -ForegroundColor Yellow
    Write-Host ('║ ' + (Center-BannerText $subtitle) + ' ║') -ForegroundColor Cyan
    Write-Host ('║ ' + (Center-BannerText $guildLine) + ' ║') -ForegroundColor Yellow
    Write-Host ('║ ' + (' ' * $contentWidth) + ' ║') -ForegroundColor Yellow
    Write-Host ('╚' + ('═' * ($contentWidth + 2)) + '╝') -ForegroundColor Yellow
    Write-Host ''
}

function Find-Python {
    $commands = @('py.exe', 'python.exe', 'python3.exe')
    foreach ($name in $commands) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $command) { continue }

        if ($name -eq 'py.exe') {
            $candidate = @(& $command.Source -3 -c "import sys; print(sys.executable)" 2>$null)
        } else {
            $candidate = @(& $command.Source -c "import sys; print(sys.executable)" 2>$null)
        }
        if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path -LiteralPath $candidate[-1])) {
            return $candidate[-1]
        }
    }
    $localPythons = @(Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python*\python.exe') -File -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)
    foreach ($candidate in $localPythons) {
        & $candidate.FullName -c "import sys; raise SystemExit(sys.version_info < (3, 10))" 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidate.FullName }
    }
    return $null
}

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Befehl fehlgeschlagen (Exit-Code $LASTEXITCODE): $Program $($Arguments -join ' ')"
    }
}

function Install-PythonWithWinget {
    $winget = Get-Command 'winget.exe' -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw 'Python 3.10+ wurde nicht gefunden und winget ist nicht verfuegbar. Installiere Python von python.org und starte INSTALL.cmd erneut.'
    }
    Write-Host 'Python 3.10 oder neuer wurde nicht gefunden.' -ForegroundColor Yellow
    $answer = Read-Host 'Python 3.12 jetzt automatisch mit winget installieren? [J/n]'
    if (-not [string]::IsNullOrWhiteSpace($answer) -and $answer -notmatch '^(j|ja|y|yes)$') {
        throw 'Installation abgebrochen. Installiere Python 3.10+ manuell und starte INSTALL.cmd erneut.'
    }
    Write-Host 'Installiere Python 3.12 ueber winget ...' -ForegroundColor Cyan
    Invoke-Checked -Program $winget.Source -Arguments @('install', '--id', 'Python.Python.3.12', '--exact', '--source', 'winget', '--accept-package-agreements', '--accept-source-agreements')
}
Set-Location -LiteralPath $projectRoot
Show-RobinThorBanner
$basePython = Find-Python
if (-not $basePython) {
    Install-PythonWithWinget
    $basePython = Find-Python
}
if (-not $basePython) {
    throw 'Python wurde installiert, aber noch nicht gefunden. Oeffne ein neues Terminal und starte INSTALL.cmd erneut.'
}
$version = & $basePython -c "import sys; print('.'.join(map(str, sys.version_info[:3]))); raise SystemExit(sys.version_info < (3, 10))"
if ($LASTEXITCODE -ne 0) {
    throw "Python $version ist zu alt. Benoetigt wird Python 3.10 oder neuer."
}

Write-Host "Python ${version}: $basePython" -ForegroundColor Cyan
if ($Force -and (Test-Path -LiteralPath $venvDir)) {
    Remove-Item -LiteralPath $venvDir -Recurse -Force
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host 'Erstelle lokale Python-Umgebung .venv ...' -ForegroundColor Cyan
    Invoke-Checked -Program $basePython -Arguments @('-m', 'venv', $venvDir)
}

Write-Host 'Installiere minimale Abhaengigkeiten ...' -ForegroundColor Cyan
Invoke-Checked -Program $venvPython -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', (Join-Path $projectRoot 'requirements.txt'))
Invoke-Checked -Program $venvPython -Arguments @('-c', 'import numpy; import PIL')
Write-Host 'Python-Abhaengigkeiten: OK' -ForegroundColor Green

try {
    $adb = @(& $venvPython -c "import digiworld_bot as b; print(b.resolve_adb())")
    if ($LASTEXITCODE -eq 0) {
        Write-Host "ADB gefunden: $($adb[-1])" -ForegroundColor Green
    }
} catch {
    Write-Warning 'BlueStacks/ADB wurde noch nicht gefunden. Folge dem BlueStacks-Abschnitt in README.md.'
}

Write-Host ''
Write-Host 'Installation abgeschlossen.' -ForegroundColor Green
Write-Host '1. BlueStacks starten, Portrait 720x1280 einstellen und ADB aktivieren.'
Write-Host '2. Digimon UP oeffnen und DigiWorld betreten.'
Write-Host '3. CHECK.cmd ausfuehren; danach START.cmd.'
