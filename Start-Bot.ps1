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
    throw 'Die lokale Python-Umgebung fehlt. Zuerst INSTALL.cmd ausfuehren.'
}
$nextSteps = $Steps
$lastStatus = 0

do {
    $runSteps = $nextSteps
    $nextSteps = 0
    if ($runSteps -le 0) {
        $answer = Read-Host 'Wie viele Aktionen soll der Bot ausfuehren? [100]'
        if ([string]::IsNullOrWhiteSpace($answer)) {
            $runSteps = 100
        } elseif (-not [int]::TryParse($answer, [ref]$runSteps) -or $runSteps -le 0) {
            throw 'Die Schrittzahl muss eine positive ganze Zahl sein.'
        }
    }

    $defaultInterval = if ($Interval -gt 0) { $Interval } else { 0.50 }
    $runInterval = $defaultInterval
    $intervalAnswer = Read-Host "Pause zwischen Aktionen in Sekunden? [$($defaultInterval.ToString('0.00'))]"
    if (-not [string]::IsNullOrWhiteSpace($intervalAnswer)) {
        $normalizedInterval = $intervalAnswer.Replace(',', '.')
        if (-not [double]::TryParse($normalizedInterval, [Globalization.NumberStyles]::Float,
                [Globalization.CultureInfo]::InvariantCulture, [ref]$runInterval)) {
            throw 'Das Intervall muss eine Zahl sein, zum Beispiel 0,50.'
        }
    }

    $experimentalAnswer = Read-Host 'Experimentelle Einstellungen verwenden? [j/N]'
    $experimental = $experimentalAnswer -match '^(j|ja|y|yes)$'
    $runDebugScreenshots = [bool]$DebugMode

    if ($experimental) {
        if (-not $DebugMode) {
            $debugAnswer = Read-Host 'Diagnosebilder speichern? [j/N]'
            $runDebugScreenshots = $debugAnswer -match '^(j|ja|y|yes)$'
        }
    } elseif ($DebugScreenshots) {
        $runDebugScreenshots = $true
    }

    if ($runInterval -lt 0.35) {
        throw 'Intervalle unter 0,35 Sekunden sind aus Sicherheitsgruenden gesperrt.'
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
        Write-Host "DEBUG LÄUFT - Status bei jedem Scan und jeder Neuplanung" -ForegroundColor Cyan
    } else {
        Write-Host "● BOT LÄUFT ...  ($runSteps Aktionen)" -ForegroundColor Green
    }
    & $python @arguments
    $lastStatus = $LASTEXITCODE
    if ($lastStatus -eq 0) {
        Write-Host 'Bot regulär beendet.' -ForegroundColor Green
    } else {
        Write-Host "Bot mit Exit-Code $lastStatus beendet. Keine weiteren Eingaben werden gesendet." -ForegroundColor Yellow
    }

    Write-Host ''
    $againAnswer = Read-Host 'Bot noch einmal neu ausführen? [j/N]'
    $again = $againAnswer -match '^(j|ja|y|yes)$'
} while ($again)

exit $lastStatus