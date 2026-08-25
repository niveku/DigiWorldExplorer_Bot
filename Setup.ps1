[CmdletBinding()]
param(
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$venvDir = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
function Show-NivekuBanner {
    try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch {}

    $logo = @(
        '███╗   ██╗ ██╗ ██╗   ██╗ ███████╗ ██╗  ██╗ ██╗   ██╗'
        '████╗  ██║ ██║ ██║   ██║ ██╔════╝ ██║ ██╔╝ ██║   ██║'
        '██╔██╗ ██║ ██║ ██║   ██║ █████╗   █████╔╝  ██║   ██║'
        '██║╚██╗██║ ██║ ╚██╗ ██╔╝ ██╔══╝   ██╔═██╗  ██║   ██║'
        '██║ ╚████║ ██║  ╚████╔╝  ███████╗ ██║  ██╗ ╚██████╔╝'
        '╚═╝  ╚═══╝ ╚═╝   ╚═══╝   ╚══════╝ ╚═╝  ╚═╝  ╚═════╝ '
    )
    $versionPath = Join-Path $PSScriptRoot 'VERSION'
    $version = if (Test-Path -LiteralPath $versionPath) { (Get-Content -LiteralPath $versionPath -Raw).Trim() } else { 'dev' }
    $subtitle = "[ Digimon UP - DigiWorldExplorer_Bot v$version ]"
    $guildLine = '✨ Fork de Niveku · base de RobinTh0r ✨'
    # The box is as wide as its widest LINE, not as its widest logo
    # row: a subtitle or credit line longer than the art used to run
    # straight through the right border.
    $contentWidth = (@($logo) + @($subtitle, $guildLine) |
        ForEach-Object Length | Measure-Object -Maximum).Maximum

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
        throw "Comando fallido (exit code $LASTEXITCODE): $Program $($Arguments -join ' ')"
    }
}

function Install-PythonWithWinget {
    $winget = Get-Command 'winget.exe' -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw 'No se encontró Python 3.10+ y winget no está disponible. Instala Python desde python.org y ejecuta INSTALL.cmd de nuevo.'
    }
    Write-Host 'No se encontró Python 3.10 o superior.' -ForegroundColor Yellow
    $answer = Read-Host '¿Instalar Python 3.12 automáticamente con winget? [S/n]'
    if (-not [string]::IsNullOrWhiteSpace($answer) -and $answer -notmatch '^(s|si|sí|j|ja|y|yes)$') {
        throw 'Instalación cancelada. Instala Python 3.10+ manualmente y ejecuta INSTALL.cmd de nuevo.'
    }
    Write-Host 'Instalando Python 3.12 con winget ...' -ForegroundColor Cyan
    Invoke-Checked -Program $winget.Source -Arguments @('install', '--id', 'Python.Python.3.12', '--exact', '--source', 'winget', '--accept-package-agreements', '--accept-source-agreements')
}
Set-Location -LiteralPath $projectRoot
Show-NivekuBanner
$basePython = Find-Python
if (-not $basePython) {
    Install-PythonWithWinget
    $basePython = Find-Python
}
if (-not $basePython) {
    throw 'Python se instaló pero todavía no se encuentra. Abre una terminal nueva y ejecuta INSTALL.cmd de nuevo.'
}
$version = & $basePython -c "import sys; print('.'.join(map(str, sys.version_info[:3]))); raise SystemExit(sys.version_info < (3, 10))"
if ($LASTEXITCODE -ne 0) {
    throw "Python $version es demasiado viejo. Se necesita Python 3.10 o superior."
}

Write-Host "Python ${version}: $basePython" -ForegroundColor Cyan
if ($Force -and (Test-Path -LiteralPath $venvDir)) {
    Remove-Item -LiteralPath $venvDir -Recurse -Force
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host 'Creando entorno local de Python .venv ...' -ForegroundColor Cyan
    Invoke-Checked -Program $basePython -Arguments @('-m', 'venv', $venvDir)
}

Write-Host 'Instalando dependencias mínimas ...' -ForegroundColor Cyan
Invoke-Checked -Program $venvPython -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', (Join-Path $projectRoot 'requirements.txt'))
Invoke-Checked -Program $venvPython -Arguments @('-c', 'import numpy; import PIL')
Write-Host 'Dependencias de Python: OK' -ForegroundColor Green

try {
    $adb = @(& $venvPython -c "import digiworld_bot as b; print(b.resolve_adb())")
    if ($LASTEXITCODE -eq 0) {
        Write-Host "ADB encontrado: $($adb[-1])" -ForegroundColor Green
    }
} catch {
    Write-Warning 'Todavía no se encontró BlueStacks/ADB. Sigue la sección de BlueStacks en README.md.'
}

Write-Host ''
Write-Host 'Instalación completada.' -ForegroundColor Green
Write-Host '1. Inicia BlueStacks, configura Portrait 720x1280 y activa ADB.'
Write-Host '2. Abre Digimon UP y entra a DigiWorld.'
Write-Host '3. Ejecuta CHECK.cmd; después START.cmd.'
