# Maravi DI1 Backoffice — Especificação funcional e decisões de negócio

**Status:** documento de referência das decisões acordadas até 18/10/2026.  
**Público-alvo:** desenvolvimento, revisão de regras financeiras, frontend, testes e agentes de IA.  
**Propósito:** descrever **o que a aplicação faz**, **como deve se comportar** e **quais decisões estão fechadas**, independentemente da organização interna do código.

> **Hierarquia de fontes:** o enunciado do desafio técnico define os requisitos mínimos. Este documento registra as decisões de produto e extensões aprovadas nas conversas posteriores. Em caso de conflito com documentos antigos, prevalecem as decisões explícitas mais recentes; discrepâncias com o enunciado devem ser registradas e não ocultadas. `schema.md`, `schema.sql`, `interfaces.md` e o plano de implementação detalham a execução técnica. **Nomes exatos de endpoints e tipos SQL não são requisitos de negócio.**

## 1. Objetivo e escopo

A Maravi DI1 Backoffice é uma aplicação web para cadastrar instrumentos financeiros, calcular PU ou taxa de contratos DI1, registrar operações e movimentações de caixa, informar preços de referência e consultar a composição e o desempenho histórico de **uma única carteira**.

- Há **exatamente uma carteira** no escopo atual; não existe seleção de carteira nem necessidade de `portfolio_id` nas entidades.
- Usuários registram operações e preços; o sistema calcula e publica posições e métricas históricas **somente após um processamento solicitado explicitamente**.
- A aplicação deve ser reproduzível, auditável e transparente quando os dados estão ausentes, incompletos ou desatualizados.
- Não são necessárias autenticação/autorização nem múltiplas carteiras para o desafio atual.
- Todo o conteúdo visível ao usuário (rótulos, mensagens, ações, datas) é em **português brasileiro**. Identificadores internos, APIs e código podem ser em inglês.
- O escopo financeiro é uma **simulação simplificada**, e não a implementação fiel dos ajustes diários, margens e liquidação de futuros DI1 na B3.

## 2. Vocabulário e módulos de negócio

| Módulo | Responsabilidade | Limite importante |
|---|---|---|
| `asset` | Classificar e cadastrar produtos e instrumentos; especificações de futuros | Não calcula P&L nem guarda operações |
| `pricing` | Calcular PU ↔ taxa com calculadoras específicas por instrumento | Cálculo puro; não persiste automaticamente preços nem publica mensagens |
| `ledger` | Registrar trades, seus preços de execução e aportes/retiradas; preservar histórico | Preço de execução **não é** preço de referência |
| `prices` | Gerenciar observações de referência manuais e B3, origens e seleção de preço preferencial | Não altera trades nem registra preços de execução |
| `portfolio` | Reconstruir posições e estado de caixa por dia; manter posições e métricas calculadas; servir consultas consolidadas | Não redefine as regras dos calculadores de P&L |
| `pnl` | Calcular P&L por ativo e agregá-lo para a carteira | Aportes/retiradas não são P&L; o módulo inicialmente não precisa persistir tabelas próprias |
| `processing` | Validar pedidos, enfileirar, executar, cancelar e publicar processamentos; administrar o status de cada data, pendências e invalidação | Alterar entrada **não** dispara processamento automaticamente |

A arquitetura é um monólito modular: módulos se comunicam por contratos públicos. Consultas para telas podem compor dados entre módulos em um read model, sem quebrar a propriedade de escrita de cada módulo.

## 3. Instrumentos e cadastro de ativos

A classificação aprovada é hierárquica:

1. **Tipo de instrumento:** por exemplo, `FUTURE`.
2. **Classe de ativo:** por exemplo, `INTEREST_RATE_FUTURE`, vinculada ao tipo `FUTURE`.
3. **Produto:** por exemplo, `DI1`.
4. **Instrumento/contrato:** por exemplo, `DI1F27`, com vencimento próprio.

A estrutura persistente do módulo Asset utiliza `instrument_types`, `asset_classes`, `products`, `futures` e `instruments`.

- `asset.futures` guarda **propriedades compartilhadas do produto futuro**: valor de referência/face value, multiplicador, modalidade ou descrição de liquidação e outras convenções específicas.
- `asset.instruments` guarda o **vencimento de cada contrato** e sua vinculação ao produto.
- Não duplicar automaticamente especificações de DI1 em todos os vencimentos.
- A estrutura admite futuramente mais classes e produtos, mas a implementação do desafio deve priorizar DI1.
- Integridade das classificações e unicidade de identificadores/códigos deve ser validada; preferir unicidade insensível a maiúsculas/minúsculas.
- **Multiplicador (decidido, OQ-2):** `contract_multiplier` permanece no cadastro, mas **não é aplicado** nos cálculos atuais (DI1 = 1; as fórmulas usam o PU diretamente). Quando for usado, os cálculos ficarão em um módulo calculador futuro.
- **Vencimento:** ver §7.4.

## 4. Cálculo de preços e taxas

### 4.1 Convenção de cálculo

Foi decidida a convenção simplificada **DC/365**, usando dias **corridos**, incluindo finais de semana e feriados:

```text
PU = 100000 / (1 + taxa) ^ (dias_corridos / 365)
taxa = (100000 / PU) ^ (365 / dias_corridos) - 1
```

- `taxa` é fração decimal anual: `0.10` significa 10% a.a.
- `dias_corridos` decorre da data de referência do cálculo e do vencimento do contrato.
- O numerador é o `face_value` do cadastro de futuros: 100.000 para o DI1, a base especificada pelo desafio.
- A aplicação aceita taxa **ou** PU e calcula o valor faltante; não deve tratar ambos como entradas independentes contraditórias.
- **Precisão (decidido, OQ-3):** cálculos em `Decimal` com contexto de 34 dígitos e arredondamento `ROUND_HALF_UP`. PU calculado é armazenado com 10 casas decimais e taxa calculada com 12. PU digitado com mais de 10 casas ou taxa digitada com mais de 12 é **rejeitado**, nunca arredondado. Valores monetários são armazenados exatos e arredondados a 2 casas apenas na exibição.
- Limites de valores: apenas os do schema (taxa > −1, PU > 0, quantidade ≠ 0, valor > 0) (OQ-14).
- Uma calculadora pode produzir uma prévia sem salvar nada. A interface atual não oferece prévia nem calculadora avulsa: o valor complementar é calculado ao salvar e exibido depois (OQ-19).
- O mesmo motor de cálculo pode ser usado ao registrar uma operação ou quando o fluxo de preço de referência realmente precisar derivar o valor complementar.

### 4.2 Três valores diferentes que não podem ser confundidos

1. **PU/taxa calculados:** resultado matemático de uma calculadora; não implica persistência.
2. **PU/taxa de execução:** dados do negócio fechado, pertencentes ao registro imutável de trade no Ledger.
3. **PU/taxa de referência:** observação para determinada data, pertencente a Prices e usada na avaliação e no P&L.

O PriceService é o ponto único de gerenciamento dos **preços de referência**, não de qualquer preço calculado nem dos trades.

## 5. Preços de referência (`prices`)

- A observação identifica **instrumento, data de referência, fonte e valores**; registra também qual entrada foi autoritativa (PU ou taxa), quando pertinente.
- Fontes atuais planejadas: **`MANUAL`** e **`B3`**.
- Existe **uma única observação por instrumento, data e fonte**; não há revisões (OQ-25). Adicionar um preço para um instrumento, data e fonte que já tem um **apaga o atual** e grava o novo (OQ-26); é assim que **Corrigir** funciona na tela. **Remover** apaga a observação.
- **Prioridade de seleção para avaliação:** `MANUAL` primeiro, `B3` em segundo. Se nenhuma existir na data exata, o preço exigido está ausente.
- Não utilizar automaticamente o último PU disponível antes da data solicitada. **Não há carry-forward**, nem aos sábados/domingos.
- O preço de referência efetivamente utilizado no cálculo é rastreável pela linha publicada: `position_metrics` guarda o **PU de referência usado e sua fonte** (MANUAL ou B3) (OQ-25), para não misturar valor corrigido com P&L antigo.
- A remoção da observação manual faz a fonte B3, se existir, passar a prevalecer para a mesma data.
- Inserir, corrigir ou remover preço marca a cadeia de posições como **desatualizada** da sua data em diante (§10.4, OQ-23); **não altera trades e nem recalcula as quantidades**.
- Invalidação ocorre junto da gravação da observação; nenhuma atualização de preço inicia um job de P&L automaticamente.
- Importação massiva CSV e coleta de preços B3 são **TODOs futuros, após o núcleo estar concluído**. Quando introduzidas, devem reutilizar o PriceService; uma via assíncrona pode integrar via RabbitMQ.

## 6. Lançamentos (`ledger`)

Operações e movimentações de caixa são uma única entidade, o **lançamento** (OQ-24): cada lançamento é uma **operação** ou uma **movimentação de caixa**, com data e **hora obrigatórias** e uma sequência (`seq`) comum aos dois tipos. A ordem de processamento é `(data, hora, seq)` entre os dois tipos.

- Registro financeiro imutável: **não há edição direta** de lançamentos. Exclusão lógica (soft delete) **sem motivo**; a exclusão múltipla é confirmada, ocorre em uma única transação (tudo ou nada) e os lançamentos excluídos juntos compartilham um identificador de lote para auditoria (OQ-24).
- O efeito de caixa de uma operação não é armazenado: é calculado na leitura como −quantidade assinada × PU de execução (§7.3).

### 6.1 Operações

Uma compra/venda inclui contrato, direção, quantidade, data/hora efetiva e PU **ou** taxa de execução. O sistema pode calcular a representação faltante através de Pricing.

- **Data e hora são obrigatórias** (OQ-13, OQ-24): hora em horário local de São Paulo; o formulário sugere a hora atual.
- **Datas aceitas** (OQ-7, OQ-14): qualquer data corrida, inclusive fins de semana e feriados; nada datado **após hoje** (America/Sao_Paulo) é aceito, para operações, movimentações e preços. Vencimentos são isentos.
- **Vencimento** (OQ-1): uma operação pode ser datada até a data de vencimento, inclusive; nessa data (dias corridos = 0) o PU é digitado e a taxa é armazenada como `0`. Operações datadas após o vencimento são rejeitadas.

- Cada operação é preservada individualmente, mesmo quando várias operações atingem o mesmo contrato no mesmo dia.
- A ordem de processamento é cronológica: `(data, hora, seq)`; não somar ou compensar todas as operações do dia antes de atualizar custos médios.
- `created_at` (instante de cadastro) é diferente do momento efetivo da operação.
- Incluir ou excluir uma operação marca as cadeias de caixa **e** de posições como desatualizadas da sua data em diante (§10.4, OQ-23).

### 6.2 Movimentações de caixa

- Dois tipos: **aporte** e **retirada**, cada qual com valor positivo informado e data e hora efetivas (hora obrigatória, OQ-24). O valor é armazenado com sinal: positivo para aporte, negativo para retirada, nunca zero.
- Também são registros auditáveis, sem edição de valores depois do lançamento.
- Incluir ou excluir uma movimentação marca **somente** a cadeia de caixa como desatualizada da sua data em diante (§10.4).
- Aportes/retiradas modificam **saldo de caixa** e AUM, **não** P&L.
- Não há obrigação de modelar BRL como um instrumento negociável para exibir caixa na carteira.

## 7. Contabilidade diária da carteira (`portfolio`)

### 7.1 Estado inicial e calendário

- Estado inicial antes do primeiro lançamento relevante: **caixa zero, posição zero, P&L zero**.
- Calcula-se **todos os dias corridos** do intervalo do processamento, inclusive fins de semana e feriados.
- Há **duas cadeias diárias independentes** (OQ-21): a de **caixa** (§7.3) e a de **posições** (§7.2, com avaliação e P&L, §8). Ambas leem os mesmos fatos do Ledger e nunca a saída uma da outra; só se encontram no AUM (§8.2).
- O cálculo do dia de cada cadeia usa o estado anterior válido **da própria cadeia** e aplica sequencialmente os fatos daquele dia.
- A posição de abertura de D é a de fechamento de D−1, levada adiante quando o usuário processa D; não há processo automático à meia-noite (OQ-22). O usuário processa D0 quando quiser (§10.1).
- O resultado publicado de D−1 é o ponto de partida de D. Quando o status de D−1 da cadeia não é **Atualizado** nem **Atualizado com pendências**, nem é o estado zero, D é publicado como **Desatualizado** (§10.4, OQ-23).

### 7.2 Posição e custo médio

Uma posição diária tem, por ativo, quantidade assinada de fechamento: positivo = comprado, negativo = vendido, zero = sem posição.

- Ao aumentar posição no mesmo sentido, o PU médio de entrada é recalculado pela ponderação das quantidades; a **taxa média de entrada é controlada separadamente** conforme sua própria ponderação, não derivada automaticamente do PU médio.
- Reduzir parcialmente uma posição **não modifica** o custo médio dos contratos remanescentes sob a convenção de custo médio adotada.
- Fechar integralmente leva a posição a zero.
- Se uma operação **atravessa zero**, o cálculo fecha a posição antiga e abre a quantidade residual no sentido oposto **ao PU/taxa da operação reversora**. O Ledger mantém a operação original indivisa; não cria trades artificiais.
- Calcular os efeitos financeiros do fechamento e da abertura sem contar P&L duas vezes.
- Custos médios são também estado necessário para o próximo dia: devem ser calculáveis/persistíveis mesmo quando o preço de referência está ausente.

### 7.3 Caixa simplificado

Sob o modelo simplificado acordado (sem ajustes diários reais de futuros), o caixa é uma cadeia própria, **pré-calculada** e publicada em `portfolio.cash_balances` (OQ-21):

```text
cash[D] = cash[D-1]
          - Σ (signed_trade_quantity × execution_PU)
          + deposits[D] - withdrawals[D]
```

- `signed_trade_quantity`: compras positivas; vendas negativas.
- A cadeia de caixa lê operações e movimentações diretamente do Ledger; não depende de posições, custo médio nem preços de referência. Cada dia publica o saldo e seus componentes: fluxo das operações, aportes e retiradas.
- O caixa de uma compra diminui, o de uma venda aumenta, independentemente do resultado de mercado.
- **P&L diário de marcação a mercado não é creditado/debitado diretamente ao caixa.**
- A aplicação **não** afirma reproduzir o fluxo de ajuste e garantias de um contrato futuro DI1 real.
- O multiplicador não é aplicado (OQ-2); não alterar a fórmula simplificada implicitamente.

### 7.4 Vencimento (decidido, OQ-1)

- **Não há liquidação automática.** O usuário encerra a posição com uma operação normal, a qualquer PU, que pode ser datada no próprio vencimento (taxa armazenada como `0`, pois dias corridos = 0).
- O preço de referência da data de vencimento é informado pelo usuário, como em qualquer outro dia; sem ele, os resultados dependentes ficam `null`, com pendência.
- **Após o vencimento**, o valor do contrato é 0 por definição (PU de referência = 0; nenhum preço é exigido ou aceito). Operações e preços datados após o vencimento são rejeitados.
- Uma posição deixada aberta após o vencimento gera `position_pnl = Q × (0 − PU_vencimento)` e a pendência **"contrato vencido com posição aberta"**.

## 8. P&L (`pnl`) e valuation

### 8.1 Atribuição por ativo, depois agregação

Calcular primeiro cada ativo e **só depois** agregar para a carteira. Para ativo `a` no dia `D`:

```text
position_pnl[a,D] = Q[a,D-1] × (reference_PU[a,D] - reference_PU[a,D-1])
trades_pnl[a,D]   = Σ trades_i_in_D (signed_qty_i × (reference_PU[a,D] - execution_PU_i))
daily_pnl[a,D]    = position_pnl[a,D] + trades_pnl[a,D]

portfolio_position_pnl[D] = Σ position_pnl[a,D]
portfolio_trades_pnl[D]   = Σ trades_pnl[a,D]
portfolio_daily_pnl[D]    = Σ daily_pnl[a,D]
portfolio_cumulative_pnl[D] = cumulative_pnl[D-1] + portfolio_daily_pnl[D]
```

- A base `Q[a,D-1]` é a posição de fechamento **do dia anterior**.
- Aporte e retirada são excluídos dessas fórmulas.
- Esse é o modelo de atribuição simplificado acordado; não se deve somar separadamente um possível **realized P&L** a `position_pnl + trades_pnl`, pois duplicaria performance.
- Métricas adicionais de P&L realizado podem ser avaliadas separadamente futuramente; **não fazem parte da visualização padrão atual**.
- Para uma avaliação diária válida, usar referência do dia `D` para ativos/trades que a exigem; a referência `D-1` é exigida para `position_pnl` **somente quando `Q[a,D-1] != 0`**.
- **Primeiro dia** (OQ-4): quando `Q[a,D-1] = 0`, `position_pnl` é exatamente 0 (não `null`), sem exigir referência `D-1`. O P&L acumulado começa em 0 antes do primeiro lançamento.
- O PU de referência `D-1` usado é o registrado, com sua fonte, na linha `position_metrics` de `D-1` (OQ-9, OQ-25); uma mudança de preço em X marca a cadeia de posições como desatualizada de X em diante (OQ-23).
- Trades intradiários podem exigir preço de referência mesmo se a posição de fechamento for zero.

### 8.2 Valor de mercado e AUM

```text
financial_total[a,D]       = Q[a,D] × reference_PU[a,D]
positions_market_value[D]  = Σ financial_total[a,D]
aum[D]                     = cash_balance[D] + positions_market_value[D]
```

- `cash_balance[D]` vem da cadeia de caixa (`cash_balances`) e `positions_market_value[D]` da cadeia de posições (`portfolio_metrics`) (OQ-21). O AUM é `null` quando qualquer dos lados falta e não tem status próprio: a tela mostra os status do caixa e das posições (OQ-28). Quem publica qualquer das cadeias recalcula o AUM de cada data na transação dessa data, com o valor publicado da outra (OQ-23).

- `financial_total` significa **valor de mercado** da posição, **não** valor histórico investido.
- A quantidade é assinada, então uma posição vendida produz valor de mercado assinado negativo.
- **AUM**, neste simulador, é definido como saldo de caixa mais valor de mercado líquido das posições. Não incluir `gross_exposure`, `net_exposure` nem `total_equity` como campos adicionais.
- Mudanças de caixa por aporte e retirada podem alterar AUM sem alterar P&L.

### 8.3 Ausência e completude de dados

- Se a referência exigida não existe para a data exata, o sistema calcula **quantidade, custo médio e caixa**, mas deixa os resultados financeiros dependentes como **indisponíveis (`null`)**, nunca zero inventado.
- O valor de mercado de uma posição zero é zero mesmo sem referência; **isso não implica** que o P&L dos trades do dia seja calculável.
- Alguns ativos podem ter P&L disponível enquanto outros não. O P&L agregado da carteira **não é completo** se faltar resultado de qualquer ativo esperado.
- **Ativo esperado em D** (OQ-10): `Q[a,D-1] != 0` ou existe operação do ativo em D. Exatamente esses ativos têm linhas em `positions` e `position_metrics` para D, inclusive com quantidade 0 após zeragem ou round trip no dia.
- **Dia sem ativo esperado** (OQ-22), por exemplo depois de zerar tudo ou após o vencimento: o dia é processado mesmo assim. `portfolio_metrics` recebe a linha do dia com valor de mercado 0, AUM = caixa (`null` se o caixa faltar), P&L de posições, de operações e diário exatamente 0, ambos os estados completos, e P&L acumulado igual ao do dia anterior (`null` se a cadeia já estiver interrompida).
- O P&L acumulado permanece indisponível a partir do primeiro dia com lacuna não resolvida na cadeia histórica, até a correção e o reprocessamento necessário.
- Uma data sem preços no calendário da tela de Ativos não gera automaticamente pendência; a pendência surge quando um cálculo requer efetivamente a observação ausente.
- Ausência de dado de mercado **não é falha técnica** da fila ou da calculadora.
- As telas devem distinguir dados **válidos, ausentes/incompletos e desatualizados**; não combinar PU recém-corrigido com P&L calculado antes da correção.

## 9. Persistência funcional das posições e métricas

| Tabela | Chave lógica | Conteúdo |
|---|---|---|
| `portfolio.positions` | `(asset_id, position_date)` | Quantidade de fechamento assinada |
| `portfolio.position_metrics` | `(asset_id, metric_date)` | PU/taxa médios de entrada, PU de referência usado e sua fonte (OQ-25), `financial_total`, `position_pnl`, `trades_pnl`, `daily_pnl` e estados de completude |
| `portfolio.portfolio_metrics` | `metric_date` | Valor de mercado total, AUM, P&L de posições, P&L de operações, P&L diário, P&L acumulado e estados de completude |
| `portfolio.cash_balances` | `balance_date` | Saldo de caixa do dia e seus componentes: fluxo financeiro das operações, aportes e retiradas (OQ-21) |

- Não persistir uma entidade de negócio `portfolio` nem `portfolio_id`.
- Não criar simultaneamente tabelas PnL independentes duplicando exatamente os campos de `position_metrics`.
- O módulo PnL calcula; Portfolio armazena os resultados publicados.
- O frontend obtém uma **visão consolidada** por ativo/data a partir do Portfolio Query Service, em uma chamada HTTP, com leitura eficiente e controle de consistência de referência.
- **Não há tabelas de estágio** (OQ-23): cada data é gravada diretamente nas tabelas finais do escopo, na sua própria transação (§10.4). As tabelas finais ficam no schema `portfolio` e são de propriedade do módulo Portfolio (OQ-8).
- O status atual de cada data e cadeia fica em `processing.date_status(date, portfolio, cash)`, de propriedade do Processing: é a única fonte de atualização dos resultados publicados (§10.4, OQ-23).

## 10. Processamentos sob solicitação do usuário

### 10.1 Regra principal

**Cadastrar/excluir lançamento ou adicionar/corrigir/remover preço apenas persiste o fato e marca as saídas dependentes como desatualizadas (§10.4). Não inicia processamento de carteira nem manda recalcular P&L automaticamente.**

O usuário acessa **Central de Controle → Processamentos**, escolhe intervalo inclusivo de datas e o **escopo** — **Caixa**, **Posições** ou **Tudo** (OQ-21) — e confirma o processamento. Caixa processa só a cadeia de caixa; Posições, a de posições com avaliação e P&L; Tudo, as duas, publicadas juntas em cada data. **O processamento cobre exatamente o intervalo solicitado [A, B]**; não há expansão automática (OQ-11).

- Cada data D de cada cadeia parte do resultado publicado de D−1 da própria cadeia, e o status de D−1 decide se D fica atualizado (§10.4, OQ-23). Sem operações antes de A (posições) ou sem lançamentos de qualquer tipo antes de A (caixa), o estado de A−1 da cadeia é o estado zero, válido (OQ-26).
- **Posições** (OQ-11): se A−1 não está **Atualizado** (com ou sem pendências), o job ainda executa e publica [A, B]; esses dias ficam **Desatualizados**, o P&L fica `null` e uma pendência pede o processamento de um intervalo anterior.
- **Caixa** (OQ-22): se o caixa de A−1 está **desatualizado**, o job executa a partir dele e publica [A, B] marcado como desatualizado, com a mesma pendência. Se o caixa de A−1 **não foi publicado** e há lançamento datado até A−1, o job de Caixa ou Tudo é recusado ao iniciar: não publica nada e termina `FAILED` com o código `CASH_PREDECESSOR_MISSING` e a mensagem "Caixa do dia anterior não processado: processe primeiro um intervalo anterior." Enfileirar é sempre permitido.
- A pré-visualização avisa quando o estado de A−1 da cadeia do escopo está desatualizado ou ausente.

### 10.2 Fila, simultaneidade e cancelamento

- Podem existir **múltiplos pedidos enfileirados**, inclusive com intervalos sobrepostos.
- **Somente um pedido é executado por vez** para a carteira única.
- O usuário pode cancelar pedidos **na fila** imediatamente.
- Para pedido **em execução**, cancelar sinaliza interrupção; o worker verifica o sinal entre datas: a data em curso é concluída e publicada, as datas seguintes não são tocadas e o pedido termina `CANCELLED`. Um cancelamento que chega durante a última data deixa o pedido terminar `COMPLETED`, ou `COMPLETED_WITH_ISSUES` se alguma data gravada tem pendências (OQ-23, OQ-26).
- O usuário pode registrar nova operação ou corrigir preço, enfileirar um novo intervalo e cancelar o job anterior. A UI oferece **Cancelar e criar novo processamento**, que faz os dois pedidos de forma coordenada (OQ-20).
- A fila durável e os estados de jobs pertencem ao **PostgreSQL**. RabbitMQ transporta comandos de execução; não é a fonte de verdade sobre a ordem dos jobs.
- O worker processa cronologicamente as datas com chamadas diretas aos módulos (Portfolio, Prices, PnL); não se publica uma mensagem para cada ativo ou dia.
- Não há versões de inputs nem job descartado por mudança de dados (OQ-23). Uma gravação que chega durante um processamento espera os bloqueios das linhas de status de D−1 e D da data em curso e depois marca como desatualizado o que afeta (§10.4); o processamento não para por isso.
- Reentrega de mensagens, reinicialização de worker e retomada de lease não podem gerar duas publicações concorrentes.

### 10.3 Status e pendências

Um processamento (pedido) tem **oito** status (OQ-23); não existe `SUPERSEDED` (Obsoleto):

- `QUEUED`: na fila.
- `DISPATCHED`: enviado para o worker, ainda não executando.
- `RUNNING`: em processamento.
- `CANCELLING`: cancelamento sinalizado.
- `CANCELLED`: cancelado; as datas já concluídas continuam publicadas e as seguintes não são tocadas.
- `COMPLETED`: todas as datas do intervalo publicadas como **Atualizado**.
- `COMPLETED_WITH_ISSUES`: alguma data gravada pelo pedido ficou **Atualizado com pendências** (preço ausente ou contrato vencido com posição aberta) ou **Desatualizado**.
- `FAILED`: falha técnica inesperada em uma data, que fica com status **Erro** (§10.4), ou caixa de A−1 não publicado (`CASH_PREDECESSOR_MISSING`, §10.1, OQ-22).

Rótulos na interface (OQ-20, OQ-23): `QUEUED` **Na fila**, `DISPATCHED` **Enviado**, `RUNNING` **Processando**, `CANCELLING` **Cancelando**, `CANCELLED` **Cancelado**, `COMPLETED` **Concluído**, `COMPLETED_WITH_ISSUES` **Concluído com pendências**, `FAILED` **Falhou**. Não existe status "Bloqueado": preço ausente nunca interrompe um job.

Cada data tem, por cadeia, um status próprio, descrito em §10.4.

A lista de **Pendências** exibe problemas acionáveis: ativo, data necessária, motivo e ação. Deduplicar problemas repetidos para a mesma obrigação. Tipos atuais: **preço de referência faltante** (ação: definir preço), **contrato vencido com posição aberta** (§7.4) e **estado anterior desatualizado** (§10.1; ação: processar intervalo anterior), que indica a cadeia afetada, Caixa ou Posições (OQ-22).

### 10.4 Publicação por data, status das datas e invalidação

- **Sem estágio** (OQ-23): o processamento percorre [A, B] em ordem de calendário e publica **cada data na sua própria transação**, diretamente nas tabelas do escopo — `cash_balances` (Caixa); `positions`, `position_metrics` e `portfolio_metrics` (Posições); todas (Tudo) — e recalcula o AUM da data com o valor publicado da outra cadeia. Em Tudo, as duas cadeias e o AUM de uma data são gravados na mesma transação. O progresso (última data publicada) é consultável na UI.
- **Status de cada data** (OQ-23): `processing.date_status` guarda, para cada data corrida, o status atual de cada cadeia, **Caixa** e **Posições**. É a **única fonte** de atualização: todas as leituras e os dois indicadores (Caixa, Posições) vêm dele. Não se guarda o status de cada data de cada processamento; o pedido guarda só o seu status geral.
  - sem status (ou sem linha): **Não processado**;
  - `FRESH`: **Atualizado**;
  - `FRESH_WITH_ISSUES`: **Atualizado com pendências** (preço ausente ou contrato vencido com posição aberta);
  - `STALE`: **Desatualizado**;
  - `RUNNING`: **Processando**;
  - `FAILED`: **Erro** (a última tentativa falhou; a data mantém os dados publicados anteriormente).
- **Processar a data D de uma cadeia** (OQ-23): uma transação curta guarda o status anterior de D e marca D como Processando. Em seguida, a transação de D bloqueia as linhas de status de D−1 e D (em ordem crescente de data), calcula D, grava as linhas publicadas de D, recalcula o AUM de D, substitui as pendências anteriores da cadeia nessa data pelas novas (posições: preço ausente, contrato vencido e estado anterior desatualizado de posições; caixa: estado anterior desatualizado de caixa; OQ-26), registra D como progresso do pedido e define o status de D:
  - quando D−1 está Atualizado ou Atualizado com pendências, ou é o estado zero da cadeia (posições: nenhuma operação até D−1; caixa: nenhum lançamento de qualquer tipo até D−1; OQ-26): **Atualizado**, ou **Atualizado com pendências** se D tem preço ausente ou contrato vencido com posição aberta;
  - quando D−1 está em qualquer outro status: **Desatualizado**, com a pendência **estado anterior desatualizado** da cadeia.
- **Falha em D** (OQ-23): a transação de D é desfeita; uma transação curta marca D como **Erro** e grava o código e a mensagem do erro no pedido, que termina `FAILED`. As datas anteriores continuam publicadas; as seguintes não são tocadas.
- **Cancelamento**: §10.2. **Recuperação** após queda do worker ou perda do lease: o processamento retoma a partir da data seguinte ao último progresso registrado (OQ-23).
- **Data deixada em Processando** (OQ-26): se o pedido termina (cancelado ou encerrado após perda do lease) sem gravar uma data que marcou como Processando, a data volta ao status que tinha antes; uma data que nunca tinha sido processada volta a **Não processado**. Uma gravação que a invalide enquanto está em Processando faz o status anterior, se existir, virar **Desatualizado**. Uma falha em D marca D como **Erro** (acima).
- Toda escrita do worker (Processando, a transação da data, Erro, o erro e o status final do pedido) verifica o claim token e o lease na mesma transação; um worker afastado não altera nada.
- **Invalidação** (OQ-23): uma gravação datada em W marca como **Desatualizado**, na **mesma transação** que salva a alteração, o status da cadeia afetada em toda data ≥ W que já tenha status; datas sem status continuam **Não processado**.
  - Operação criada ou excluída: caixa **e** posições.
  - Aporte ou retirada: **somente** caixa (OQ-21).
  - Preço de referência inserido, corrigido ou removido: **somente** posições, **sem** alterar quantidade, caixa ou custo médio.
  - Uma exclusão múltipla com operações e movimentações marca cada cadeia necessária uma única vez, a partir da sua data mais antiga (OQ-24).
- Não há marcadores de invalidação nem contadores de revisão (OQ-23).
- Novos processamentos são uma decisão do usuário, não um efeito colateral da invalidação.
- **Limites operacionais** (OQ-5): sem tamanho máximo de intervalo; jobs mantidos como histórico; fila FIFO por `(created_at, id)`; lease de 60 s renovado a cada data processada; todos os valores configuráveis.

## 11. Telas e experiência do usuário

Os designs existentes no **Aura Build** são a base visual e devem ser implementados, não reconstruídos como um aplicativo de demonstração separado. Eles estão no Figma (Carteira, Ativos, Lançamentos, Central de Controle → Pendências) e no HTML clicável da Central de Controle (Processamentos); são preliminares e serão refinados durante o desenvolvimento. Dados e funcionalidades prevalecem: onde o design diverge desta especificação, valem as decisões OQ-19 e OQ-20. UI inteira em **pt-BR**, com React, Mantine e TanStack Query. Durante o desenvolvimento, o frontend real pode usar respostas simuladas via **MSW**, seguindo contratos de API revisáveis.

### 11.1 Central de Controle

Duas abas: **Pendências** e **Processamentos**.

- **Pendências:** problemas realmente identificados pela validação/processamento, não uma lista de todos os dias sem cotação. Somente os três tipos de §10.3; falha técnica (`FAILED`) aparece em Processamentos, não como pendência (OQ-19). Ação **Definir preço** conduz à entrada/correção da referência.
- **Processamentos:** escolher datas e escopo (Caixa, Posições ou Tudo; OQ-21), pré-visualizar o intervalo exato [A, B] (dias a processar, com aviso quando o estado anterior está desatualizado; sem "período efetivo" expandido), enfileirar, acompanhar progresso e status, ver erros, cancelar pedidos, cancelar e substituir. Os jobs continuam existindo no histórico após conclusão/cancelamento (OQ-20). Os status dos pedidos são os oito de §10.3.
  - Cada data é publicada na sua própria transação (§10.4, OQ-23): os detalhes de um job cancelado ou com falha informam a última data publicada, que as datas até ela continuam publicadas e que as seguintes não foram tocadas; na falha, mostram a data com **Erro**, o código e a mensagem.
  - Um job cancelado ou com falha oferece **Solicitar novo processamento**, que preenche o formulário a partir da data com falha ou, para um job cancelado, da primeira data não alcançada, até a data final original (OQ-23).
  - Pedidos sobrepostos ou repetidos continuam permitidos; não há coluna "Motivo".
- Sem KPIs financeiros redundantes na Central de Controle.

### 11.2 Ativos

- Navegar pelo cadastro `tipo → classe → produto → instrumento`. O catálogo mostra somente o que a API devolve (tipos como abas, produtos reais); nenhum produto ilustrativo (OQ-19).
- Ver contrato, especificações, datas e referências existentes. A lista de contratos de um produto mostra a última observação de referência (PU, taxa) **sempre ao lado da sua data**, nunca como preço de hoje.
- A tela de contrato permite cadastro/inspeção/correção de preço de referência de data específica. **Não há calculadora taxa ↔ PU** nessa tela (OQ-19): o usuário informa PU ou taxa e o valor complementar é calculado ao salvar.
- Calendário/serie de preços deve distinguir observações reais de dias sem observação; **não inventar** preços interpolados. Mostra a **Fonte** (Manual/B3) da observação preferencial; o menu da linha oferece **Corrigir** (altera a observação no lugar) e **Remover** (apaga a observação). Não há "Ver revisões" (OQ-25).
- Um PU informado manualmente não precisa gerar obrigatoriamente um segundo campo visível para a taxa implícita, embora o motor possa calculá-la quando necessário. Quando a taxa existir, ela é exibida ao lado do PU (OQ-19).

### 11.3 Lançamentos

- Visualizar os lançamentos — operações e movimentações de caixa em uma única lista, na ordem `(data, hora, seq)` (OQ-24) — com filtro de intervalo inclusivo, busca e paginação (§12).
- Registrar compra, venda, aporte e retirada por formulários/drawers apropriados; todos exigem data e hora.
- Distinguir **tipo de instrumento** de **tipo de lançamento**.
- Excluir um lançamento ou vários com confirmação, sem motivo e em uma única transação (tudo ou nada); **não editar** lançamentos existentes (OQ-24).
- Exibir data/hora efetiva e valores com formatação brasileira. Cada operação mostra PU **e** taxa de execução: o valor informado e o calculado pelo backend ao salvar (OQ-19).
- Faixa de caixa (OQ-19): **Caixa D0** é o saldo publicado na data final do período selecionado e **Caixa D−1** o do dia anterior, lidos do caixa publicado (`cash_balances`, via resumo da carteira) e marcados conforme o status de **caixa** de cada data em `processing.date_status` (§10.4; OQ-21, OQ-23).

### 11.4 Carteira

- Seleção de **uma data**; consulta a posições e métricas anteriormente publicadas, sem recalcular no GET.
- Indicadores: **Saldo em caixa**, **AUM/Patrimônio**, **P&L diário**, **P&L de posições** e **P&L de operações**.
- **Gráfico compacto de P&L acumulado** no nível da carteira, somente onde houver histórico completo e válido.
- O gráfico termina sempre na data selecionada da Carteira (mesma publicação dos indicadores); o usuário escolhe apenas a **data inicial**, anterior a essa data. Padrão: os 30 dias corridos que terminam na data. A data inicial fica na URL (`?pnl_start=`); valor inválido é ignorado (OQ-27).
- Tabela de posições consolida: ativo, vencimento, quantidade, PU médio, taxa média, PU de referência, taxa de referência (quando disponível), **valor de mercado** (`financial_total`), P&L posições e P&L operações.
- Os resultados por ativo e o total do portfólio derivam da mesma publicação coerente; não juntar preço novo com P&L velho.
- Exibir claramente métricas ausentes/incompletas ou desatualizadas; oferecer caminho contextual para Pendências ou Processamentos.
- Os indicadores de status **Caixa** e **Posições** da data vêm de `processing.date_status` (§10.4, OQ-23).
- Não listar caixa como linha de posição de ativo. Não expor P&L realizado/não realizado ou P&L acumulado por ativo na tabela padrão.

## 12. Regras de API e integração com frontend

- API de Carteira devolve dados agregados para a tabela em **uma resposta**, sem obrigar o React a coordenar pedidos a Asset, Prices, Portfolio e PnL.
- Respostas identificam data, estado de processamento/completude e valores ausentes com `null` (não zero). O status de cada cadeia na data vem de `processing.date_status` (OQ-23).
- Valores monetários/PU/taxas trafegam como números decimais representados por **strings**, para preservar precisão no frontend.
- Processamentos expõem criação, listagem, status/progresso (última data publicada e erro, se houver) e cancelamento. O frontend pode consultar status periodicamente enquanto houver trabalho.
- **Paginação** (usuário, 18/10/2026): listas paginadas recebem `?limit=&cursor=` e devolvem `{items, next_cursor}`, com cursor por chave: `(data, hora, seq)` para lançamentos e `(created_at, id)` para processamentos.
- Lançamentos usam uma única rota para os dois tipos, que substitui as rotas separadas de operações e de movimentações; a exclusão múltipla é um único pedido com a lista de ids (OQ-24).
- **Erros** (OQ-15) seguem `application/problem+json` (RFC 9457) com `errors: [{code, message, field}]`; mensagens em pt-BR, códigos em inglês, catálogo em `interfaces.md`.
- O gráfico de P&L acumulado da Carteira usa `GET /portfolio/pnl` (OQ-16), com `end_date` = data da Carteira e `start_date` escolhida pelo usuário (OQ-27).
- Contratos podem evoluir durante o desenvolvimento; mudanças compartilhadas devem ser coordenadas entre Integrador, backend e mocks MSW. Não congelar uma API incorreta só para preservar mocks.

## 13. Requisitos de qualidade e testes de aceitação

Devem existir testes de unidade para calculadoras e testes de integração para persistência e workflow, pelo menos cobrindo:

1. Taxa ↔ PU em DC/365, precisão, datas e limites próximos ao vencimento.
2. Compra, aumento, venda parcial, fechamento e reversão long/short com **ordem intradiária**.
3. PU médio e taxa média por regras próprias; manutenção do custo médio em redução parcial e zeragem.
4. Entradas/saídas de caixa e efeitos de trades sem creditar P&L no caixa.
5. `position_pnl`, `trades_pnl`, `daily_pnl`, agregação por ativos e P&L acumulado.
6. Aporte/retirada alterando caixa e AUM mas não P&L.
7. Sem PU do dia e/ou anterior, fim de semana, posição zero e round trip no mesmo dia; não fazer carry-forward.
8. P&L parcial em ativo sem publicar total de carteira aparentemente completo.
9. Mudança histórica em lançamento/PU e invalidação pelo status das datas (OQ-23): somente as datas ≥ W que já têm status ficam **Desatualizado**, só na cadeia afetada, e as datas sem status continuam **Não processado** (sem auto-job).
10. Dois pedidos com intervalos sobrepostos, cancelamento na fila, cancelamento em execução (a data em curso é publicada, as seguintes não são tocadas, `CANCELLED`; durante a última data, `COMPLETED` ou `COMPLETED_WITH_ISSUES`) e reposição.
11. Publicação por data (OQ-23): falha em D deixa D com **Erro**, mantém publicadas as datas anteriores e não toca as seguintes; regra do predecessor (D **Atualizado** somente com D−1 Atualizado, com ou sem pendências, ou estado zero; senão **Desatualizado** com pendência); uma gravação durante o job espera o bloqueio de D−1/D e marca o que afeta, sem interromper o job; idempotência/reentrega RabbitMQ; recuperação de worker a partir do último progresso; "Solicitar novo processamento" a partir da data com falha ou da primeira não alcançada.
12. Resposta consolidada da Carteira coerente por data e status; mocks em conformidade com APIs.
13. Cadeias separadas (OQ-21, OQ-23): um aporte marca Desatualizado somente o caixa, e uma operação, caixa e posições; um job Tudo grava as duas cadeias e o AUM de cada data na mesma transação; `aum = caixa + valor de mercado` após publicar só Caixa, só Posições e Tudo.
14. Predecessor (OQ-22): Caixa com A−1 não publicado e lançamentos anteriores termina `FAILED` (`CASH_PREDECESSOR_MISSING`) sem publicar; com A−1 desatualizado publica marcado; um job Tudo registra as duas pendências de predecessor, uma por cadeia.
15. Dia sem ativo esperado (OQ-22): posição zerada em D e D+1 sem ativos publica P&L 0, AUM = caixa e P&L acumulado levado adiante.
16. Lançamento único (OQ-24): operações e movimentações da mesma data seguem `(data, hora, seq)` entre os dois tipos; a exclusão múltipla mista é tudo ou nada, compartilha o identificador de lote e marca cada cadeia uma única vez, a partir da sua data mais antiga.
17. Preços sem revisões (OQ-25): corrigir altera a observação no lugar; remover o MANUAL faz o B3 prevalecer; corrigir ou remover um preço já usado é permitido e marca as posições como Desatualizado da sua data em diante; a linha publicada guarda o PU e a fonte usados.

## 14. Decisões fechadas e itens ainda abertos

### Fechado

- Uma carteira; monólito modular; `market_data` renomeado para `prices`.
- Ledger é dono exclusivo de preços executados em trades; Prices apenas de referências.
- Prioridade de preços MANUAL > B3, uma observação por instrumento, data e fonte (OQ-25).
- Ativos classificados por tipo, classe, produto e instrumento; `asset.futures` para especificações compartilhadas.
- DC/365, processamento em **cada dia corrido**, **sem carregamento implícito** de cotação antiga.
- Quatro tabelas finais de carteira: `positions`, `position_metrics`, `portfolio_metrics` e `cash_balances` (OQ-21).
- `financial_total` é valor de mercado; AUM é caixa + valor de mercado assinado; sem campos de exposição ou `total_equity` redundante.
- P&L por ativo e depois agregado; aportes/retiradas excluídos do P&L.
- Mudanças apenas invalidam; processamento da carteira ocorre **sob comando explícito do usuário**.
- Fila com sobreposição permitida, uma execução por vez, cancelamento seguro e publicação de cada data na sua própria transação (OQ-23).
- Frontend real baseado nos designs existentes, com chamadas mockadas por MSW em paralelo ao desenvolvimento do backend.

Decididos em 18/10/2026 (detalhes e palavras do usuário em `open-questions.md`):

- Sem liquidação automática no vencimento; o usuário encerra com operação a qualquer PU, inclusive na data de vencimento (taxa 0); após o vencimento, valor 0 e lançamentos rejeitados (OQ-1, OQ-6).
- Multiplicador mantido no cadastro e não aplicado nos cálculos atuais (OQ-2).
- Precisão: 34 dígitos, `ROUND_HALF_UP`, PU 10 casas, taxa 12 casas, excesso de casas rejeitado (OQ-3).
- Primeiro dia: `position_pnl` = 0 quando `Q[D-1] = 0` (OQ-4).
- Limites operacionais simples e configuráveis (OQ-5).
- Fins de semana e feriados aceitos; datas futuras rejeitadas; limites de valores apenas do schema (OQ-7, OQ-14).
- Tabelas de resultados no schema `portfolio`, de propriedade do Portfolio (OQ-8); sem tabelas de estágio desde OQ-23.
- PU `D-1` rastreado pela linha de `D-1`, que guarda PU e fonte usados (OQ-9, OQ-25).
- Ativo esperado: `Q[D-1] != 0` ou operação em D (OQ-10).
- Intervalo exato [A, B], sem expansão; predecessor desatualizado publica como desatualizado (OQ-11).
- Atualização dos resultados pelo status de cada data (OQ-12, substituído por OQ-23).
- Hora obrigatória em todo lançamento; ordem `(data, hora, seq)` entre operações e movimentações (OQ-13, OQ-24).
- Erros em problem+json (RFC 9457) com catálogo de códigos (OQ-15).
- `GET /portfolio/pnl` alimenta o gráfico de P&L acumulado (OQ-16).
- Gráfico de P&L acumulado da Carteira: só data inicial (anterior à data da Carteira, padrão 30 dias, na URL); termina sempre na data da Carteira (usuário, 18/10/2026, sessão do frontend; OQ-27).
- Lane H é dona de `platform/**` (OQ-17).
- Caixa e posições são duas cadeias processáveis separadamente (escopos Caixa, Posições e Tudo), cada uma com seu status por data (OQ-23); caixa publicado em `cash_balances`; AUM recalculado por quem publica (OQ-21).
- Caixa de A−1 não publicado recusa o job ao iniciar; caixa desatualizado publica marcado; posições seguem OQ-11; pendência de predecessor indica a cadeia; dia sem ativo esperado é processado com P&L 0 e acumulado levado adiante; sem processo automático à meia-noite (OQ-22).
- Arquitetura (usuário, 18/10/2026): `infrastructure/` contém persistência e outros adaptadores de saída; consumidores e handlers RabbitMQ de um módulo ficam em `presentation/messaging/`, a infraestrutura RabbitMQ compartilhada em `platform/messaging/`, e a lógica de processamento em `application/`. O domínio é determinístico e sem I/O nem efeitos colaterais (sem arquivo, rede, banco, mensageria, ambiente ou relógio do sistema); utilitários puros da biblioteca padrão (`datetime`, `Decimal`, `Enum`, `dataclasses`) são permitidos. O domínio não faz logging (que pertence às camadas de aplicação, infraestrutura e apresentação) e comunica falhas por exceções e resultados explícitos; não gera aleatoriedade internamente: um cálculo que precise dela (ex.: Monte Carlo) recebe uma semente explícita ou um gerador injetado.

- Desvios e interpretações do enunciado registrados em §15 (OQ-18).
- Design × especificação (usuário, 18/10/2026, sessão do frontend; OQ-19, OQ-20): dados e funcionalidades da especificação prevalecem sobre o design preliminar; Carteira com P&L de posições e de operações; três tipos de pendência; faixa Caixa D0/D−1 em Lançamentos; catálogo só com dados da API; última referência sempre com sua data; coluna Fonte no calendário, com menu Corrigir e Remover (OQ-25); sem calculadora taxa ↔ PU nem prévia (valor complementar calculado ao salvar); intervalo exato [A, B]; oito status com rótulos em português e sem "Bloqueado" (OQ-23); publicação por data (OQ-23); novo processamento a partir da data com falha ou da primeira data não alcançada (OQ-23); cancelar e substituir.
- Processamento dia a dia (OQ-23): sem estágio, cada data publicada na sua própria transação; `processing.date_status` guarda o status atual de cada data por cadeia (Atualizado, Atualizado com pendências, Desatualizado, Processando, Erro; sem status = Não processado) e é a única fonte de atualização; gravações marcam Desatualizado as datas com status a partir da sua data; sem marcadores, revisões nem `SUPERSEDED`; falha em D deixa D com Erro e não toca as datas seguintes; cancelamento publica a data em curso; recuperação a partir do último progresso.
- Lançamento único (OQ-24): `ledger.entries` para operações e movimentações de caixa, hora obrigatória, `seq` comum, valor de caixa com sinal; exclusão lógica sem motivo; exclusão múltipla em uma única transação, com identificador de lote; rotas `/ledger/entries`.
- AUM sem status (OQ-28): `aum` é apenas o valor (caixa + valor de mercado, `null` se um lado falta); a tela mostra os status das duas cadeias.
- Preços de referência sem revisões (OQ-25): uma observação por instrumento, data e fonte; correção no lugar, remoção apaga; rastreio pelo PU e fonte gravados em `position_metrics`.

### Aberto — requer decisão específica antes de codificar o comportamento

Nenhum item em aberto.

### TODO posterior à entrega principal

- Importação CSV de preços de referência via RabbitMQ.
- Integração para captura de preços oficiais B3.

## 15. Desvios e interpretações do enunciado

Fonte: `docs/desafio_tecnico_di1_1.pdf`. Auditoria de 18/10/2026; desvios aprovados pelo usuário (OQ-18). O README repete esta seção.

### Interpretações (texto ambíguo)

| # | Enunciado | Leitura adotada | Por quê |
|---|---|---|---|
| I1 | §3: o contrato possui identificador, **data de referência**, vencimento e taxa ou PU | O contrato possui identificador e vencimento; data de referência e taxa/PU pertencem à calculadora, à operação ou ao preço de referência | Os mesmos dados, separados entre o contrato estático e os eventos datados |
| I2 | §4.2: saldo de caixa = entradas − saídas | O caixa inclui também o efeito financeiro das operações (§7.3) | O exemplo do §5 exige: caixa 109.090,91 após a compra |
| I3 | §5: "Financeiro total: 200.000" | AUM = caixa + valor de mercado (§8.2) | 200.000 = 109.090,91 + 90.909,09 |
| I4 | §5: "Resultado financeiro simplificado da posição" | Valor de mercado (`financial_total`) e P&L de posições e de operações (§8) | O enunciado não define a métrica |

### Adições (não rejeitam nada que o enunciado descreve, exceto D4)

Hora da operação obrigatória (§6.1); regras de vencimento (§7.4); fontes MANUAL e B3 (§5); Pendências e processamento sob solicitação (§10).

### Desvios deliberados

| # | Enunciado | Especificação | Como o exemplo do enunciado roda |
|---|---|---|---|
| D1 | §5: BRL aparece como linha da tabela de posições (QTD 109090.91, PREÇO 1) | Caixa é o indicador "Saldo em caixa", nunca uma linha de posição (§11.4) | Mesmos números, apresentação diferente |
| D2 | §5: "preços de referência disponíveis"; o exemplo avalia DI1F28 ao preço da própria operação | Preço de referência somente da data exata; preço de execução nunca vira referência (§4.2, §5) | O usuário informa também um preço de referência de 10% (PU 90.909,09) para DI1F28 em 01/01/2027; os números então coincidem |
| D3 | §5 e requisito 6: a consulta reconstrói a carteira a partir dos eventos até a data | A reconstrução ocorre no processamento solicitado pelo usuário, a partir dos fatos imutáveis; o GET só lê resultados publicados (§10, §11.4) | Após um processamento de 01/01/2027; antes disso a tela mostra "não processado" ou "desatualizado", com link para Processamentos. Justifica onde o assíncrono agrega valor (§8 do enunciado) |
| D4 | Os exemplos são datados de 01/01/2027, data futura em 18/10/2026 | Datas após hoje são rejeitadas (§6.1) | Testes automatizados rodam os exemplos exatamente como escritos, com relógio injetado fixo em 01/01/2027; a demonstração do README usa os mesmos passos datados de hoje, com vencimento em hoje + 365 dias: números idênticos (PU 90.909,09, caixa 109.090,91, AUM 200.000) |

---

**Diretriz para agentes:** não reinterpretar campos, mudar o modelo de P&L, inserir recálculo automático, adicionar múltiplas carteiras ou carregar cotações anteriores sem solicitação expressa. Ao identificar ambiguidade, registrar a decisão pendente e propor alternativa com impactos, sem preencher silenciosamente a lacuna.
