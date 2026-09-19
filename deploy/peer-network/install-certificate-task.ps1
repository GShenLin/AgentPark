$ErrorActionPreference = 'Stop'
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (Test-Path -LiteralPath (Join-Path $workspace '.auth\private-ca\root.pem')) {
    throw 'This deployment uses a private CA; do not register public ACME renewal.'
}
$python = Join-Path $workspace '.runtime\acme-venv\Scripts\pythonw.exe'
$script = Join-Path $PSScriptRoot 'renew_ip_certificate.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Install the dedicated ACME Python environment before registering certificate renewal.'
}
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $script + '"') -WorkingDirectory $workspace
$periodic = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 6)
$login = New-ScheduledTaskTrigger -AtLogOn -User $account
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 15)
$task = New-ScheduledTask -Action $action -Trigger @($periodic, $login) -Principal $principal -Settings $settings -Description 'Renew the AgentPark ECS IP certificate using this Windows account. Requires this computer to be powered on, signed in, and online; ECS retains the TLS private key.'
Register-ScheduledTask -TaskName 'AgentPark-ECS-Certificate-Renew' -InputObject $task -Force | Select-Object TaskName, State
