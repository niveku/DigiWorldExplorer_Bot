[CmdletBinding()]
param(
    [string]$Loop = '',
    # Everything below is for the rare case. The plain double-click path
    # asks exactly one question, and it is the only one the bot needs.
    [int]$Cycles = 0,
    [switch]$AdoptSession,
    [switch]$Yes,
    [string]$Adb = 'auto',
    [string]$Serial = 'auto'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$loopScript = Join-Path $projectRoot 'screen_loops.py'
$profilesDir = Join-Path $projectRoot 'screen_profiles'

. (Join-Path $PSScriptRoot 'NivekuBanner.ps1')
Show-NivekuBanner

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Falta el entorno local de Python. Ejecuta primero INSTALL.cmd.'
}

# Which loops exist is a question about the disk, not about memory: the
# profiles are what the runner can actually recognize, so they are the menu.
function Select-Loop {
    param([string]$Preset)
    $available = @(Get-ChildItem -LiteralPath $profilesDir -Filter '*.json' -File -ErrorAction SilentlyContinue |
        ForEach-Object { $_.BaseName })
    if (-not $available) {
        throw "No hay perfiles en $profilesDir. Ensena uno primero (ver SCREEN_LOOPS.md)."
    }
    if ($Preset) {
        if ($available -notcontains $Preset) {
            throw "No existe el perfil '$Preset'. Hay: $($available -join ', ')."
        }
        return $Preset
    }
    if ($available.Count -eq 1) { return $available[0] }
    for ($i = 0; $i -lt $available.Count; $i++) {
        Write-Host ("  [{0}] {1}" -f ($i + 1), $available[$i])
    }
    while ($true) {
        $answer = Read-Host "Loop [1-$($available.Count)]"
        $parsed = 0
        if ([int]::TryParse($answer, [ref]$parsed) -and $parsed -ge 1 -and $parsed -le $available.Count) {
            return $available[$parsed - 1]
        }
    }
}

function Invoke-Loop {
    param([string]$Name, [switch]$Simulate, [switch]$Adopt)
    $arguments = @($loopScript, '--adb', $Adb, '--serial', $Serial)
    if ($Simulate) {
        $arguments += @('watch', '--loop', $Name, '--max-frames', '12')
    } else {
        $arguments += @('run', '--loop', $Name)
        if ($Cycles -gt 0) { $arguments += @('--cycles', $Cycles) }
        if ($Adopt) { $arguments += '--adopt-session' }
    }
    Set-Location -LiteralPath $projectRoot
    & $python @arguments
    return $LASTEXITCODE
}

$loopName = Select-Loop -Preset $Loop

# The dry run is not optional and is not a question: it is how a bad
# profile is caught before it spends entries, and it costs ~12 seconds.
Write-Host ''
Write-Host "Comprobando que '$loopName' reconoce lo que hay en pantalla..." -ForegroundColor Cyan
Invoke-Loop -Name $loopName -Simulate | Out-Null

if (-not $Yes) {
    Write-Host ''
    $answer = Read-Host 'Arrancar [S/n]'
    if ($answer -match '^(n|no)$') {
        Write-Host 'Cancelado.' -ForegroundColor Yellow
        exit 0
    }
}

Write-Host ''
Write-Host "LOOP '$loopName' EN MARCHA. Ctrl+C para parar." -ForegroundColor Green
$status = Invoke-Loop -Name $loopName -Adopt:$AdoptSession

# The one situation the operator cannot guess at: a panel left open by the
# previous process blocks the loop, and the fix is a flag. Offer it here
# instead of asking about it upfront on every single launch.
if ($status -eq 3 -and -not $AdoptSession) {
    Write-Host ''
    Write-Host 'El juego quedo en una pantalla que este loop no abrio.' -ForegroundColor Yellow
    $answer = Read-Host 'Cerrarla una vez y seguir [S/n]'
    if ($answer -notmatch '^(n|no)$') {
        Write-Host ''
        $status = Invoke-Loop -Name $loopName -Adopt
    }
}

exit $status
