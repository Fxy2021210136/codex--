param(
  [int]$Port = 4173
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
  Write-Error "cloudflared is not installed. Install Cloudflare Tunnel CLI first, then run this script again."
}

Write-Host "Opening a temporary public tunnel to http://127.0.0.1:${Port}"
Write-Host "Keep this window open while sharing the generated https://*.trycloudflare.com URL."
cloudflared tunnel --url "http://127.0.0.1:${Port}"
