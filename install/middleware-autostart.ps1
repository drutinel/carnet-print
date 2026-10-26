# Arranca el middleware (puerto 8787) al iniciar sesión, con una tarea programada del usuario actual.
# Corre en la sesión del usuario (no como servicio) porque el driver/SDK de Entrust imprime con
# el perfil y las preferencias de ese usuario.
#   Instalar:  powershell -ExecutionPolicy Bypass -File install\middleware-autostart.ps1
#   Quitar:    powershell -ExecutionPolicy Bypass -File install\middleware-autostart.ps1 -Remove
param([switch]$Remove, [int]$Port = 8787)
$name = "CarnetMiddleware"
if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tarea $name eliminada."
    exit 0
}
$root = Split-Path $PSScriptRoot -Parent
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\run-windows.ps1`" -Port $Port" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Tarea $name registrada: el middleware arranca al iniciar sesión (http://127.0.0.1:$Port)."
Write-Host "Para arrancarla ya: Start-ScheduledTask -TaskName $name"
