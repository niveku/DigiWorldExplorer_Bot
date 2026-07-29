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
if ($Steps -le 0) {
    $answer = Read-Host 'Wie viele Aktionen soll der Bot ausfuehren? [100]'
    if ([string]::IsNullOrWhiteSpace($answer)) {
        $Steps = 100
    } elseif (-not [int]::TryParse($answer, [ref]$Steps) -or $Steps -le 0) {
        throw 'Die Schrittzahl muss eine positive ganze Zahl sein.'
    }
}
if ($Interval -le 0) {
    $intervalAnswer = Read-Host 'Pause zwischen Aktionen in Sekunden? [0,50]'
    if ([string]::IsNullOrWhiteSpace($intervalAnswer)) { $Interval = 0.50 }
    else {
        $normalizedInterval = $intervalAnswer.Replace(',', '.')
        if (-not [double]::TryParse($normalizedInterval, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$Interval)) {
            throw 'Das Intervall muss eine Zahl sein, zum Beispiel 0,50.'
        }
    }
}
if ($Interval -lt 0.35) {
    throw 'Intervalle unter 0,35 Sekunden sind aus Sicherheitsgruenden gesperrt.'
}

if ($DebugMode) {
    $DebugScreenshots = $true
} elseif (-not $PSBoundParameters.ContainsKey('DebugScreenshots')) {
    $debugAnswer = Read-Host 'Diagnosebilder fuer jeden Planungsschritt speichern? [j/N]'
    $DebugScreenshots = $debugAnswer -match '^(j|ja|y|yes)$'
}
Write-Host ''
Write-Host "Geplant: $Steps Aktionen | Intervall: $($Interval.ToString('0.00')) s | Debugbilder: $DebugScreenshots" -ForegroundColor Yellow
$confirmation = Read-Host 'Bot jetzt starten? [J/n]'
if (-not [string]::IsNullOrWhiteSpace($confirmation) -and $confirmation -notmatch '^(j|ja|y|yes)$') {
    Write-Host 'Start abgebrochen. Es wurden keine Eingaben gesendet.' -ForegroundColor Yellow
    exit 0
}

Set-Location -LiteralPath $projectRoot
$arguments = @(
    (Join-Path $projectRoot 'auto_digiworld_batch2.py'),
    '--steps', $Steps,
    '--interval', $Interval.ToString([Globalization.CultureInfo]::InvariantCulture),
    '--min-confidence', '0.80',
    '--adb', $Adb,
    '--serial', $Serial,
    '--out', (Join-Path $projectRoot 'runs')
)
if ($DebugScreenshots) {
    $arguments += '--debug-screenshots'
}
if ($DebugMode) {
    $arguments += '--verbose'
} else {
    $arguments += @('--progress-percent', '2')
}

if ($DebugMode) {
    Write-Host "DEBUG LÄUFT - Status bei jedem Scan und jeder Neuplanung" -ForegroundColor Cyan
} else {
    Write-Host "● BOT LÄUFT ...  ($Steps Aktionen)" -ForegroundColor Green
}
& $python @arguments
$status = $LASTEXITCODE
if ($status -eq 0) {
    Write-Host 'Bot regulaer beendet.' -ForegroundColor Green
} else {
    Write-Host "Bot mit Exit-Code $status beendet. Keine weiteren Eingaben werden gesendet." -ForegroundColor Yellow
}
exit $status
