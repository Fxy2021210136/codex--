param(
  [string]$Database = ".\data\app.db",
  [string]$BackupDir = ".\backups"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Test-Path -LiteralPath $Database)) {
  Write-Error "Database not found: $Database. Start and use the app once before creating a backup."
}

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $BackupDir "app-$stamp.db"

$source = Resolve-Path -LiteralPath $Database
$destination = [System.IO.Path]::GetFullPath($target)

Copy-Item -LiteralPath $source.Path -Destination $destination -Force

if (Test-Path -LiteralPath "$($source.Path)-wal") {
  Copy-Item -LiteralPath "$($source.Path)-wal" -Destination "$destination-wal" -Force
}
if (Test-Path -LiteralPath "$($source.Path)-shm") {
  Copy-Item -LiteralPath "$($source.Path)-shm" -Destination "$destination-shm" -Force
}

Write-Host "Backup created: $destination"
