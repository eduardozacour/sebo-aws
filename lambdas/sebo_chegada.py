"""Lambda sebo_chegada: avisa quem estava esperando quando um livro volta ao estoque.

Gatilho: DynamoDB Stream da tabela de livros (tipo de visão NEW_AND_OLD_IMAGES).
Para cada registro em que a quantidade passou de 0 (ou não existia) para > 0, busca os
interesses "aguardando" daquele livro, marca cada um como "notificado" e pede à
sebo_notificar o e-mail "seu livro chegou".

O stream entrega cada mudança pelo menos uma vez: se a Lambda falhar no meio, o lote
volta. Por isso a marcação usa ConditionExpression (aguardando -> notificado). Num
reprocessamento, quem já foi marcado não recebe o e-mail de novo.

Variáveis de ambiente: TABELA_INTERESSES, FUNCAO_NOTIFICAR.
"""
import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
interesses = dynamodb.Table(os.environ["TABELA_INTERESSES"])
lambda_client = boto3.client("lambda")
desserializar = TypeDeserializer().deserialize


def lambda_handler(event, context):
    avisados = 0
    for registro in event.get("Records", []):
        if registro.get("eventName") not in ("INSERT", "MODIFY"):
            continue
        imagens = registro["dynamodb"]
        antes = converter(imagens.get("OldImage", {}))
        depois = converter(imagens.get("NewImage", {}))
        qtd_antes = antes.get("quantidade", 0)
        qtd_depois = depois.get("quantidade", 0)
        print(f"{depois.get('livro_id')}: {qtd_antes} -> {qtd_depois}")
        if qtd_antes <= 0 < qtd_depois:
            avisados += avisar_espera(depois)
    print(f"clientes avisados neste lote: {avisados}")
    return {"avisados": avisados}


def avisar_espera(livro):
    livro_id = livro["livro_id"]
    pendentes = []
    consulta = {"KeyConditionExpression": Key("livro_id").eq(livro_id),
                "FilterExpression": Attr("status").eq("aguardando")}
    pagina = interesses.query(**consulta)
    pendentes.extend(pagina["Items"])
    while "LastEvaluatedKey" in pagina:
        pagina = interesses.query(ExclusiveStartKey=pagina["LastEvaluatedKey"], **consulta)
        pendentes.extend(pagina["Items"])

    # ordem de chegada do pedido; todos os que esperavam são avisados (decisão no relatório)
    avisados = 0
    for interesse in sorted(pendentes, key=lambda i: i.get("criado_em", "")):
        if marcar_notificado(livro_id, interesse["email"]):
            notificar("chegou", interesse["email"], livro)
            avisados += 1
    return avisados


def marcar_notificado(livro_id, email):
    try:
        interesses.update_item(
            Key={"livro_id": livro_id, "email": email},
            UpdateExpression="SET #s = :novo, notificado_em = :t",
            ConditionExpression="#s = :aguardando",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":novo": "notificado", ":aguardando": "aguardando",
                                       ":t": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def notificar(tipo, email, livro):
    lambda_client.invoke(
        FunctionName=os.environ["FUNCAO_NOTIFICAR"],
        InvocationType="Event",
        Payload=json.dumps({"tipo": tipo, "email": email, "livro": livro}, default=para_json),
    )


def converter(imagem):
    """Formato do stream ({"N": "3"}) -> Python (Decimal 3)."""
    return {k: desserializar(v) for k, v in imagem.items()}


def para_json(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(type(o))
