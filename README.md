# Maravi DI1 Backoffice

Backoffice web para contratos futuros de DI1 (B3) de **uma** carteira. O sistema:

- precifica contratos DI1 (PU ↔ taxa);
- registra operações, aportes, retiradas e preços de referência;
- calcula, **quando o usuário pede**, o caixa, as posições, o valor de mercado, o patrimônio e o
  P&L de cada dia.

O enunciado do desafio está em [docs/desafio_tecnico_di1_1.pdf](docs/desafio_tecnico_di1_1.pdf) e a
especificação completa em [docs/](docs/README.md).

## Como funciona

Três ideias guiam o sistema.

**1. Registrar é diferente de calcular.** Lançar uma operação ou um preço só grava o fato. Nada é
recalculado sozinho: os resultados de cada dia são produzidos por um **processamento** que o
usuário solicita para um intervalo de datas. Assim, o usuário sempre sabe quais números estão
publicados e quando foram calculados ("Processado em dd/mm/aaaa hh:mm").

**2. Três tipos de preço, que nunca se misturam.**

| Preço | Onde aparece | Para que serve |
|---|---|---|
| Calculado | Ao digitar PU ou taxa | O sistema calcula o outro valor; não é guardado como preço |
| De execução | Operação (Lançamentos) | Preço da compra ou venda; nunca vira preço de referência |
| De referência | Ativos → contrato | Marca a posição a mercado na data exata; manual tem prioridade sobre B3 |

Sem preço de referência na data, não há valor de mercado nem P&L daquele ativo naquele dia: o
sistema mostra o campo como indisponível (nunca zero) e cria uma **Pendência**.

**3. Cada dia depende do anterior.** O dia D só é processado se D−1 já estiver processado (ou se
ainda não houver nada antes). Caixa e posições são duas cadeias independentes, que se encontram só
no patrimônio total.

### Regras de cálculo

- **Precificação** (DC/365, dias corridos), com taxa em fração (0,10 = 10% a.a.):
  `PU = 100.000 / (1 + taxa)^(dias_corridos/365)` e o inverso para a taxa. Valores em `Decimal`,
  nunca ponto flutuante.
- **Caixa:** `caixa[D] = caixa[D−1] − Σ(quantidade × PU de execução) + aportes − retiradas`.
- **Posição:** quantidade com sinal (comprado > 0, vendido < 0) e PU médio ponderado. Uma redução
  parcial mantém o PU médio; uma operação que inverte o sinal fecha a posição e abre o restante no
  PU da operação.
- **P&L do dia**, por ativo e depois somado:
  `P&L posições = Q[D−1] × (PU ref. D − PU ref. D−1)` e
  `P&L operações = Σ q × (PU ref. D − PU de execução)`. O P&L acumulado soma os dias.
- **Patrimônio total** = caixa + Σ (quantidade × PU de referência).

## Telas

O menu lateral tem quatro telas.

### Central de Controle

Ponto de partida do dia a dia, com duas abas.

- **Pendências:** o que impede um resultado completo, com o ativo, a data e desde quando afeta.
  - *Preço de referência ausente*: o botão "Definir preço" abre o contrato com a data preenchida.
  - *Contrato vencido com posição aberta*: o botão "Ver lançamentos" mostra as operações do ativo.
- **Processamentos:**
  - **Solicitar processamento:** escolha "Data inicial", "Data final" e o escopo ("Caixa",
    "Posições" ou "Tudo"). Antes de confirmar, o sistema mostra quantos dias serão processados e
    avisa se o dia anterior não estiver processado.
  - **Histórico de processamentos:** cada execução, com período, escopo, progresso ("x / y dias")
    e status: Na fila, Processando, Cancelando, Cancelado, Concluído, Concluído com pendências ou
    Falhou.
  - **Ações de cada execução:**
    - "Ver detalhes";
    - "Cancelar processamento": os dias já concluídos continuam publicados;
    - "Solicitar novo processamento": refaz a partir do dia que falhou ou, numa execução
      cancelada, do primeiro dia não alcançado. Numa execução "Tudo" em que só uma cadeia falhou,
      também é possível refazer apenas essa cadeia (Caixa ou Posições).

As execuções entram numa fila e rodam uma de cada vez, na ordem em que foram pedidas.

### Ativos

Catálogo de produtos (o DI1 já vem cadastrado) e seus contratos.

- **Produto:** lista os contratos com o último PU e a taxa de referência. "Novo contrato" cadastra
  um contrato (código, como DI1F31, e vencimento).
- **Contrato:**
  - gráfico do histórico de preços (PU ou taxa);
  - calendário de preços de referência, dia a dia, onde se registra, corrige ou remove o preço de
    cada data.
- **Registrar preço:** digite o PU **ou** a taxa; o sistema calcula o outro. Registrar um preço não
  recalcula a carteira: é preciso processar de novo.

### Lançamentos

Livro de operações e movimentações de caixa de um período.

- **Novo lançamento:**
  - *Operação*: compra ou venda de um contrato, com data, hora, quantidade e PU **ou** taxa.
  - *Caixa*: aporte ou retirada, com data, hora, valor e uma descrição opcional.
- A tabela mostra data e hora, tipo, ativo, descrição, quantidade, PU, taxa e financeiro (compras e
  retiradas negativas, vendas e aportes positivos).
- Lançamentos não são editados. Um lançamento errado é **excluído** (um ou vários de uma vez) e
  lançado de novo.
- No topo, o caixa de D−1 e D0 com o status de cada um, e o botão "Processar".

### Carteira

Fotografia da carteira numa "Data de avaliação".

- **Status das cadeias:** "Caixa" e "Posições", cada uma com Processado, Processado com
  pendências, Processando, Erro ou Não processado. Um atalho leva ao que falta resolver.
- **Indicadores:**
  - saldo em caixa (com operações, aportes e retiradas do dia);
  - patrimônio total;
  - P&L diário, de posições e de operações.
- **Gráfico do P&L acumulado** a partir de uma data escolhida.
- **Posições:** por contrato, com quantidade, PU médio, taxa média, PU e taxa de referência, valor
  de mercado e P&L. Alguns selos sinalizam problemas:
  - "Sem preço" ou "P&L indisponível": falta o preço de referência.
  - "Preço alterado": o preço mudou depois do processamento; basta reprocessar a data.

## Fluxo de uso

1. **Ativos → DI1 → Novo contrato:** cadastre os contratos.
2. **Lançamentos → Novo lançamento → Caixa → Aporte:** registre o caixa inicial.
3. **Lançamentos → Novo lançamento → Operação:** registre compras e vendas.
4. **Ativos → contrato → Registrar preço:** informe o preço de referência de cada dia,
   fins de semana incluídos.
5. **Central de Controle → Processamentos:** processe o período com escopo "Tudo", a partir do
   primeiro dia com lançamentos.
6. **Pendências:** resolva o que faltar (por exemplo, "Definir preço") e processe de novo a partir
   da data afetada.
7. **Carteira:** escolha a data e veja caixa, posições, patrimônio e P&L.

Mudou o passado (excluiu um lançamento, corrigiu um preço)? Processe de novo a partir daquela data.

**Exemplo do desafio:**
- aporte de 200.000 e compra de 1 contrato a 10% a.a., com vencimento em 365 dias: PU de execução
  90.909,09;
- preço de referência de 10% na mesma data;
- depois de processar, a Carteira mostra caixa de **109.090,91**, valor de mercado de 90.909,09 e
  patrimônio de **200.000,00**.

### Desvios do enunciado

Quatro escolhas deliberadas, registradas na especificação (§15):

- **D1:** o caixa aparece como o indicador "Saldo em caixa", não como uma linha BRL na tabela de
  posições.
- **D2:** o preço de referência vem só da data exata, e o preço de execução nunca é usado como
  referência. Por isso, no exemplo, informa-se também um preço de referência de 10%.
- **D3:** a carteira não é reconstruída na consulta, e sim publicada pelo processamento
  solicitado. Antes dele, a data aparece como "Não processado".
- **D4:** datas futuras são rejeitadas. Os testes rodam o exemplo de 01/01/2027 com relógio fixo,
  e o `make e2e` executa o mesmo exemplo datado de hoje.

## Arquitetura

### Serviços

O Docker Compose sobe tudo:

```text
navegador ──► web (nginx + React) ──► api (FastAPI) ──► PostgreSQL
                                          │ grava pedido + mensagem (outbox)
                                          ▼
                     outbox-relay ──► RabbitMQ ──► worker (processamento)
```

| Serviço | Papel |
|---|---|
| `postgres` | PostgreSQL 16: lançamentos, preços, resultados publicados e a fila de processamentos |
| `rabbitmq` | Transporta o aviso de que há um processamento a executar |
| `migrate` | Aplica as migrações Alembic e encerra |
| `seed` | Cadastra o catálogo (tipo FUTURE, classe e produto DI1) e encerra |
| `api` | API HTTP |
| `demo` | Carrega dados de demonstração pela API e encerra (opcional) |
| `outbox-relay` | Publica no RabbitMQ as mensagens gravadas pela API |
| `worker` | Executa os processamentos, um de cada vez |
| `web` | Interface (build do React servido por nginx), que repassa `/api` para a API |

### Processamento

1. **Pedido:** a API grava o pedido como "Na fila" e, na mesma transação, uma mensagem no *outbox*
   (padrão *transactional outbox*). Pedido e mensagem são gravados juntos, ou nenhum dos dois.
2. **Publicação:** o `outbox-relay` publica a mensagem no RabbitMQ.
3. **Execução:** a cada mensagem, o `worker` pega o pedido **mais antigo** da fila e o executa dia
   a dia. Cada dia é publicado na sua própria transação.

O PostgreSQL é a fonte da verdade da fila: ordem e status ficam no banco, e o RabbitMQ só avisa
que há trabalho. Uma varredura periódica no worker cobre uma mensagem perdida, e uma mensagem
duplicada não causa efeito. O cancelamento é cooperativo: o dia em andamento termina e os
seguintes não são tocados. Se o worker cair, ele retoma a execução interrompida ao reiniciar.

### Backend: monólito modular

Python 3.12, FastAPI, SQLAlchemy 2 assíncrono, Alembic e aio-pika. O código fica em
`backend/src/di1/`, organizado por módulos de negócio:

| Módulo | Responsabilidade |
|---|---|
| `asset` | Catálogo: produtos e contratos (código, vencimento) |
| `pricing` | Cálculo PU ↔ taxa (puro, sem banco) |
| `ledger` | Operações e movimentações de caixa |
| `prices` | Preços de referência (manual e B3) |
| `portfolio` | Contabilidade diária: caixa, posições, PU médio, valor de mercado |
| `pnl` | P&L de posições e de operações, por ativo e da carteira |
| `processing` | Pedidos de processamento, fila, execução dia a dia, status e pendências |

Todo módulo segue as mesmas camadas:

```text
modules/<módulo>/
  public.py         contrato do módulo: os únicos DTOs e serviços que outros módulos usam
  domain/           regras de negócio puras: sem banco, rede, relógio do sistema ou log
  application/      serviços que orquestram um caso de uso numa unidade de trabalho
  infrastructure/   persistência; o SQL fica em infrastructure/persistence/queries
  presentation/     adaptadores HTTP (rotas e esquemas) e de mensageria
```

Fora dos módulos:

- `platform/`: infraestrutura técnica compartilhada (configuração, banco e *Unit of Work*,
  RabbitMQ, outbox, observabilidade).
- `composition/`: monta a aplicação e liga os módulos.
- `workers/`: ponto de entrada do worker e do outbox-relay.
- `shared/`: utilitários comuns (decimais, datas, paginação, erros).

Testes de arquitetura garantem essas fronteiras:

- um módulo só acessa outro pelo `public.py`;
- as camadas dependem apenas para dentro, e o domínio não faz I/O;
- SQL só existe na infraestrutura dos módulos, em `platform/` e na montagem da aplicação;
- FastAPI só aparece nos adaptadores HTTP, nos provedores de dependência e em `composition/`.

Valores monetários, PUs e taxas são `Decimal` em Python, `NUMERIC` no banco e strings no JSON.

### Frontend

React com TypeScript, Mantine, TanStack Query e React Router, em `frontend/src/`, organizado por
tela em `features/` (processing, assets, ledger, portfolio). O frontend só formata: todo cálculo
vem da API. Os tipos da API são gerados a partir do OpenAPI do backend (`npm run gen:api`).

### Testes

- **Unitários:** domínio e serviços.
- **Integração:** em PostgreSQL real, nunca SQLite.
- **Aceitação:** os casos da especificação, inclusive o exemplo do desafio com data fixa.
- **Arquitetura:** fronteiras entre módulos.
- **Frontend:** componentes, com Vitest e Testing Library.
- **Ponta a ponta:** `make e2e` sobe a pilha inteira e roda o exemplo do desafio pela API.

## Instalação e execução

### Requisitos

- Para rodar a aplicação: Docker com Docker Compose.
- Para desenvolver e rodar os testes: também [uv](https://docs.astral.sh/uv/), Node 24 LTS com
  npm e GNU Make.

### Subir a aplicação

```bash
cp .env.example .env          # opcional: todos os valores têm padrão
docker compose up --build -d
```

Abra **http://localhost:8080**.

Na primeira subida, o serviço `demo` carrega duas semanas de dados de exemplo:
- três contratos DI1;
- aportes, uma retirada e operações;
- preços de referência diários, com uma lacuna proposital.

Nada vem processado. Para ver a carteira:
1. Em Central de Controle → Processamentos, processe com escopo "Tudo" de 14 dias atrás até hoje.
2. A execução termina "Concluído com pendências", por causa da lacuna de preço.
3. Os resultados aparecem na Carteira.

Para começar com a base vazia, use `DI1_DEMO=0` no `.env`.

| Endereço padrão | Serviço |
|---|---|
| http://localhost:8080 | Interface |
| http://127.0.0.1:8000 | API (`/health`, `/api/...`) |
| 127.0.0.1:5432 | PostgreSQL (usuário, senha e banco `di1`) |
| http://127.0.0.1:15672 | Painel do RabbitMQ (usuário e senha `di1`) |

**Portas:** se alguma estiver ocupada (por exemplo, um PostgreSQL local na 5432), troque-a no
`.env`: `DI1_WEB_PORT`, `DI1_API_PORT`, `DI1_DB_PORT` e `DI1_RABBITMQ_MANAGEMENT_PORT`.

```bash
docker compose down       # para a pilha
docker compose down -v    # para e apaga os dados
```

### Desenvolvimento e testes

```bash
make install   # dependências do backend (uv) e do frontend (npm)
make lint      # ruff, mypy, eslint, tsc e prettier
make test      # testes do backend em um PostgreSQL temporário (Docker) e do frontend
make e2e       # pilha completa temporária executando o exemplo do desafio
```

Para desenvolver a interface com recarga automática, suba a pilha e rode
`cd frontend && npm run dev` (http://localhost:5173).

## Documentação

- [docs/development.md](docs/development.md): guia técnico (em inglês), com configuração
  detalhada, decisões de processamento, dados de demonstração, interpretações e desvios do
  enunciado, e limitações conhecidas.
- [docs/maravi_business_specification.md](docs/maravi_business_specification.md): especificação
  de negócio.
- [docs/schema.md](docs/schema.md) e [docs/interfaces.md](docs/interfaces.md): banco de dados e
  contratos entre módulos.
- [docs/open-questions.md](docs/open-questions.md): todas as decisões tomadas durante o projeto.
