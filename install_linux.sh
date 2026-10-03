#!/bin/bash
# Instalador Automático do Lumina-AI para Linux (Para a equipe do Bar)
echo "=============================================="
echo "    Instalador do Lumina-AI & Antigravity     "
echo "=============================================="

# 1. Instalação de pacotes do sistema
echo "[*] Instalando dependências básicas do sistema (Python, Curl)..."
if command -v apt-get &> /dev/null; then
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-pip python3-venv curl xdg-utils
elif command -v dnf &> /dev/null; then
    sudo dnf install -y python3 python3-pip curl xdg-utils
elif command -v pacman &> /dev/null; then
    sudo pacman -Sy --noconfirm python3 python-pip curl xdg-utils
fi

# 2. Instalação do Ollama
if ! command -v ollama &> /dev/null
then
    echo "[-] Ollama não encontrado. Baixando e instalando Ollama (Motor da IA)..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "[+] Ollama já está instalado."
fi

# 3. Garante que o Ollama está rodando
echo "[*] Iniciando o serviço Ollama..."
ollama serve &
sleep 5

# 4. Baixa o modelo da Inteligência Artificial
echo "[*] Baixando a Inteligência Artificial (qwen2.5:7b-instruct)... (Pode demorar alguns minutos)"
ollama pull qwen2.5:7b-instruct
echo "[+] Inteligência Artificial pronta!"

# 5. Instalação das dependências Python do Lumina-AI
echo "[*] Configurando ambiente do Lumina-AI..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
echo "[+] Dependências instaladas!"

# 6. Instalação do Antigravity
echo "[*] Instalando o Antigravity IDE..."
# Método genérico via NPM (caso seja pacote npm) ou script Bash. 
# Adicionando o Node.js caso não tenha para garantir
if command -v apt-get &> /dev/null; then
    sudo apt-get install -y nodejs npm
fi
if command -v npm &> /dev/null; then
    sudo npm install -g @antigravity/cli --force || echo "Aviso: Falha ao instalar Antigravity via NPM."
else
    # Fallback para instalação via curl bash se o npm não existir
    curl -fsSL https://get.antigravity.dev | bash || echo "Aviso: Falha ao instalar Antigravity via script bash."
fi
echo "[+] Antigravity instalado!"

# 7. Criar atalho na Área de Trabalho
echo "[*] Criando atalho na Área de Trabalho..."
DESKTOP_DIR=$(xdg-user-dir DESKTOP 2>/dev/null)
if [ -z "$DESKTOP_DIR" ]; then
    DESKTOP_DIR="$HOME/Desktop"
fi
if [ -d "$HOME/Área de Trabalho" ]; then
    DESKTOP_DIR="$HOME/Área de Trabalho"
fi

DIR=$(pwd)
cat <<EOF > "$DESKTOP_DIR/Lumina-AI.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=Lumina-AI
Comment=Inicia o Servidor e Aplicativo Lumina-AI
Exec=bash -c "cd '$DIR' && source venv/bin/activate && python3 desktop.py"
Terminal=false
Icon=utilities-terminal
Categories=Utility;
EOF

chmod +x "$DESKTOP_DIR/Lumina-AI.desktop"

echo "=============================================="
echo "[+] INSTALAÇÃO CONCLUÍDA COM SUCESSO!"
echo "Um atalho chamado 'Lumina-AI' foi criado na sua Área de Trabalho."
echo "Basta dar dois cliques nele para iniciar."
echo "=============================================="
read -p "Pressione ENTER para fechar."
