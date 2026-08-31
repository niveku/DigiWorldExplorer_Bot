[CmdletBinding()]
param(
    # What to package. Defaults to the tag matching VERSION, so a release
    # ZIP is built from what was tagged rather than from whatever the
    # working tree happens to hold.
    [string]$Ref = '',
    [string]$OutDir = 'dist',
    # Package the working tree instead of a committed ref. For trying the
    # ZIP out before tagging; a release should never use it.
    [switch]$WorkingTree,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# git archive is the whole point of this script: it packages exactly the
# files git tracks at a ref. Everything the release must not carry
# (.venv, runs/, outputs/, screen_profiles/captures/, local config) is
# already untracked, so there is no exclusion list here to drift out of
# date. The one thing it does need is .gitattributes export-ignore for
# what is tracked but not for players.
& git -C $root rev-parse --is-inside-work-tree *> $null
if ($LASTEXITCODE -ne 0) { throw 'Esto no es un repositorio git.' }

$version = (Get-Content -LiteralPath (Join-Path $root 'VERSION') -Raw).Trim()
if ($Ref -eq '') { $Ref = if ($WorkingTree) { 'HEAD' } else { "v$version" } }

if (-not $WorkingTree) {
    & git -C $root rev-parse --verify --quiet "$Ref^{commit}" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "No existe el ref '$Ref'. Crea el tag primero (git tag -a v$version) o usa -WorkingTree."
    }
    $dirty = & git -C $root status --porcelain
    if ($dirty -and -not $Force) {
        throw 'El árbol tiene cambios sin commitear. Haz commit, o pasa -Force si de verdad quieres empaquetar el ref igual.'
    }
}

$outPath = Join-Path $root $OutDir
if (-not (Test-Path -LiteralPath $outPath)) {
    New-Item -ItemType Directory -Path $outPath | Out-Null
}
$prefix = "DigiWorldExplorer_Bot-v$version"
$zip = Join-Path $outPath "$prefix.zip"
if ((Test-Path -LiteralPath $zip) -and -not $Force) {
    throw "Ya existe $zip. Bórralo o pasa -Force."
}

Write-Host ''
Write-Host "Empaquetando $Ref como $prefix.zip" -ForegroundColor Cyan

if ($WorkingTree) {
    # Tracked files only, working-tree contents. `git stash create` makes
    # a throwaway commit of the tree without touching the stash list.
    $tmp = (& git -C $root stash create)
    if (-not $tmp) { $tmp = 'HEAD' }
    & git -C $root archive --format=zip --prefix="$prefix/" -o $zip $tmp
} else {
    & git -C $root archive --format=zip --prefix="$prefix/" -o $zip $Ref
}
if ($LASTEXITCODE -ne 0) { throw 'git archive falló.' }

# What went in, so the release note can be checked against it rather
# than trusted.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$entries = [System.IO.Compression.ZipFile]::OpenRead($zip)
try {
    $count = $entries.Entries.Count
    $bad = $entries.Entries | Where-Object {
        $_.FullName -match '/(\.venv|runs|outputs)/' -or
        $_.FullName -match '/screen_profiles/captures/'
    }
} finally { $entries.Dispose() }
if ($bad) {
    throw ("El ZIP trae archivos que no debería: " +
           ($bad | Select-Object -First 5 -ExpandProperty FullName) -join ', ')
}

$size = [Math]::Round((Get-Item -LiteralPath $zip).Length / 1MB, 2)
Write-Host "  $count archivos, $size MB" -ForegroundColor Green
Write-Host "  $zip" -ForegroundColor Green
Write-Host ''
Write-Host 'Para subirlo al release:' -ForegroundColor DarkGray
Write-Host "  gh release upload v$version `"$zip`"" -ForegroundColor DarkGray
Write-Host ''
