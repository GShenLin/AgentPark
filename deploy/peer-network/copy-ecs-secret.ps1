$credentialPath = Join-Path $PSScriptRoot '..\..\.auth\ecs-credentials.clixml'
$credentials = Import-Clixml -LiteralPath $credentialPath
$secret = [System.Net.NetworkCredential]::new('', $credentials.PortalPassword).Password
Set-Clipboard -Value $secret
$secret = $null
Write-Host 'Portal password copied to clipboard. Paste it only into your AgentPark device-center login.'
