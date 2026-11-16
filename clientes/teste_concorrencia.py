"""Teste de concorrência contra as Lambdas publicadas (mesmas URLs do .env).

Cadastra um livro de teste e dispara, ao mesmo tempo:
  1. N vendas sobre N/3 exemplares: só N/3 podem passar, o resto recebe 409;
  2. N entradas de 1 exemplar: o estoque tem que subir exatamente N.

Uso:  python3 clientes/teste_concorrencia.py [N]      (N padrão: 12)
O livro de teste fica no acervo (não há ação de apagar); o título leva a hora da execução.
"""
import sys
import threading
import time
from collections import Counter

from sebo_api import chamar

ESTOQUE = "SEBO_URL_ESTOQUE"


def ao_mesmo_tempo(n, corpo):
    """Dispara n POSTs iguais, todos liberados juntos por uma barreira. Devolve os status HTTP."""
    status = []
    barreira = threading.Barrier(n)

    def um():
        barreira.wait()
        status.append(chamar(ESTOQUE, corpo)[0])

    threads = [threading.Thread(target=um) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return Counter(status)


def estoque(livro_id):
    _, r = chamar(ESTOQUE, {"acao": "listar"})
    return next(l["quantidade"] for l in r["livros"] if l["livro_id"] == livro_id)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    exemplares = max(1, n // 3)
    st, r = chamar(ESTOQUE, {"acao": "cadastrar", "titulo": f"Teste de Concorrencia {time.strftime('%H%M%S')}",
                             "autor": "Teste", "preco": 1, "quantidade": exemplares})
    if st != 201:
        sys.exit(f"não consegui cadastrar o livro de teste: {r.get('erro')}")
    livro_id = r["livro"]["livro_id"]
    print(f"Livro de teste: {livro_id} com {exemplares} exemplares\n")

    vendas = ao_mesmo_tempo(n, {"acao": "venda", "livro_id": livro_id})
    final = estoque(livro_id)
    ok = vendas.get(200, 0) == exemplares and vendas.get(409, 0) == n - exemplares and final == 0
    print(f"{n} vendas simultâneas: {vendas.get(200, 0)} aceitas, {vendas.get(409, 0)} recusadas (409); "
          f"estoque final {final}  ->  {'OK' if ok else 'FALHOU'}")

    entradas = ao_mesmo_tempo(n, {"acao": "entrada", "livro_id": livro_id, "quantidade": 1})
    final2 = estoque(livro_id)
    ok2 = entradas.get(200, 0) == n and final2 == n
    print(f"{n} entradas simultâneas de 1: {entradas.get(200, 0)} aceitas; estoque final {final2} "
          f"(esperado {n})  ->  {'OK' if ok2 else 'FALHOU'}")
    sys.exit(0 if ok and ok2 else 1)


if __name__ == "__main__":
    main()
