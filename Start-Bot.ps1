[CmdletBinding()]
param(
    [int]$Steps = 0,
    [double]$Interval = 0,
    [switch]$DebugScreenshots,
    [switch]$DebugMode,
    [string]$Adb = 'auto',
    [string]$Serial = 'auto'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
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
$nextSteps = $Steps
$lastStatus = 0

do {
    $runSteps = $nextSteps
    $nextSteps = 0
    if ($runSteps -le 0) {
        $answer = Read-Host '¿Cuántas acciones debe ejecutar el bot? [100]'
        if ([string]::IsNullOrWhiteSpace($answer)) {
            $runSteps = 100
        } elseif (-not [int]::TryParse($answer, [ref]$runSteps) -or $runSteps -le 0) {
            throw 'El número de acciones debe ser un entero positivo.'
        }
    }

    $defaultInterval = if ($Interval -gt 0) { $Interval } else { 0.50 }
    $runInterval = $defaultInterval
    $intervalAnswer = Read-Host "¿Pausa entre acciones en segundos? [$($defaultInterval.ToString('0.00'))]"
    if (-not [string]::IsNullOrWhiteSpace($intervalAnswer)) {
        $normalizedInterval = $intervalAnswer.Replace(',', '.')
        if (-not [double]::TryParse($normalizedInterval, [Globalization.NumberStyles]::Float,
                [Globalization.CultureInfo]::InvariantCulture, [ref]$runInterval)) {
            throw 'El intervalo debe ser un número, por ejemplo 0,50.'
        }
    }

    $experimentalAnswer = Read-Host '¿Usar ajustes experimentales? [s/N]'
    $experimental = $experimentalAnswer -match '^(s|si|sí|j|ja|y|yes)$'
    $runDebugScreenshots = [bool]$DebugMode

    if ($experimental) {
        if (-not $DebugMode) {
            $debugAnswer = Read-Host '¿Guardar imágenes de diagnóstico? [s/N]'
            $runDebugScreenshots = $debugAnswer -match '^(s|si|sí|j|ja|y|yes)$'
        }
    } elseif ($DebugScreenshots) {
        $runDebugScreenshots = $true
    }

    if ($runInterval -lt 0.35) {
        throw 'Los intervalos menores a 0,35 segundos están bloqueados por seguridad.'
    }

    Set-Location -LiteralPath $projectRoot
    $arguments = @(
        (Join-Path $projectRoot 'auto_digiworld_batch2.py'),
        '--steps', $runSteps,
        '--interval', $runInterval.ToString([Globalization.CultureInfo]::InvariantCulture),
        '--min-confidence', '0.80',
        '--adb', $Adb,
        '--serial', $Serial,
        '--out', (Join-Path $projectRoot 'runs')
    )
    if ($runDebugScreenshots) { $arguments += '--debug-screenshots' }
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