[CmdletBinding()]
param(
    [int]$Steps = 0,
    # Diagnostic PNGs are ON by default: they are the only forensic
    # record of a run, and the whole regression suite (replay_harness.py,
    # tests/test_replay.py) is built from them. A misbehaving run without
    # them cannot be diagnosed or turned into a corpus case. ~57 MB per
    # 200 actions - use -NoDebugShots if disk is tight.
    [switch]$NoDebugShots,
    [switch]$DebugMode,
    [string]$Adb = 'auto',
    [string]$Serial = 'auto'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# The banner switches the console to UTF-8; without telling Python the
# same thing its own accented output comes back mangled ("seria" printed
# as "ser?a" in the run plan).
$env:PYTHONIOENCODING = 'utf-8'
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
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
Show-RobinThorBanner

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Falta el entorno local de Python. Ejecuta primero INSTALL.cmd.'
}
$botScript = Join-Path $projectRoot 'auto_digiworld_batch2.py'
$runsDir = Join-Path $projectRoot 'runs'

function Read-ActionCount {
    param([int]$Default = 100)
    $parsed = 0
    while ($true) {
        $answer = Read-Host "¿Cuántas acciones debe ejecutar el bot? [$Default]"
        if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
        if ([int]::TryParse($answer, [ref]$parsed) -and $parsed -gt 0) { return $parsed }
        Write-Host '  Tiene que ser un entero positivo.' -ForegroundColor Yellow
    }
}

# Reads the HUD once and prints what the planned run costs against what
# is in the bag. The number can be re-typed here and re-costed as many
# times as needed - choosing it beats guessing and then running dry.
function Confirm-RunSize {
    param([int]$Steps)
    while ($true) {
        Write-Host ''
        # Out-Host, not bare output: inside a function every uncaptured
        # line a native command writes joins the function's OUTPUT
        # stream, so the caller's `$runSteps = Confirm-RunSize ...` was
        # collecting the plan text plus the number into an array. The
        # plan then never reached the screen and `if ($runSteps -le 0)`
        # compared strings against 0, which is true often enough that
        # every answer - s, S, Y, n - printed 'Cancelado.'
        & $python $botScript '--steps' $Steps '--plan-only' '--adb' $Adb '--serial' $Serial | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-Host '  No se pudo leer el inventario (¿el juego está en DigiWorld?).' -ForegroundColor Yellow
        }
        Write-Host ''
        $answer = Read-Host "Arrancar con $Steps acciones? [S/n, u otro número]"
        if ([string]::IsNullOrWhiteSpace($answer)) { return $Steps }
        if ($answer -match '^(s|si|sí|y|yes)$') { return $Steps }
        if ($answer -match '^(n|no)$') { return 0 }
        $parsed = 0
        if ([int]::TryParse($answer, [ref]$parsed) -and $parsed -gt 0) {
            $Steps = $parsed
            continue
        }
        Write-Host '  Responde s, n, o un número de acciones.' -ForegroundColor Yellow
    }
}

# The diagnostic PNGs are worth their disk, but not silently: say what
# they cost so the choice to keep them stays informed. Nothing here
# deletes anything.
function Show-RunsDiskUsage {
    if (-not (Test-Path -LiteralPath $runsDir)) { return }
    $files = Get-ChildItem -LiteralPath $runsDir -Recurse -File -ErrorAction SilentlyContinue
    if (-not $files) { return }
    $bytes = ($files | Measure-Object -Property Length -Sum).Sum
    $gb = $bytes / 1GB
    if ($gb -lt 3) { return }
    $count = @(Get-ChildItem -LiteralPath $runsDir -Directory -ErrorAction SilentlyContinue).Count
    Write-Host ("runs\ ocupa {0:N1} GB en {1} corridas guardadas." -f $gb, $count) -ForegroundColor DarkYellow
    Write-Host "  Son la evidencia con la que se diagnostican los fallos; borra las más viejas a mano si necesitas espacio." -ForegroundColor DarkYellow
    Write-Host ''
}
Show-RunsDiskUsage

$nextSteps = $Steps
$lastStatus = 0

do {
    $runSteps = $nextSteps
    $nextSteps = 0
    if ($runSteps -le 0) { $runSteps = Read-ActionCount }
    $runSteps = Confirm-RunSize -Steps $runSteps
    if ($runSteps -le 0) {
        Write-Host 'Cancelado.' -ForegroundColor Yellow
        break
    }

    Set-Location -LiteralPath $projectRoot
    $arguments = @(
        $botScript,
        '--steps', $runSteps,
        '--min-confidence', '0.80',
        '--adb', $Adb,
        '--serial', $Serial,
        '--out', $runsDir
    )
    if (-not $NoDebugShots) { $arguments += '--debug-screenshots' }
    if ($DebugMode) { $arguments += '--verbose' }
    else { $arguments += @('--progress-percent', '2') }

    Write-Host ''
    if ($DebugMode) {
        Write-Host "DEBUG EN MARCHA - estado en cada escaneo y replanificación" -ForegroundColor Cyan
    } else {
        Write-Host "● BOT EN MARCHA ...  ($runSteps acciones)" -ForegroundColor Green
    }
    & $python @arguments
    $lastStatus = $LASTEXITCODE
    if ($lastStatus -eq 0) {
        Write-Host 'Bot finalizado correctamente.' -ForegroundColor Green
    } else {
        Write-Host "Bot finalizado con exit code $lastStatus. No se enviarán más entradas." -ForegroundColor Yellow
    }

    Write-Host ''
    $againAnswer = Read-Host '¿Ejecutar el bot otra vez? [s/N]'
    $again = $againAnswer -match '^(s|si|sí|j|ja|y|yes)$'
} while ($again)

exit $lastStatus