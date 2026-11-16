"""Teste local do fluxo completo, sem AWS: DynamoDB e SNS simulados pelo moto.

Rodar:  uv run --with 'moto[dynamodb,sns]' --with pytest pytest -q tests/

O Stream e a invocação Lambda->Lambda não existem fora da AWS. Aqui o teste monta o
evento do stream à mão (com as imagens antes/depois) e troca o lambda_client.invoke
por uma chamada direta ao handler da sebo_notificar.
"""
import importlib
import json
import os
import sys
from pathlib import Path

import boto3
import pytest
from boto3.dynamodb.types import TypeSerializer
from moto import mock_aws

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "lambdas"))
REGIAO = "us-east-1"


@pytest.fixture
def sebo(monkeypatch):
    with mock_aws():
        for k, v in {"AWS_DEFAULT_REGION": REGIAO, "AWS_ACCESS_KEY_ID": "x",
                     "AWS_SECRET_ACCESS_KEY": "x", "TABELA_LIVROS": "SeboLivros",
                     "TABELA_INTERESSES": "SeboInteresses", "TABELA_VENDAS": "SeboVendas",
                     "FUNCAO_NOTIFICAR": "sebo_notificar"}.items():
            monkeypatch.setenv(k, v)
        ddb = boto3.client("dynamodb", region_name=REGIAO)
        ddb.create_table(TableName="SeboLivros", BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "livro_id", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "livro_id", "KeyType": "HASH"}])
        ddb.create_table(TableName="SeboInteresses", BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "livro_id", "AttributeType": "S"},
                                               {"AttributeName": "email", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "livro_id", "KeyType": "HASH"},
                                    {"AttributeName": "email", "KeyType": "RANGE"}])
        ddb.create_table(TableName="SeboVendas", BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "venda_id", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "venda_id", "KeyType": "HASH"}])
        topico = boto3.client("sns", region_name=REGIAO).create_topic(Name="SeboAvisos")["TopicArn"]
        monkeypatch.setenv("TOPICO_ARN", topico)

        mods = {n: importlib.reload(importlib.import_module(n)) if n in sys.modules
                else importlib.import_module(n)
                for n in ("sebo_estoque", "sebo_pedido", "sebo_chegada", "sebo_notificar")}

        enviados = []

        def invoke(FunctionName, InvocationType, Payload):
            evento = json.loads(Payload)
            r = mods["sebo_notificar"].lambda_handler(evento, None)
            enviados.append({**evento, **r})
            return {"StatusCode": 202}

        monkeypatch.setattr(mods["sebo_pedido"].lambda_client, "invoke", invoke)
        monkeypatch.setattr(mods["sebo_chegada"].lambda_client, "invoke", invoke)
        yield mods, enviados


def http(mod, corpo):
    """Simula a Function URL: body em string, método POST."""
    r = mod.lambda_handler({"body": json.dumps(corpo),
                            "requestContext": {"http": {"method": "POST"}}}, None)
    return r["statusCode"], json.loads(r["body"])


def evento_stream(antes, depois):
    s = TypeSerializer().serialize
    img = lambda d: {k: s(v) for k, v in d.items()}
    dyn = {"NewImage": img(depois)}
    if antes is not None:
        dyn["OldImage"] = img(antes)
    return {"Records": [{"eventName": "MODIFY" if antes else "INSERT", "dynamodb": dyn}]}


def test_disponivel_manda_email_na_hora(sebo):
    m, enviados = sebo
    st, r = http(m["sebo_estoque"], {"acao": "cadastrar", "titulo": "Dom Casmurro",
                                      "autor": "Machado de Assis", "preco": 18, "quantidade": 2})
    assert st == 201
    livro_id = r["livro"]["livro_id"]
    assert livro_id == "dom-casmurro-machado-de-assis"

    st, r = http(m["sebo_pedido"], {"acao": "interesse", "livro_id": livro_id, "email": "Ana@x.com"})
    assert st == 200 and r["disponivel"] is True
    assert [(e["tipo"], e["email"]) for e in enviados] == [("disponivel", "ana@x.com")]


def test_em_falta_espera_e_avisa_na_chegada(sebo):
    m, enviados = sebo
    _, r = http(m["sebo_estoque"], {"acao": "cadastrar", "titulo": "Vidas Secas",
                                     "autor": "Graciliano Ramos", "preco": 15, "quantidade": 0})
    livro = r["livro"]
    for email in ("bia@x.com", "caio@x.com"):
        st, r = http(m["sebo_pedido"], {"acao": "interesse", "livro_id": livro["livro_id"], "email": email})
        assert st == 200 and r["disponivel"] is False
    assert enviados == []

    st, r = http(m["sebo_estoque"], {"acao": "entrada", "livro_id": livro["livro_id"], "quantidade": 1})
    assert st == 200 and r["livro"]["quantidade"] == 1

    antes = {"livro_id": livro["livro_id"], "titulo": "Vidas Secas", "quantidade": 0}
    depois = {**antes, "autor": "Graciliano Ramos", "preco": 15, "quantidade": 1}
    evento = evento_stream(antes, depois)
    assert m["sebo_chegada"].lambda_handler(evento, None) == {"avisados": 2}
    assert sorted(e["email"] for e in enviados) == ["bia@x.com", "caio@x.com"]

    # o stream reentrega o mesmo lote: ninguém recebe e-mail duplicado
    assert m["sebo_chegada"].lambda_handler(evento, None) == {"avisados": 0}
    assert len(enviados) == 2


def test_venda_respeita_estoque(sebo):
    m, _ = sebo
    _, r = http(m["sebo_estoque"], {"acao": "cadastrar", "titulo": "Macunaíma",
                                     "autor": "Mário de Andrade", "preco": 16, "quantidade": 1})
    lid = r["livro"]["livro_id"]
    assert http(m["sebo_estoque"], {"acao": "venda", "livro_id": lid})[0] == 200
    st, r = http(m["sebo_estoque"], {"acao": "venda", "livro_id": lid})
    assert st == 409
    # quantidade 1 -> 0 não é chegada
    antes = {"livro_id": lid, "quantidade": 1}
    assert m["sebo_chegada"].lambda_handler(evento_stream(antes, {**antes, "quantidade": 0}), None) == {"avisados": 0}


def test_busca_ignora_acento_e_caixa(sebo):
    m, _ = sebo
    http(m["sebo_estoque"], {"acao": "cadastrar", "titulo": "Memórias Póstumas de Brás Cubas",
                              "autor": "Machado de Assis", "preco": 20, "quantidade": 0})
    st, r = http(m["sebo_pedido"], {"acao": "buscar", "termo": "MEMORIAS"})
    assert st == 200 and len(r["livros"]) == 1 and r["livros"][0]["disponivel"] is False


def test_erros_de_entrada(sebo):
    m, _ = sebo
    assert http(m["sebo_pedido"], {"acao": "interesse", "livro_id": "nao-existe", "email": "a@x.com"})[0] == 404
    assert http(m["sebo_pedido"], {"acao": "interesse", "livro_id": "x"})[0] == 400
    assert http(m["sebo_estoque"], {"acao": "entrada", "livro_id": "nao-existe", "quantidade": 1})[0] == 404
    assert http(m["sebo_estoque"], {"acao": "voar"})[0] == 400


def test_corrida_livro_chega_durante_o_pedido(sebo, monkeypatch):
    """O livro chega entre a leitura do estoque e a gravação do interesse.

    A sebo_chegada roda nesse intervalo e não vê o cliente (ele ainda não está na tabela).
    Sem a releitura na sebo_pedido, o cliente ficaria "aguardando" para sempre.
    """
    m, enviados = sebo
    _, r = http(m["sebo_estoque"], {"acao": "cadastrar", "titulo": "O Cortiço",
                                     "autor": "Aluísio Azevedo", "preco": 12.5, "quantidade": 0})
    livro = r["livro"]
    original = m["sebo_pedido"].gravar_interesse

    def chegada_no_meio(*args, **kwargs):
        http(m["sebo_estoque"], {"acao": "entrada", "livro_id": livro["livro_id"], "quantidade": 1})
        antes = {"livro_id": livro["livro_id"], "titulo": "O Cortiço", "quantidade": 0}
        avisados = m["sebo_chegada"].lambda_handler(evento_stream(antes, {**antes, "quantidade": 1}), None)
        assert avisados == {"avisados": 0}  # o cliente ainda não estava na tabela
        return original(*args, **kwargs)

    monkeypatch.setattr(m["sebo_pedido"], "gravar_interesse", chegada_no_meio)
    st, r = http(m["sebo_pedido"], {"acao": "interesse", "livro_id": livro["livro_id"], "email": "duda@x.com"})
    assert st == 200 and r["disponivel"] is True and "acabou de chegar" in r["mensagem"]
    assert [(e["tipo"], e["email"]) for e in enviados] == [("chegou", "duda@x.com")]
