"""Lambda sebo_pedido: o comprador procura um livro e registra interesse.

Exposta por Function URL (POST com corpo JSON):

    {"acao": "buscar", "termo": "machado"}                 # termo vazio lista tudo
    {"acao": "interesse", "livro_id": "...", "email": "..."}

No "interesse":
  - com estoque: grava o interesse como "avisado_disponivel" e pede à sebo_notificar o
    e-mail "venha à livraria efetivar a compra";
  - sem estoque: grava como "aguardando". Quando o livro chegar, a sebo_chegada avisa.

Variáveis de ambiente: TABELA_LIVROS, TABELA_INTERESSES, FUNCAO_NOTIFICAR.
"""
import base64
import json
import os
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
livros = dynamodb.Table(os.environ["TABELA_LIVROS"])
interesses = dynamodb.Table(os.environ["TABELA_INTERESSES"])
lambda_client = boto3.client("lambda")


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
        if acao == "buscar":
            return resposta(200, {"livros": buscar(corpo.get("termo", ""))})
        if acao == "interesse":
            return registrar_interesse(corpo["livro_id"], corpo["email"].strip().lower())
        return resposta(400, {"erro": f"ação inválida: {acao}"})
    except KeyError as e:
        return resposta(400, {"erro": f"parâmetro obrigatório: {e}"})


def buscar(termo):
    alvo = normalizar(termo)
    itens = []
    pagina = livros.scan()
    itens.extend(pagina["Items"])
    while "LastEvaluatedKey" in pagina:
        pagina = livros.scan(ExclusiveStartKey=pagina["LastEvaluatedKey"])
        itens.extend(pagina["Items"])
    achados = [l for l in itens
               if alvo in normalizar(l.get("titulo", "")) or alvo in normalizar(l.get("autor", ""))]
    for l in achados:
        l["disponivel"] = l.get("quantidade", 0) > 0
    return sorted(achados, key=lambda l: l.get("titulo", ""))


def registrar_interesse(livro_id, email):
    if "@" not in email:
        return resposta(400, {"erro": "e-mail inválido"})
    livro = livros.get_item(Key={"livro_id": livro_id}).get("Item")
    if not livro:
        return resposta(404, {"erro": f"livro {livro_id} não encontrado"})

    if livro.get("quantidade", 0) > 0:
        gravar_interesse(livro_id, email, "avisado_disponivel")
        notificar("disponivel", email, livro)
        return resposta(200, {
            "disponivel": True,
            "mensagem": f"'{livro['titulo']}' está disponível. Enviamos um e-mail para {email}.",
        })

    gravar_interesse(livro_id, email, "aguardando")
    # Corrida: o livro pode ter chegado entre o get_item acima e a gravação do interesse,
    # e nesse caso a sebo_chegada já rodou sem ver este cliente. Relê e, se chegou,
    # notifica aqui mesmo. A condição em marcar_notificado garante um e-mail só.
    livro = livros.get_item(Key={"livro_id": livro_id}, ConsistentRead=True).get("Item")
    if livro and livro.get("quantidade", 0) > 0 and marcar_notificado(livro_id, email):
        notificar("chegou", email, livro)
        return resposta(200, {
            "disponivel": True,
            "mensagem": f"'{livro['titulo']}' acabou de chegar. Enviamos um e-mail para {email}.",
        })
    return resposta(200, {
        "disponivel": False,
        "mensagem": f"'{livro['titulo']}' está em falta. Avisaremos {email} quando chegar.",
    })


def gravar_interesse(livro_id, email, status):
    interesses.put_item(Item={
        "livro_id": livro_id,
        "email": email,
        "status": status,
        "criado_em": agora(),
    })


def marcar_notificado(livro_id, email):
    """Passa aguardando -> notificado de forma atômica. False se outro já notificou."""
    try:
        interesses.update_item(
            Key={"livro_id": livro_id, "email": email},
            UpdateExpression="SET #s = :novo, notificado_em = :t",
            ConditionExpression="#s = :aguardando",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":novo": "notificado", ":aguardando": "aguardando", ":t": agora()},
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def notificar(tipo, email, livro):
    """Chamada assíncrona (Event): o comprador não espera o envio do e-mail."""
    lambda_client.invoke(
        FunctionName=os.environ["FUNCAO_NOTIFICAR"],
        InvocationType="Event",
        Payload=json.dumps({"tipo": tipo, "email": email, "livro": livro}, default=para_json),
    )


# ---------- utilitários ----------

def normalizar(texto):
    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()


def metodo(event):
    return event.get("requestContext", {}).get("http", {}).get("method", "POST")


def ler_corpo(event):
    if "body" not in event:
        return event
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise ValueError("corpo nao e JSON valido")


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
