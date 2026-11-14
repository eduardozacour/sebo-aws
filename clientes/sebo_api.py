"""Chamada HTTP às Function URLs das Lambdas. Só biblioteca padrão (sem pip install).

As URLs vêm de variáveis de ambiente (nada fixo no código):
    SEBO_URL_PEDIDO   -> Function URL da Lambda sebo_pedido   (comprador)
    SEBO_URL_ESTOQUE  -> Function URL da Lambda sebo_estoque  (colaborador)
Elas podem ficar num arquivo .env na raiz do projeto (veja config.example.env).
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def carregar_env():
    """Lê ../.env (formato CHAVE=valor) sem sobrescrever o que já está no ambiente."""
    arquivo = Path(__file__).resolve().parent.parent / ".env"
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip())


def url(variavel):
    carregar_env()
    valor = os.environ.get(variavel)
    if not valor:
        sys.exit(f"Defina {variavel} (Function URL da Lambda) no ambiente ou no arquivo .env")
    return valor


def chamar(variavel, corpo):
    """POST JSON na Function URL. Devolve (status_http, dicionario_da_resposta)."""
    pedido = urllib.request.Request(
        url(variavel),
        data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(pedido, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        texto = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(texto)
        except json.JSONDecodeError:
            return e.code, {"erro": texto}
    except urllib.error.URLError as e:
        return 0, {"erro": f"sem conexao com a Lambda: {e.reason}"}


def mostrar_livros(livros):
    if not livros:
        print("  (nenhum livro)")
        return
    for l in livros:
        preco = f"R$ {float(l.get('preco', 0)):.2f}".replace(".", ",")
        print(f"  [{l['livro_id']}] {l['titulo']} - {l.get('autor', '')} | {preco} | "
              f"estoque: {l.get('quantidade', 0)}")
