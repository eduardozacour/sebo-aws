# Sebo na AWS: INF1304, 2º trabalho (2026.2)

Aplicação de uma livraria no estilo sebo, sem servidor, rodando no AWS Academy Learner Lab.
O comprador procura um livro e diz que tem interesse. Se houver exemplar, recebe um e-mail
para ir à livraria efetivar a compra. Se não houver, é avisado por e-mail quando o livro chegar.

- 4 funções Lambda (Python): `sebo_pedido`, `sebo_estoque`, `sebo_chegada`, `sebo_notificar`
- 3 tabelas DynamoDB: `SeboLivros` (com Stream), `SeboInteresses`, `SeboVendas`
- 1 tópico SNS (`SeboAvisos`) para os e-mails, com política de filtro por assinante
- 2 interfaces de linha de comando: comprador e colaborador da livraria

Arquitetura, diagramas e decisões estão em [`docs/RELATORIO.md`](docs/RELATORIO.md) e [`docs/diagramas.md`](docs/diagramas.md).

```
lambdas/            código de cada Lambda (um arquivo por função, colado na console)
clientes/           interfaces do comprador e do colaborador, carga do catálogo, teste de concorrência
dados/livros.csv    acervo inicial para a demonstração
eventos-teste/      eventos para o botão Test da console Lambda
tests/              teste local do fluxo (DynamoDB/SNS simulados com moto)
docs/               relatório e diagramas
```

## Instalação (console da AWS, Learner Lab)

Tudo em **us-east-1 (N. Virginia)**. No Learner Lab não dá para criar papéis IAM: toda Lambda usa o papel **LabRole**.

### 0. Abrir o laboratório
1. https://awsacademy.instructure.com, curso **AWS Academy Learner Lab**, Modules, **Launch AWS Academy Learner Lab**.
2. **Start Lab**, esperar a bolinha ficar verde e clicar em **AWS**.
3. A sessão dura 4 h. Os recursos (Lambda, DynamoDB, SNS) continuam existindo entre sessões.

### 1. DynamoDB: tabelas
Console DynamoDB, **Create table** (o resto fica no padrão):

| Tabela | Partition key | Sort key |
|---|---|---|
| `SeboLivros` | `livro_id` (String) | — |
| `SeboInteresses` | `livro_id` (String) | `email` (String) |
| `SeboVendas` | `venda_id` (String) | — |

Depois, em `SeboLivros`, aba **Exports and streams**, **DynamoDB stream details**, **Turn on**, e escolher **New and old images**.

### 2. SNS: tópico e inscrição do cliente
1. Console SNS, **Topics**, **Create topic**, tipo **Standard**, nome `SeboAvisos`. Anotar o **ARN**.
2. No tópico, **Create subscription**, protocolo **Email**, endpoint = e-mail do cliente.
3. Na mesma tela, abrir **Subscription filter policy**, ligar, escolher o escopo **Message attributes** e colar:
   ```json
   { "email": ["cliente@exemplo.com"] }
   ```
   (o mesmo e-mail do endpoint, **em minúsculas**). Sem esse filtro, cada assinante recebe os avisos de todos os clientes.
4. Confirmar a inscrição pelo link que chega no e-mail (olhar o spam).
5. Repetir para cada cliente da demonstração.

### 3. Lambdas
Para cada função: console Lambda, **Create function**, **Author from scratch**, runtime **Python 3.12** (ou o mais novo), **Change default execution role**, **Use an existing role**, **LabRole**.
Colar o conteúdo de `lambdas/<nome>.py` no `lambda_function.py` do editor e clicar em **Deploy**.
Em **Configuration**, **General configuration**, colocar o timeout em **15 s**. Em **Configuration**, **Environment variables**:

| Função | Variáveis de ambiente | Gatilho / acesso |
|---|---|---|
| `sebo_notificar` | `TOPICO_ARN` = ARN do `SeboAvisos`; `NOME_LIVRARIA`; `ENDERECO_LIVRARIA` | invocada pelas outras |
| `sebo_pedido` | `TABELA_LIVROS=SeboLivros`, `TABELA_INTERESSES=SeboInteresses`, `FUNCAO_NOTIFICAR=sebo_notificar` | **Function URL**, auth **NONE** |
| `sebo_estoque` | `TABELA_LIVROS=SeboLivros`, `TABELA_VENDAS=SeboVendas` | **Function URL**, auth **NONE** |
| `sebo_chegada` | `TABELA_INTERESSES=SeboInteresses`, `FUNCAO_NOTIFICAR=sebo_notificar` | **Add trigger**, DynamoDB, `SeboLivros`, batch 10, posição **Latest** |

Function URL: **Configuration**, **Function URL**, **Create function URL**, Auth type **NONE**. Anotar as duas URLs.

### 4. Interfaces (no computador)
Precisa só de Python 3.10 ou mais novo, sem `pip install`.
```bash
cp config.example.env .env      # colar as duas Function URLs
python3 clientes/carregar_catalogo.py   # cadastra o acervo de dados/livros.csv
```

## Operação

**Comprador:** `python3 clientes/comprador.py`
- `1` procura por título ou autor (sem acento e sem diferenciar maiúsculas)
- `2` pede um livro pelo código. Com estoque, o e-mail chega na hora. Sem estoque, o pedido fica aguardando.

**Colaborador:** `python3 clientes/colaborador.py`
- `1` lista o estoque, `2` cadastra livro, `3` registra chegada de exemplares, `4` registra venda

### Roteiro de demonstração
1. Colaborador: listar. *Vidas Secas* está com 0.
2. Comprador (e-mail A): pedir *Dom Casmurro*. O e-mail "disponível" chega.
3. Comprador (e-mail A e e-mail B): pedir *Vidas Secas*. A resposta é "em falta, avisaremos".
4. DynamoDB, `SeboInteresses`: os dois aparecem com `status = aguardando`.
5. Colaborador: chegada de 1 exemplar de *Vidas Secas*. Os dois e-mails "chegou" chegam e o status passa a `notificado`.
6. Colaborador: vender *Vidas Secas* duas vezes. A segunda venda falha por falta de estoque.
7. CloudWatch, Log groups, `/aws/lambda/sebo_chegada`: o log mostra `0 -> 1` e os clientes avisados.
8. Concorrência: `python3 clientes/teste_concorrencia.py`. Dispara 12 vendas ao mesmo tempo sobre 4 exemplares (só 4 passam, o resto recebe 409) e 12 entradas simultâneas (o estoque sobe exatamente 12).

## Teste local (opcional, sem AWS)
```bash
uv run --python 3.12 --with 'moto[dynamodb,sns]' --with pytest pytest -q tests/
```
São 6 testes do fluxo: disponível, em falta e chegada (com reentrega do Stream), venda sem estoque, busca sem acento, erros de entrada e a corrida em que o livro chega durante o pedido.

## Problemas comuns
- **403 na Function URL:** ver em **Configuration**, **Permissions**, **Resource-based policy** se existe permissão pública (`lambda:InvokeFunctionUrl`, e também `lambda:InvokeFunction`). Recriar a Function URL pela console costuma resolver. Se não resolver, rodar no CloudShell (testado na conta do Learner Lab em 16/11/2026, sem a segunda permissão a URL dá 403):
  `aws lambda add-permission --function-name sebo_pedido --statement-id FunctionURLInvokeAllowPublicAccess --action lambda:InvokeFunction --principal '*' --invoked-via-function-url` (e o mesmo para `sebo_estoque`).
- **E-mail não chega:** inscrição não confirmada (enquanto estiver *Pending confirmation*, o SNS não entrega nada), filtro com e-mail diferente (maiúsculas) ou spam. O log de `sebo_notificar` mostra o `MessageId` publicado.
- **`sebo_chegada` não dispara:** stream desligado na `SeboLivros` ou gatilho desativado. Ver a aba **Monitor** da função.
- **`AccessDenied`:** a função não está com o papel LabRole.
