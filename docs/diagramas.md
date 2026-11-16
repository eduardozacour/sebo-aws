# Diagramas

O GitHub renderiza os blocos Mermaid. Para o PDF do relatório, exportar como PNG:
`npx -y @mermaid-js/mermaid-cli -i docs/diagramas.md -o docs/diagrama.png`
(gera um PNG por bloco: `diagrama-1.png`, `diagrama-2.png`, ...). Se reclamar de Chrome, usar o Chromium do sistema: criar `pp.json` com `{"executablePath":"/usr/bin/chromium","args":["--no-sandbox"]}` e passar `-p pp.json`.

## 1. Diagrama em blocos

```mermaid
flowchart LR
    subgraph PC["Computador do usuário"]
        C["comprador.py"]
        K["colaborador.py"]
    end

    subgraph AWS["AWS Academy Learner Lab (us-east-1)"]
        P["λ sebo_pedido<br/>(Function URL)"]
        E["λ sebo_estoque<br/>(Function URL)"]
        H["λ sebo_chegada"]
        N["λ sebo_notificar"]
        L[("DynamoDB<br/>SeboLivros")]
        I[("DynamoDB<br/>SeboInteresses")]
        V[("DynamoDB<br/>SeboVendas")]
        S{{"SNS<br/>SeboAvisos"}}
    end

    M(["E-mail do cliente"])

    C -- "HTTPS POST buscar / interesse" --> P
    K -- "HTTPS POST listar / cadastrar / entrada / venda" --> E
    P -- "lê" --> L
    P -- "grava" --> I
    E -- "lê / grava" --> L
    E -- "grava" --> V
    L -. "DynamoDB Stream<br/>(quantidade 0 → n)" .-> H
    H -- "consulta / marca notificado" --> I
    P -- "invoke assíncrono" --> N
    H -- "invoke assíncrono" --> N
    N -- "publish + atributo email" --> S
    S -- "filtro por assinante" --> M
```

## 2. Diagrama de sequência UML: livro disponível

```mermaid
sequenceDiagram
    autonumber
    actor Comprador
    participant UI as comprador.py
    participant P as λ sebo_pedido
    participant L as SeboLivros
    participant I as SeboInteresses
    participant N as λ sebo_notificar
    participant S as SNS SeboAvisos

    Comprador->>UI: procura "dom casmurro"
    UI->>P: POST {acao: buscar, termo}
    P->>L: scan
    L-->>P: livros
    P-->>UI: lista (quantidade 2)
    Comprador->>UI: quero este livro + e-mail
    UI->>P: POST {acao: interesse, livro_id, email}
    P->>L: get_item(livro_id)
    L-->>P: quantidade = 2
    P->>I: put_item(status = avisado_disponivel)
    P-)N: invoke (Event) {tipo: disponivel}
    P-->>UI: 200 "disponível, veja seu e-mail"
    N->>S: publish(MessageAttributes.email)
    S-)Comprador: e-mail "compareça à livraria"
```

## 3. Diagrama de sequência UML: livro em falta e chegada

```mermaid
sequenceDiagram
    autonumber
    actor Comprador
    actor Colaborador
    participant UI as comprador.py
    participant P as λ sebo_pedido
    participant K as colaborador.py
    participant E as λ sebo_estoque
    participant L as SeboLivros
    participant I as SeboInteresses
    participant H as λ sebo_chegada
    participant N as λ sebo_notificar
    participant S as SNS SeboAvisos

    Comprador->>UI: quero "Vidas Secas" + e-mail
    UI->>P: POST {acao: interesse}
    P->>L: get_item
    L-->>P: quantidade = 0
    P->>I: put_item(status = aguardando)
    P->>L: get_item (ConsistentRead, contra corrida)
    L-->>P: quantidade = 0
    P-->>UI: 200 "em falta, avisaremos"

    Note over Colaborador,L: dias depois
    Colaborador->>K: chegada de 1 exemplar
    K->>E: POST {acao: entrada, quantidade: 1}
    E->>L: update_item ADD quantidade 1
    E-->>K: 200 (quantidade = 1)
    L-)H: Stream MODIFY (Old 0, New 1)
    H->>I: query(livro_id, status = aguardando)
    I-->>H: [comprador]
    H->>I: update_item status = notificado (condição: aguardando)
    H-)N: invoke (Event) {tipo: chegou}
    N->>S: publish(MessageAttributes.email)
    S-)Comprador: e-mail "seu livro chegou"
```
