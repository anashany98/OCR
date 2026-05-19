param(
  [Parameter(Mandatory=$true)]
  [string]$SourceDir,
  [string]$DestinationDir = "data\input",
  [switch]$Hash
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $SourceDir)) {
  throw "No existe SourceDir: $SourceDir"
}
if (-not (Test-Path -LiteralPath $DestinationDir)) {
  throw "No existe DestinationDir: $DestinationDir"
}

function Get-TreeStats($Root) {
  $files = Get-ChildItem -LiteralPath $Root -Recurse -File
  [pscustomobject]@{
    Count = @($files).Count
    Bytes = (@($files) | Measure-Object -Property Length -Sum).Sum
    Files = $files
  }
}

$source = Get-TreeStats $SourceDir
$dest = Get-TreeStats $DestinationDir

if ($source.Count -ne $dest.Count -or $source.Bytes -ne $dest.Bytes) {
  throw "Integridad fallida. Origen: $($source.Count) archivos/$($source.Bytes) bytes. Destino: $($dest.Count) archivos/$($dest.Bytes) bytes."
}

if ($Hash) {
  $sourceRoot = (Resolve-Path -LiteralPath $SourceDir).Path
  $destRoot = (Resolve-Path -LiteralPath $DestinationDir).Path
  foreach ($sourceFile in $source.Files) {
    $relative = $sourceFile.FullName.Substring($sourceRoot.Length).TrimStart("\", "/")
    $destFile = Join-Path $destRoot $relative
    if (-not (Test-Path -LiteralPath $destFile)) {
      throw "Falta archivo destino: $relative"
    }
    $sourceHash = (Get-FileHash -LiteralPath $sourceFile.FullName -Algorithm SHA256).Hash
    $destHash = (Get-FileHash -LiteralPath $destFile -Algorithm SHA256).Hash
    if ($sourceHash -ne $destHash) {
      throw "Hash distinto: $relative"
    }
  }
}

Write-Host "Integridad OK: $($source.Count) archivos, $($source.Bytes) bytes"
