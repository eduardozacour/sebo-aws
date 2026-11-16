"""Carga inicial do acervo: cadastra cada linha de um CSV pela Lambda sebo_estoque.

Uso:  python3 clientes/carregar_catalogo.py [dados/livros.csv]
Colunas: titulo,autor,preco,quantidade
"""
import csv
import sys
from pathlib import Path

from sebo_api import chamar

ARQUIVO_PADRAO = Path(__file__).resolve().parent.parent / "dados" / "livros.csv"


def main():
    arquivo = Path(sys.argv[1]) if len(sys.argv) > 1 else ARQUIVO_PADRAO
    with open(arquivo, encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            corpo = {"acao": "cadastrar", "titulo": linha["titulo"], "autor": linha["autor"],
                     "preco": float(linha["preco"]), "quantidade": int(linha["quantidade"])}
            status, r = chamar("SEBO_URL_ESTOQUE", corpo)
            if status == 201:
                print(f"ok   {r['livro']['livro_id']} (estoque {linha['quantidade']})")
            else:
                print(f"erro {linha['titulo']}: {r.get('erro')}")


if __name__ == "__main__":
    main()
