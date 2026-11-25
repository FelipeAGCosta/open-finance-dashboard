<#
.SYNOPSIS
    Registra no Agendador de Tarefas do Windows a tarefa "Findash - Sync".

.DESCRIPTION
    Roda "findash sync" com o Python do .venv, na pasta do projeto,
    todos os dias as 08:00 e as 20:00. Se o computador estiver desligado no horario,
    a tarefa roda assim que possivel (StartWhenAvailable). Usa pythonw.exe para nao
    abrir janela; o log fica em data\logs\findash-AAAA-MM.log.

    A tarefa roda com o seu usuario, apenas quando voce esta logado (nao pede senha
    nem privilegio de administrador). Rodar o script de novo atualiza a tarefa.

.PARAMETER Remover
    Remove a tarefa em vez de registrar.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\agendar_sync.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\agendar_sync.ps1 -Remover
#>
[CmdletBinding()]
param(
    [switch]$Remover
)

$ErrorActionPreference = 'Stop'
$TaskName = 'Findash - Sync'

if ($Remover) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Tarefa '$TaskName' removida."
    } else {
        Write-Host "Tarefa '$TaskName' nao existe."
    }
    return
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Pythonw = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $Pythonw)) {
    throw "Python do ambiente virtual nao encontrado em $Pythonw. Crie o .venv e rode: pip install -e ."
}
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot 'data\logs') | Out-Null

$action = New-ScheduledTaskAction -Execute $Pythonw -Argument '-m findash sync' -WorkingDirectory $ProjectRoot
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At '08:00'),
    (New-ScheduledTaskTrigger -Daily -At '20:00')
)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings -Principal $principal `
    -Description 'Sincroniza o banco local do painel com a Pluggy (findash sync).' -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
$info = $task | Get-ScheduledTaskInfo
Write-Host "Tarefa '$TaskName' registrada."
Write-Host "  Executa : $Pythonw -m findash sync"
Write-Host "  Pasta   : $ProjectRoot"
Write-Host "  Horarios: 08:00 e 20:00 (roda assim que possivel se um horario for perdido)"
Write-Host "  Proxima : $($info.NextRunTime)"
Write-Host "  Logs    : $(Join-Path $ProjectRoot 'data\logs')"
Write-Host "Para testar agora: Start-ScheduledTask -TaskName '$TaskName'"
