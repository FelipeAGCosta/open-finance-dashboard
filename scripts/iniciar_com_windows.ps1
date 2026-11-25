<#
.SYNOPSIS
    Registra no Agendador de Tarefas do Windows a tarefa "Findash - Servidor".

.DESCRIPTION
    Ao fazer login no Windows, sobe o servidor local do painel em segundo plano
    (pythonw.exe, sem janela), escutando so em http://127.0.0.1:8765, SEM abrir o navegador.
    Assim o endereco funciona sempre (inclusive o app instalado pelo Edge).
    "findash app" (ou o atalho) detecta o servidor ja rodando e so abre o navegador.

    A tarefa roda com o seu usuario, apenas quando voce esta logado (nao pede senha
    nem privilegio de administrador). Rodar o script de novo atualiza a tarefa.
    Mensagens do servidor ficam em data\logs\servidor.log.

.PARAMETER Remover
    Remove a tarefa (e encerra o servidor iniciado por ela) em vez de registrar.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\iniciar_com_windows.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\iniciar_com_windows.ps1 -Remover
#>
[CmdletBinding()]
param(
    [switch]$Remover
)

$ErrorActionPreference = 'Stop'
$TaskName = 'Findash - Servidor'

if ($Remover) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Tarefa '$TaskName' removida. O servidor deixa de subir no login."
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
if (-not (Test-Path (Join-Path $ProjectRoot 'frontend\dist\index.html'))) {
    Write-Warning "A interface ainda nao foi compilada (frontend\dist). Rode: npm --prefix frontend ci; npm --prefix frontend run build"
}
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot 'data\logs') | Out-Null

$action = New-ScheduledTaskAction -Execute $Pythonw -Argument '-m findash app --sem-navegador' -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description 'Servidor local do painel (so 127.0.0.1:8765), sem abrir o navegador.' -Force | Out-Null

Write-Host "Tarefa '$TaskName' registrada."
Write-Host "  Executa : $Pythonw -m findash app --sem-navegador"
Write-Host "  Quando  : ao fazer login no Windows (sem janela)"
Write-Host "  Endereco: http://127.0.0.1:8765 (so neste computador)"
Write-Host "  Log     : $(Join-Path $ProjectRoot 'data\logs\servidor.log')"
Write-Host "Para iniciar agora, sem reiniciar: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Para remover: powershell -ExecutionPolicy Bypass -File .\scripts\iniciar_com_windows.ps1 -Remover"
