@echo off
rem Abre o painel no navegador (servidor local, so neste computador).
rem Atalho na area de trabalho: clique com o botao direito neste arquivo > Enviar para >
rem Area de trabalho (criar atalho). Para fechar o app, feche esta janela.
cd /d "%~dp0.."
if not exist "frontend\dist\index.html" (
  echo Compilando a interface pela primeira vez...
  call npm --prefix frontend ci || goto :erro
  call npm --prefix frontend run build || goto :erro
)
".venv\Scripts\python.exe" -m findash app %*
if errorlevel 1 goto :erro
exit /b 0
:erro
echo.
echo Algo deu errado. Veja a mensagem acima.
pause
exit /b 1
