"""Interface do colaborador da livraria: cadastro, chegada de exemplares e venda.

Uso:  python3 clientes/colaborador.py
"""
from sebo_api import chamar, mostrar_livros

ESTOQUE = "SEBO_URL_ESTOQUE"


def listar():
    status, r = chamar(ESTOQUE, {"acao": "listar"})
    mostrar_livros(r.get("livros", [])) if status == 200 else print("Erro:", r.get("erro"))


def cadastrar():
    corpo = {
        "acao": "cadastrar",
        "titulo": input("Título: ").strip(),
        "autor": input("Autor: ").strip(),
        "preco": float(input("Preço (ex. 25.90): ").replace(",", ".") or 0),
        "quantidade": int(input("Exemplares agora (0 se em falta): ") or 0),
    }
    status, r = chamar(ESTOQUE, corpo)
    print(f"Cadastrado: {r['livro']['livro_id']}" if status == 201 else f"Erro: {r.get('erro')}")


def entrada():
    livro_id = input("Código do livro: ").strip()
    qtd = int(input("Quantos exemplares chegaram: ") or 1)
    status, r = chamar(ESTOQUE, {"acao": "entrada", "livro_id": livro_id, "quantidade": qtd})
    if status == 200:
        print(f"Estoque de '{r['livro']['titulo']}' agora: {r['livro']['quantidade']}. "
              "Quem estava esperando será avisado por e-mail.")
    else:
        print("Erro:", r.get("erro"))


def venda():
    livro_id = input("Código do livro: ").strip()
    email = input("E-mail do comprador (opcional): ").strip()
    status, r = chamar(ESTOQUE, {"acao": "venda", "livro_id": livro_id, "email": email})
    if status == 200:
        print(f"Venda registrada ({r['venda']['venda_id']}). Restam {r['livro']['quantidade']}.")
    else:
        print("Erro:", r.get("erro"))


def main():
    acoes = {"1": listar, "2": cadastrar, "3": entrada, "4": venda}
    while True:
        print("\n=== Sebo: colaborador ===\n1) Listar estoque\n2) Cadastrar livro\n"
              "3) Chegada de exemplares\n4) Registrar venda\n0) Sair")
        opcao = input("> ").strip()
        if opcao == "0":
            break
        if opcao in acoes:
            try:
                acoes[opcao]()
            except ValueError as e:
                print("Valor inválido:", e)


if __name__ == "__main__":
    main()
