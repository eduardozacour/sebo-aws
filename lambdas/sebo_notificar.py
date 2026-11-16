"""Lambda sebo_notificar: único ponto do sistema que envia e-mail.

Invocada pelas Lambdas sebo_pedido e sebo_chegada (chamada assíncrona) com:

    {"tipo": "disponivel" | "chegou", "email": "...", "livro": {...}}

Publica no tópico SNS com o atributo de mensagem "email". O cliente se inscreveu no
tópico pela console da AWS (protocolo Email) com uma política de filtro
{"email": ["<o e-mail dele>"]}. Assim o SNS só entrega a cada assinante as mensagens
que têm o e-mail dele no atributo; sem o filtro, todo assinante receberia todo aviso.

Variáveis de ambiente: TOPICO_ARN, NOME_LIVRARIA (opcional), ENDERECO_LIVRARIA (opcional).
"""
import os

import boto3

sns = boto3.client("sns")

TEXTOS = {
    "disponivel": (
        "{livraria}: '{titulo}' está disponível",
        "Olá!\n\nO livro '{titulo}' ({autor}) que você procurou está disponível.\nCompareça à livraria para efetivar a compra:\n{endereco}\n\n"
        "{livraria}",
    ),
    "chegou": (
        "{livraria}: '{titulo}' chegou!",
        "Olá!\n\nVocê pediu para ser avisado quando o livro '{titulo}' ({autor}) chegasse.\n"
        "Ele acabou de chegar. Preço: R$ {preco}\n\nCompareça à livraria para efetivar a compra:\n"
        "{endereco}\n\nOs exemplares são limitados; quem chegar primeiro leva.\n\n{livraria}",
    ),
}


def lambda_handler(event, context):
    # sem DLQ: se o SNS cair, a invocacao falha e o retry do lambda reprocessa
    tipo = event["tipo"]
    email = event["email"]
    livro = event["livro"]
    assunto, corpo = TEXTOS[tipo]
    campos = {
        "livraria": os.environ.get("NOME_LIVRARIA", "Sebo"),
        "endereco": os.environ.get("ENDERECO_LIVRARIA", "(endereço da livraria)"),
        "titulo": livro.get("titulo", ""),
        "autor": livro.get("autor", ""),
    }
    r = sns.publish(
        TopicArn=os.environ["TOPICO_ARN"],
        Subject=assunto.format(**campos)[:100],  # limite do SNS para assunto
        Message=corpo.format(**campos),
        MessageAttributes={"email": {"DataType": "String", "StringValue": email}},
    )
    print(f"e-mail '{tipo}' para {email} sobre {livro.get('livro_id')}: MessageId={r['MessageId']}")
    return {"MessageId": r["MessageId"]}
