import subprocess
import sys
import os

# Força a saída do print para UTF-8 no Windows para evitar UnicodeEncodeError (cp1252)
sys.stdout.reconfigure(encoding='utf-8')

plan_path = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity-ide", "brain", "981983cf-1fc7-4a2b-a8f7-58feb8702310", "implementation_plan.md")
with open(plan_path, "r", encoding="utf-8") as f:
    plan_content = f.read()

prompt_text = f"""
Você é o Claude Code (Claude 3.5 Sonnet), um engenheiro de software sênior.
Você é o Claude Code operando sob o poderoso modelo FABLE 5.
Sua missão agora é revisar as capacidades atuais do `engine.py` (especialmente a recente alteração que permite efeitos paralelos, como chase e shape rodando juntos) e a lista de ferramentas em `api.py`.
O usuário relatou que a IA local (Qwen 7B) "não está eficiente" e não moveu os aparelhos quando pedido.
Crie uma LISTA DE ORIENTAÇÕES (regras de System Prompt) brutalmente claras e eficientes para o Qwen.
Foque em:
1. Ensinar a IA a usar `run_shape` para movimentar os moving heads (em paralelo com outras coisas).
2. Como encadear as tools corretamente sem alucinar.
3. Como fazer coreografias complexas (chase + shape + cores).
Escreva a lista final em Markdown.
"""

# Deixando o claude-code usar o modelo padrão (que já é o Sonnet 3.5)
cmd = ["npx.cmd", "@anthropic-ai/claude-code"]

print("Iniciando Claude 3.5 Sonnet Auto-Dev em background para gerar as orientações da IA...")
sys.stdout.flush()

process = subprocess.Popen(
    cmd, 
    stdin=subprocess.PIPE, 
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8"
)

stdout_data, _ = process.communicate(input=prompt_text)

print("\n--- RELATÓRIO DO FABLE 5 ---\n")
if stdout_data:
    # Caso a reconfiguração do stdout falhe em capturar algum char obscuro,
    # fazemos um fallback pra replace
    print(stdout_data.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding))
else:
    print("Nenhum retorno do processo.")
print("\n--- FIM DO RELATÓRIO ---\n")
