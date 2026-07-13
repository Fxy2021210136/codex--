param([string]$BaseUrl = "http://127.0.0.1:4173")

$health = Invoke-RestMethod "$BaseUrl/api/health"
if ($health.publicReady) {
  Write-Host "publicReady=true"
  exit 0
}

Write-Host "publicReady=false"
Write-Host "Open 系统设置 -> 上线健康检查，修复红色项目。"
exit 1
