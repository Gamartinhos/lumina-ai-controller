$WshShell = New-Object -comObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$Shortcut = $WshShell.CreateShortcut("$DesktopPath\Lumina-AI.lnk")

$CurrentDir = Get-Location
$Shortcut.TargetPath = "$CurrentDir\Lumina-Desktop.bat"
$Shortcut.WorkingDirectory = "$CurrentDir"
$Shortcut.Description = "Lumina-AI Controle DMX e Inteligência Artificial"

# Tenta usar o ícone de lâmpada padrão do windows, ou um ícone customizado se houver
$Shortcut.IconLocation = "shell32.dll,22"

$Shortcut.Save()

Write-Host "=============================================="
Write-Host "    ATALHO CRIADO COM SUCESSO!                "
Write-Host "=============================================="
Write-Host "O atalho 'Lumina-AI' foi colocado na sua Área de Trabalho."
Write-Host "Pressione qualquer tecla para sair..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
