@echo off
echo Iniciando Lumina-AI Desktop...
:: Verifica se o pywebview esta instalado e instala se faltar
pip show pywebview >nul 2>&1
if %errorlevel% neq 0 (
    echo Instalando biblioteca para a janela Desktop...
    pip install pywebview
)

:: Roda o aplicativo com pythonw para esconder a janela preta do terminal
start pythonw desktop.py
exit
