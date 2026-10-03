# Lumina AI Controller

Um servidor local em Python com uma interface para controle de iluminação DMX/Art-Net de palco. Este projeto foi desenhado para ser integrado com agentes IA (como Claude, Gemini, ou ferramentas MCP). Permite o controle de refletores, strobos, lasers e efeitos DMX através de comandos de rede e lógica de shows.

## Funcionalidades
- **DMX/Art-Net Engine**: Controle real e fluido de equipamentos de luz profissionais.
- **Interface Gráfica (GUI)**: UI local para controle manual de intensidades, cores, macros e sequences.
- **IA Ready**: Possui endpoints que podem ser facilmente conectados ao Model Context Protocol (MCP) para que uma IA possa controlar a iluminação do ambiente.
- **Visualizador 3D**: Interface em HTML/JS local para pré-visualizar efeitos em tempo real se um equipamento físico não estiver conectado.

## Estrutura do Projeto
- `engine.py` / `controller.py`: Núcleo de envio de comandos DMX/Art-Net.
- `api.py` / `mcp_server.py`: Interfaces de comunicação externa e integração com MCP.
- `gui.py` / `desktop.py`: Interface de controle manual.
- `/ui`: Painéis de controle web (HTML/JS/CSS).

## Como rodar
1. Crie um ambiente virtual (opcional) e instale as dependências.
2. Execute o servidor:
   ```bash
   python gui.py
   ```
   (Ou use o `Lumina-Desktop.bat` no Windows).
