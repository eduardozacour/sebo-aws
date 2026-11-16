"""Interface do comprador (pessoa física): procura um livro e registra interesse.

Uso:  python3 clientes/comprador.py
O e-mail informado precisa estar inscrito no tópico SNS (feito pela console da AWS, ver README).
"""
from sebo_api import chamar, mostrar_livros

PEDIDO = "SEBO_URL_PEDIDO"


def procurar():
    termo = input("Título ou autor (Enter lista tudo): ").strip()
    status, r = chamar(PEDIDO, {"acao": "buscar", "termo": termo})
    if status != 200:
        print("Erro:", r.get("erro"))
        return []
    livros = r["livros"]
    mostrar_livros(livros)
    return livros


def pedir(livros):
    livro_id = input("Código do livro (entre colchetes acima): ").strip()
    if livros and livro_id not in {l["livro_id"] for l in livros}:
        print("Código fora da última busca; enviando mesmo assim.")
    email = input("Seu e-mail: ").strip()
    status, r = chamar(PEDIDO, {"acao": "interesse", "livro_id": livro_id, "email": email})
    print(r.get("mensagem") or f"Erro ({status}): {r.get('erro')}")


def main():
    livros = []
    while True:
        print("\n=== Sebo: comprador ===\n1) Procurar livro\n2) Quero este livro\n0) Sair")
        opcao = input("> ").strip()
        if opcao == "1":
            livros = procurar()
        elif opcao == "2":
            pedir(livros)
        elif opcao == "0":
            break


if __name__ == "__main__":
    main()
