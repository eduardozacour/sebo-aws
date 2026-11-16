"""Lambda sebo_estoque: operações do colaborador da livraria sobre o estoque.

Exposta por Function URL (POST com corpo JSON). Campo "acao" escolhe a operação:

    {"acao": "listar"}
    {"acao": "cadastrar", "titulo": "...", "autor": "...", "preco": 25.0, "quantidade": 0}
    {"acao": "entrada", "livro_id": "...", "quantidade": 2}   # exemplares que chegaram
    {"acao": "venda", "livro_id": "...", "email": "..."}      # baixa 1 exemplar

A "entrada" só atualiza a tabela. Quem avisa os clientes que estavam esperando é a
Lambda sebo_chegada, disparada pelo DynamoDB Stream da tabela de livros.

Variáveis de ambiente: TABELA_LIVROS, TABELA_VENDAS.
"""
import base64
import json
import os
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
livros = dynamodb.Table(os.environ["TABELA_LIVROS"])
vendas = dynamodb.Table(os.environ["TABELA_VENDAS"])


def lambda_handler(event, context):
    if metodo(event) == "OPTIONS":
        return resposta(200, {"ok": True})
    try:
        corpo = ler_corpo(event)
    except ValueError as e:
        return resposta(400, {"erro": str(e)})

    acao = corpo.get("acao")
    print(f"acao={acao} corpo={corpo}")
    try:
        if acao == "listar":
            return resposta(200, {"livros": listar()})
        if acao == "cadastrar":
            return cadastrar(corpo)
        if acao == "entrada":
            return entrada(corpo)
        if acao == "venda":
            return venda(corpo)
        return resposta(400, {"erro": f"ação inválida: {acao}"})
    except (KeyError, ValueError) as e:
        return resposta(400, {"erro": f"parâmetro inválido: {e}"})


def listar():
    # scan: ok p/ acervo pequeno; se o sebo crescer, GSI
    itens = []
    pagina = livros.scan()
    itens.extend(pagina["Items"])
    while "LastEvaluatedKey" in pagina:
        pagina = livros.scan(ExclusiveStartKey=pagina["LastEvaluatedKey"])
        itens.extend(pagina["Items"])
    return sorted(itens, key=lambda l: l.get("titulo", ""))


def cadastrar(corpo):
    titulo = corpo["titulo"].strip()
    autor = corpo.get("autor", "").strip()
    livro_id = corpo.get("livro_id") or gerar_id(titulo, autor)
    item = {
        "livro_id": livro_id,
        "titulo": titulo,
        "autor": autor,
        "preco": Decimal(str(corpo.get("preco", 0))),
        "quantidade": int(corpo.get("quantidade", 0)),
        "cadastrado_em": agora(),
    }
    try:
        # não sobrescreve livro já cadastrado (para somar exemplares, use "entrada")
        livros.put_item(Item=item, ConditionExpression="attribute_not_exists(livro_id)")
    except ClientError as e:
        if codigo(e) == "ConditionalCheckFailedException":
            return resposta(409, {"erro": f"livro {livro_id} já existe; use a ação entrada"})
        raise
    return resposta(201, {"livro": item})


def entrada(corpo):
    livro_id = corpo["livro_id"]
    qtd = int(corpo["quantidade"])
    if qtd <= 0:
        return resposta(400, {"erro": "quantidade deve ser positiva"})
    try:
        # ADD é atômico: duas entradas simultâneas não se perdem
        r = livros.update_item(
            Key={"livro_id": livro_id},
            UpdateExpression="ADD quantidade :q",
            ConditionExpression="attribute_exists(livro_id)",
            ExpressionAttributeValues={":q": qtd},
            ReturnValues="ALL_NEW",
        )
    except ClientError as e:
        if codigo(e) == "ConditionalCheckFailedException":
            return resposta(404, {"erro": f"livro {livro_id} não cadastrado"})
        raise
    return resposta(200, {"livro": r["Attributes"]})


def venda(corpo):
    livro_id = corpo["livro_id"]
    try:
        # a condição impede vender o mesmo último exemplar duas vezes
        r = livros.update_item(
            Key={"livro_id": livro_id},
            UpdateExpression="SET quantidade = quantidade - :um",
            ConditionExpression="attribute_exists(livro_id) AND quantidade >= :um",
            ExpressionAttributeValues={":um": 1},
            ReturnValues="ALL_NEW",
        )
    except ClientError as e:
        if codigo(e) == "ConditionalCheckFailedException":
            return resposta(409, {"erro": "livro sem estoque ou inexistente"})
        raise
    livro = r["Attributes"]
    registro = {
        "venda_id": str(uuid.uuid4()),
        "livro_id": livro_id,
        "titulo": livro.get("titulo", ""),
        "preco": livro.get("preco", Decimal(0)),
        "email": corpo.get("email", ""),
        "vendido_em": agora(),
    }
    vendas.put_item(Item=registro)
    return resposta(200, {"venda": registro, "livro": livro})


# ---------- utilitários (repetidos em cada Lambda para cada uma caber num arquivo só) ----------

def gerar_id(titulo, autor):
    base = f"{titulo}-{autor}".lower()
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base[:60] or str(uuid.uuid4())


def metodo(event):
    return event.get("requestContext", {}).get("http", {}).get("method", "POST")


def ler_corpo(event):
    """Aceita evento da Function URL (body em string) ou teste da console (dict puro)."""
    if "body" not in event:
        return event
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise ValueError("corpo nao e JSON valido")


def codigo(erro):
    return erro.response.get("Error", {}).get("Code", "")


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def para_json(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(type(o))


def resposta(status, corpo):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(corpo, default=para_json, ensure_ascii=False),
    }
