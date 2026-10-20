# Maravi DI1 Backoffice — Especificação funcional e decisões de negócio

**Status:** documento de referência das decisões acordadas até 19/10/2026 (OQ-1 a OQ-47; nenhuma em aberto).  
**Público-alvo:** desenvolvimento, revisão de regras financeiras, frontend, testes e agentes de IA.  
**Propósito:** descrever **o que a aplicação faz**, **como deve se comportar** e **quais decisões estão fechadas**, independentemente da organização interna do código.

> **Hierarquia de fontes:** o enunciado do desafio técnico define os requisitos mínimos. Este documento registra as decisões de produto e extensões aprovadas nas conversas posteriores. Em caso de conflito com documentos antigos, prevalecem as decisões explícitas mais recentes; discrepâncias com o enunciado devem ser registradas e não ocultadas. `schema.md`, `schema.sql`, `interfaces.md` e o plano de implementação detalham a execução técnica. **Nomes exatos de endpoints e tipos SQL não são requisitos de negócio.**

## 1. Objetivo e escopo

A Maravi DI1 Backoffice é uma aplicação web para cadastrar instrumentos financeiros, calcular PU ou taxa de contratos DI1, registrar operações e movimentações de caixa, informar preços de referência e consultar a composição e o desempenho histórico de **uma única carteira**.

- Há **exatamente uma carteira** no escopo atual; não existe seleção de carteira nem necessidade de `portfolio_id` nas entidades.
- Usuários registram operações e preços; o sistema calcula e publica posições e métricas históricas **somente após um processamento solicitado explicitamente**.
- A aplicação deve ser reproduzível, auditável e transparente quando os dados estão ausentes, incompletos ou não processados.
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
| `processing` | Validar pedidos, enfileirar, executar, cancelar e publicar processamentos; administrar o status e o horário de processamento de cada data e as pendências | Alterar entrada **não** dispara processamento automaticamente |

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
- **Os preços ficam somente na tabela de preços** (OQ-30): a Carteira mostra, para cada data, o PU, a taxa e a fonte da observação preferencial atual (MANUAL, senão B3, data exata; após o vencimento o PU é 0). `position_metrics` não guarda PU de referência nem fonte; guarda o `financial_total` e o P&L calculados. Após uma correção de preço, a data mostra o PU novo ao lado dos valores antigos e mantém o seu status de processamento até o usuário reprocessá-la (OQ-31).
- A remoção da observação manual faz a fonte B3, se existir, passar a prevalecer para a mesma data.
- Inserir, corrigir ou remover preço **apenas grava a observação** (OQ-31): não marca nenhuma data, **não altera trades e nem recalcula as quantidades**, e nenhuma atualização de preço inicia um job de P&L automaticamente. Os resultados já processados permanecem como estão até o usuário processar de novo.
- Importação massiva CSV e coleta de preços B3 são **TODOs futuros, após o núcleo estar concluído**. Quando introduzidas, devem reutilizar o PriceService; uma via assíncrona pode integrar via RabbitMQ.

## 6. Lançamentos (`ledger`)

Operações e movimentações de caixa são uma única entidade, o **lançamento** (OQ-24): cada lançamento é uma **operação** ou uma **movimentação de caixa**, com data e **hora obrigatórias** e uma sequência (`seq`) comum aos dois tipos. A ordem de processamento é `(data, hora, seq)` entre os dois tipos.

- **Não há edição** de lançamentos. A exclusão é **definitiva** (OQ-32): o lançamento é apagado do banco e não fica registrado em lugar nenhum, sem trilha de auditoria. A exclusão de um ou vários lançamentos é confirmada pelo usuário, **sem motivo**, e ocorre em uma única transação (tudo ou nada); um id inexistente ou já excluído recusa o pedido inteiro (404) e nada é excluído. Uma lista vazia é recusada (422); um id repetido conta uma vez (OQ-32). Os resultados já processados mantêm seus valores até o usuário processar as datas de novo (OQ-31).
- O efeito de caixa de uma operação não é armazenado: é calculado na leitura como −quantidade assinada × PU de execução (§7.3).

### 6.1 Operações

Uma compra/venda inclui contrato, direção, quantidade, data/hora efetiva e PU **ou** taxa de execução. O sistema pode calcular a representação faltante através de Pricing.

- **Data e hora são obrigatórias** (OQ-13, OQ-24): hora em horário local de São Paulo; o formulário sugere a hora atual.
- **Datas aceitas** (OQ-7, OQ-14): qualquer data corrida, inclusive fins de semana e feriados; nada datado **após hoje** (America/Sao_Paulo) é aceito, para operações, movimentações e preços. Vencimentos são isentos.
- **Vencimento** (OQ-1): uma operação pode ser datada até a data de vencimento, inclusive; nessa data (dias corridos = 0) o PU é digitado e a taxa é armazenada como `0`. Operações datadas após o vencimento são rejeitadas.

- Cada operação é preservada individualmente, mesmo quando várias operações atingem o mesmo contrato no mesmo dia.
- A ordem de processamento é cronológica: `(data, hora, seq)`; não somar ou compensar todas as operações do dia antes de atualizar custos médios.
- `created_at` (instante de cadastro) é diferente do momento efetivo da operação.
- Incluir ou excluir uma operação apenas grava o fato; não marca nenhuma data, e os resultados já processados permanecem até o usuário processar de novo (OQ-31).

### 6.2 Movimentações de caixa

- Dois tipos: **aporte** e **retirada**, cada qual com valor positivo informado e data e hora efetivas (hora obrigatória, OQ-24). O valor é armazenado com sinal: positivo para aporte, negativo para retirada, nunca zero.
- **Descrição opcional** (enunciado §4.2; OQ-51): texto livre de até 200 caracteres, gravado sem espaços nas pontas e na forma Unicode composta (NFC); vazia ou em branco vira nula; o caractere nulo é rejeitado (422). Só movimentações de caixa têm descrição: uma operação com descrição não vazia é rejeitada (422). Como o resto do lançamento, não é editada.
- Também não podem ser editadas; a exclusão é definitiva, como para todo lançamento (§6, OQ-32).
- Incluir ou excluir uma movimentação apenas grava o fato; não marca nenhuma data (OQ-31).
- Aportes/retiradas modificam **saldo de caixa** e AUM, **não** P&L.
- Não há obrigação de modelar BRL como um instrumento negociável para exibir caixa na carteira.

## 7. Contabilidade diária da carteira (`portfolio`)

### 7.1 Estado inicial e calendário

- Estado inicial antes do primeiro lançamento relevante: **caixa zero, posição zero, P&L zero**.
- Calcula-se **todos os dias corridos** do intervalo do processamento, inclusive fins de semana e feriados.
- Há **duas cadeias diárias independentes** (OQ-21): a de **caixa** (§7.3) e a de **posições** (§7.2, com avaliação e P&L, §8). Ambas leem os mesmos fatos do Ledger e nunca a saída uma da outra; só se encontram no AUM (§8.2).
- O cálculo do dia de cada cadeia usa o estado anterior válido **da própria cadeia** e aplica sequencialmente os fatos daquele dia.
- A posição de abertura de D é a de fechamento de D−1, levada adiante quando o usuário processa D; não há processo automático à meia-noite (OQ-22). O usuário processa D0 quando quiser (§10.1).
- O resultado publicado de D−1 é o ponto de partida de D. Quando o status de D−1 da cadeia não é **Processado** nem **Processado com pendências**, nem é o estado zero, D fica com **Erro** e o processamento termina `FAILED` (§10.1, OQ-31; num processamento Tudo em que só uma cadeia falha, termina `COMPLETED_WITH_ISSUES`, OQ-36).

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
- O PU de referência `D-1` usado é o da tabela de preços, observação preferencial atual de `D-1` (OQ-9, OQ-30). Uma mudança de preço não marca nenhuma data (OQ-31): se o preço de `D-1` mudou depois que `D-1` e `D` foram processados, os dois continuam com o seu status de processamento até o usuário reprocessá-los.
- Trades intradiários podem exigir preço de referência mesmo se a posição de fechamento for zero.

### 8.2 Valor de mercado e AUM

```text
financial_total[a,D]       = Q[a,D] × reference_PU[a,D]
positions_market_value[D]  = Σ financial_total[a,D]
aum[D]                     = cash_balance[D] + positions_market_value[D]
```

- `cash_balance[D]` vem da cadeia de caixa (`cash_balances`) e `positions_market_value[D]` da cadeia de posições (`portfolio_metrics`) (OQ-21). O AUM é `null` quando qualquer dos lados falta e não tem status próprio: a tela mostra os status do caixa e das posições (OQ-28). O AUM não é gravado (OQ-50 item 1): cada leitura o calcula como `cash_balance[D] + positions_market_value[D]`, só quando as duas cadeias **da data** estão Processado ou Processado com pendências, qualquer que seja o pedido que as gravou (OQ-38, OQ-40); caso contrário (Erro, Processando ou não processado, por exemplo depois da falha de uma cadeia num Tudo), ou quando um dos lados falta, é `null`.

- `financial_total` significa **valor de mercado** da posição, **não** valor histórico investido.
- A quantidade é assinada, então uma posição vendida produz valor de mercado assinado negativo.
- **AUM**, neste simulador, é definido como saldo de caixa mais valor de mercado líquido das posições. Não incluir `gross_exposure`, `net_exposure` nem `total_equity` como campos adicionais.
- Mudanças de caixa por aporte e retirada podem alterar AUM sem alterar P&L.

### 8.3 Ausência e completude de dados

- Se a referência exigida não existe para a data exata, o sistema calcula **quantidade, custo médio e caixa**, mas deixa os resultados financeiros dependentes como **indisponíveis (`null`)**, nunca zero inventado.
- O valor de mercado de uma posição zero é zero mesmo sem referência; **isso não implica** que o P&L dos trades do dia seja calculável.
- Alguns ativos podem ter P&L disponível enquanto outros não. O P&L agregado da carteira **não é completo** se faltar resultado de qualquer ativo esperado.
- **Ativo esperado em D** (OQ-10): `Q[a,D-1] != 0` ou existe operação do ativo em D. Exatamente esses ativos têm linhas em `positions` e `position_metrics` para D, inclusive com quantidade 0 após zeragem ou round trip no dia.
- **Dia sem ativo esperado** (OQ-22), por exemplo depois de zerar tudo ou após o vencimento: o dia é processado mesmo assim. `portfolio_metrics` recebe a linha do dia com valor de mercado 0, AUM = caixa, quando a cadeia de caixa está processada nessa data; caso contrário, `null` (OQ-38), P&L de posições, de operações e diário exatamente 0, ambos os estados completos, e P&L acumulado igual ao do dia anterior (`null` se a cadeia já estiver interrompida).
- O P&L acumulado permanece indisponível a partir do primeiro dia com lacuna não resolvida na cadeia histórica, até a correção e o reprocessamento necessário. A única exceção deliberada a "`null`, nunca zero" é a soma do gráfico de P&L acumulado da Carteira (`range_cumulative_pnl`, §11.4, OQ-41), em que um dia não processado ou com P&L diário indisponível conta como 0; o título do card "P&L acumulado" mostra a mesma soma, com a mesma exceção e a mesma nota de período incompleto (OQ-41 item 5, OQ-48 item 3).
- Uma data sem preços no calendário da tela de Ativos não gera automaticamente pendência; a pendência surge quando um cálculo requer efetivamente a observação ausente.
- Ausência de dado de mercado **não é falha técnica** da fila ou da calculadora.
- As telas devem distinguir dados **válidos, ausentes/incompletos e não processados**, com o status e o horário de processamento de cada data e cadeia (OQ-31); um PU corrigido depois do processamento aparece ao lado dos valores calculados antes da correção, e a data mantém o seu status até ser reprocessada (OQ-30, OQ-31). Desde OQ-50 (item 3), a Carteira marca essa linha (§11.4).

## 9. Persistência funcional das posições e métricas

| Tabela | Chave lógica | Conteúdo |
|---|---|---|
| `portfolio.positions` | `(asset_id, position_date)` | Quantidade de fechamento assinada |
| `portfolio.position_metrics` | `(asset_id, metric_date)` | PU/taxa médios de entrada, `financial_total`, `position_pnl`, `trades_pnl`, `daily_pnl` e estados de completude |
| `portfolio.portfolio_metrics` | `metric_date` | Valor de mercado total, AUM (coluna sem uso desde OQ-50: o AUM é calculado na leitura), P&L de posições, P&L de operações, P&L diário, P&L acumulado e estados de completude |
| `portfolio.cash_balances` | `balance_date` | Saldo de caixa do dia e seus componentes: fluxo financeiro das operações, aportes e retiradas (OQ-21) |

- Não persistir uma entidade de negócio `portfolio` nem `portfolio_id`.
- Não criar simultaneamente tabelas PnL independentes duplicando exatamente os campos de `position_metrics`.
- O módulo PnL calcula; Portfolio armazena os resultados publicados.
- `position_metrics` não guarda PU de referência nem fonte: a leitura da Carteira os obtém da observação preferencial atual na tabela de preços (OQ-30).
- O frontend obtém uma **visão consolidada** por ativo/data a partir do Portfolio Query Service, em uma chamada HTTP, com leitura eficiente e controle de consistência de referência.
- **Não há tabelas de estágio** (OQ-23): cada data é gravada diretamente nas tabelas finais do escopo, na sua própria transação (§10.4). As tabelas finais ficam no schema `portfolio` e são de propriedade do módulo Portfolio (OQ-8).
- O status atual de cada data e cadeia e o horário do seu último processamento ficam em `processing.date_status(date, portfolio, cash, portfolio_processed_at, cash_processed_at)`, de propriedade do Processing: é a única fonte do status de processamento dos resultados publicados (§10.4, OQ-23, OQ-31).

## 10. Processamentos sob solicitação do usuário

### 10.1 Regra principal

**Cadastrar/excluir lançamento ou adicionar/corrigir/remover preço apenas persiste o fato (OQ-31). Não marca nenhuma data, não inicia processamento de carteira nem manda recalcular P&L automaticamente.** Os resultados já processados permanecem como estão até o usuário processar de novo.

O usuário acessa **Central de Controle → Processamentos**, escolhe intervalo inclusivo de datas e o **escopo** — **Caixa**, **Posições** ou **Tudo** (OQ-21) — e confirma o processamento. Caixa processa só a cadeia de caixa; Posições, a de posições com avaliação e P&L; Tudo, as duas, publicadas juntas em cada data. **O processamento cobre exatamente o intervalo solicitado [A, B]**; não há expansão automática (OQ-11).

- Cada data D de cada cadeia parte do resultado publicado de D−1 da própria cadeia (§10.4, OQ-23).
- **Regra do predecessor, por dia** (OQ-31, uma regra para as duas cadeias): um processamento pode começar em qualquer data. Para cada data D de uma cadeia, o worker verifica se D−1 está **Processado** ou **Processado com pendências**, ou é o estado zero da cadeia: nenhuma data anterior a D tem status da cadeia (Processado, Processado com pendências, Processando ou Erro) **e** não há lançamento do tipo da cadeia datado até D−1 (posições: nenhuma operação; caixa: nenhum lançamento de qualquer tipo; OQ-26, OQ-32, OQ-40 item 5). Caso contrário, D fica com **Erro**, o pedido recebe o código `CASH_PREDECESSOR_MISSING` ou `POSITIONS_PREDECESSOR_MISSING` e a mensagem "Dia anterior não processado", termina `FAILED` (em Tudo, ver abaixo) e as datas seguintes não são tocadas. Como as datas são processadas em ordem, isso só pode acontecer na primeira data do pedido. Um D−1 com **Erro** conta como não processado. O Lançamentos só é consultado sobre o estado zero quando a cadeia não tem status em nenhuma data anterior a D (OQ-40 item 5); se D−1 está sem status mas uma data anterior da cadeia tem status (um buraco), D fica com **Erro** sem consultar: todo dia precisa ser processado (OQ-37). Enfileirar é sempre permitido.
- **Tudo, falha de uma cadeia** (OQ-36, substitui OQ-31 item 7): num processamento Tudo, se uma cadeia falha em D, pela regra do predecessor ou por erro técnico, ela fica com **Erro** em D e as suas datas seguintes no intervalo não são tocadas; a outra cadeia ainda é gravada em D, na mesma transação, e segue até o fim do intervalo (OQ-36 item 8). As datas continuam em ordem, uma transação por data; enquanto as duas cadeias estão ativas, ambas são gravadas na mesma transação, sem execução paralela. A data D roda numa transação com um SAVEPOINT por cadeia (OQ-40 item 1): um erro técnico numa cadeia desfaz só essa cadeia até o seu savepoint e a marca com **Erro**; o pedido guarda o primeiro erro, e as linhas, o AUM, o progresso (`progress_date`) e os status da cadeia que sobrevive são gravados na mesma transação, sem janela de queda entre o **Erro** e o progresso. Uma falha que não pertence a nenhuma cadeia, isto é, fora do savepoint de todas as cadeias (por exemplo, tempo de espera de bloqueio esgotado nas linhas de status da data; lista definida pelo integrador), desfaz toda a data D: D fica com **Erro** em todas as cadeias ainda ativas no pedido e o pedido termina `FAILED`; uma cadeia que já tinha parado mantém as suas datas seguintes intocadas (OQ-36 item 1). Uma queda do worker não é uma falha em D: o pedido é retomado quando o worker inicia (OQ-40, OQ-45). O AUM da data segue o status da outra cadeia nessa data (§8.2, OQ-38, OQ-40). O pedido termina `COMPLETED_WITH_ISSUES` com o código e a mensagem da primeira falha, e só termina `FAILED` se as duas cadeias falharem; se as duas falharem na mesma data, o código é `POSITIONS_PREDECESSOR_MISSING` no caso do predecessor, ou o erro da cadeia de posições nos demais casos. Processamentos só de Caixa ou só de Posições não mudam.
- Um pedido de processamento ou uma pré-visualização cujo intervalo termina **após hoje** é recusado com 422 `FUTURE_DATE` (OQ-29).
- Um pedido de processamento, uma pré-visualização ou a série de P&L (`GET /portfolio/pnl`) com mais de **3.660 datas**, contando as duas pontas, é recusado com 422 `INVALID_RANGE` em `end_date` e a mensagem "O período deve ter no máximo 3.660 dias." (OQ-5 item 1, emendado em 19/10/2026).
- A pré-visualização devolve o status de A−1 das duas cadeias (`predecessor.cash` e `predecessor.positions`) em qualquer escopo (OQ-39); só as cadeias do escopo decidem o aviso, aplicado pelo frontend, quando A−1 não está processado nem é o estado zero (OQ-40 item 5), caso em que o pedido terminará com erro em A (OQ-31).

### 10.2 Fila, simultaneidade e cancelamento

- Podem existir **múltiplos pedidos enfileirados**, inclusive com intervalos sobrepostos.
- **Somente um pedido é executado por vez** para a carteira única.
- O usuário pode cancelar pedidos **na fila** imediatamente: o pedido `QUEUED` passa a `CANCELLED`. Cancelar um pedido já terminado é recusado (409 `JOB_NOT_CANCELLABLE`) (OQ-29). Desde OQ-46 não há pedido enviado (`DISPATCHED`): o caminho `DISPATCHED` → `CANCELLING` de OQ-29 não ocorre mais e `CANCELLING` não é usado (leitura do integrador).
- Para pedido **em execução**, cancelar sinaliza interrupção; o worker verifica o sinal entre datas: a data em curso é concluída e publicada, as datas seguintes não são tocadas e o pedido termina `CANCELLED`. Um cancelamento que chega durante a última data deixa o pedido terminar `COMPLETED`, ou `COMPLETED_WITH_ISSUES` se alguma data gravada tem pendências (OQ-23, OQ-26). Mantido por decisão do usuário (OQ-50 item 6): o cancelamento age entre datas, e durante a última data não resta nada a pular, então o pedido terminou normalmente; depois de terminado, o pedido não mostra "cancelamento solicitado" (Cancelando só aparece para um pedido `RUNNING`).
- O usuário pode registrar nova operação ou corrigir preço, enfileirar um novo intervalo e cancelar o job anterior, como **ações separadas**: não há ação combinada de cancelar e substituir (OQ-30, que reverte OQ-20 item 5).
- A fila durável e os estados de jobs pertencem ao **PostgreSQL**. RabbitMQ transporta comandos de execução; não é a fonte de verdade sobre a ordem dos jobs.
- **Sem dispatcher** (OQ-46): `POST /processing/requests` grava o pedido `QUEUED` e, na mesma transação, uma mensagem no outbox que só avisa "há trabalho" (uma campainha, sem o ID do pedido). A cada mensagem, e na inicialização depois da recuperação (§10.4), o worker repete até não restar pedido `QUEUED`: numa transação, bloqueia a linha do pedido `QUEUED` mais antigo por `(created_at, id)` e o marca `RUNNING` com `started_at`; depois o executa. Uma mensagem que não encontra pedido `QUEUED` não faz nada. O PostgreSQL decide a ordem; uma mensagem perdida é coberta por qualquer mensagem seguinte ou por um reinício, e duplicatas são inofensivas. Um só pedido executa por vez porque há um só worker, que esvazia a fila em série. **Desde OQ-50 (item 2, "option 1"):** não há campainha. `POST /processing/requests` grava o pedido `QUEUED` e, na mesma transação, uma mensagem no outbox com o seu `request_id`, que serve só para rastreio e logs (o relay não garante a ordem de publicação). O worker consome uma mensagem por vez; a cada mensagem, pega o pedido `QUEUED` mais antigo por `(created_at, id)`, com bloqueio de linha, e o executa; sem pedido `QUEUED`, confirma e não faz nada. **A ordem FIFO por `(created_at, id)` não muda** (OQ-5). Uma varredura periódica no worker, a cada poucos segundos, faz o mesmo enquanto houver pedido `QUEUED`, então uma mensagem perdida só atrasa a execução. O PostgreSQL continua guardando status e histórico. Saem o inbox e a sua retenção, as filas de mensagens mortas (dead-letter), o limite de entregas, o backoff de reentrega e a fila de trabalho pós-ACK. Continuam um só worker e um só pedido executando por vez.
- O worker processa cronologicamente as datas com chamadas diretas aos módulos (Portfolio, Prices, PnL); não se publica uma mensagem para cada ativo ou dia.
- Não há versões de inputs nem job descartado por mudança de dados (OQ-23). Uma gravação que chega durante um processamento apenas grava o fato; não marca nada e o processamento não para por isso (OQ-31).
- Há **um único worker** de processamento (OQ-45), com prefetch 1, mais o relay do outbox; não há processo dispatcher (OQ-46). Não há lease nem token de posse. A entrega pelo RabbitMQ continua pelo menos uma vez; como a mensagem não carrega dados, uma mensagem reentregue ou duplicada não gera duas publicações, e o worker pode confirmá-la (ACK) ao recebê-la (leitura do integrador). Desde OQ-50 (item 2), uma mensagem duplicada é inofensiva: pega o próximo pedido `QUEUED` ou não encontra nenhum, sem inbox.

### 10.3 Status e pendências

Um processamento (pedido) tem **oito** status (OQ-23); não existe `SUPERSEDED` (Obsoleto):

- `QUEUED`: na fila.
- `DISPATCHED`: enviado para o worker, ainda não executando. Não é usado desde OQ-46: o pedido passa de `QUEUED` a `RUNNING`; o status continua no enum e no CHECK, sem migração.
- `RUNNING`: em processamento.
- `CANCELLING`: cancelamento sinalizado de um pedido enviado (OQ-29). Não é usado desde OQ-46 (leitura do integrador): só surgia ao cancelar um pedido `DISPATCHED`; o cancelamento de um pedido em execução grava `cancel_requested_at` e o pedido continua `RUNNING` até terminar `CANCELLED`. O status continua no enum e no CHECK.
- `CANCELLED`: cancelado; as datas já concluídas continuam publicadas e as seguintes não são tocadas. Num processamento Tudo cancelado depois que uma cadeia falhou, o pedido termina `CANCELLED` e mantém o código e a mensagem da primeira falha (OQ-36 item 10), além de `failed_date` e `failed_chain`; Processamentos oferece também **Solicitar novo processamento** com o escopo da cadeia que falhou, de `failed_date` até a data final original, além do novo processamento comum (OQ-40 item 6).
- `COMPLETED`: todas as datas do intervalo publicadas como **Processado**.
- `COMPLETED_WITH_ISSUES`: alguma data gravada pelo pedido ficou **Processado com pendências** (preço ausente ou contrato vencido com posição aberta), ou, num processamento Tudo, uma cadeia falhou e a outra chegou ao fim do intervalo (OQ-36). Nesse último caso, e só nele, o pedido guarda o código e a mensagem do erro, exibidos nos detalhes em Processamentos; com apenas preço ausente ou contrato vencido, eles ficam vazios. Nesse caso, Processamentos também oferece **Solicitar novo processamento**, preenchido com o escopo da cadeia que falhou (Caixa ou Posições), de `failed_date` até a data final original (OQ-40).
- `FAILED`: falha técnica inesperada em uma data (`PROCESSING_ERROR`, "Erro técnico ao processar a data.", de uma cadeia ou de nenhuma, OQ-44), ou dia anterior não processado: caixa (`CASH_PREDECESSOR_MISSING`) ou posições (`POSITIONS_PREDECESSOR_MISSING`) (§10.1, OQ-31); a data fica com status **Erro** (§10.4). Num processamento Tudo, só quando as duas cadeias falham (OQ-36).

O pedido guarda a sua primeira falha em `failed_date` e `failed_chain` (OQ-40), expostos na leitura do pedido: `failed_chain` é `CASH` ou `POSITIONS` (nunca Tudo): a cadeia que falhou; `POSITIONS` quando as duas cadeias de um Tudo falham na mesma data, como o código de erro (OQ-36 item 5); num pedido de uma só cadeia, a cadeia do pedido quando a falha é dessa cadeia; vazio com `failed_date` preenchido quando a falha não pertence a nenhuma cadeia, em qualquer escopo (escolhas do integrador); os dois são vazios se o pedido nunca falhou, e também num pedido `FAILED` encerrado por um erro não transitório ao gravar o seu término (OQ-47 item 7; nesse caso fica só a primeira falha de cadeia de um Tudo, se houver).

Rótulos na interface (OQ-20, OQ-23): `QUEUED` **Na fila**, `DISPATCHED` **Enviado**, `RUNNING` **Processando**, `CANCELLING` **Cancelando**, `CANCELLED` **Cancelado**, `COMPLETED` **Concluído**, `COMPLETED_WITH_ISSUES` **Concluído com pendências**, `FAILED` **Falhou**. Não existe status "Bloqueado": preço ausente nunca interrompe um job. Desde OQ-46, os status `DISPATCHED` e `CANCELLING` não são usados, então **Enviado** nunca aparece (leitura do integrador). As telas mostram **Cancelando** para um pedido `RUNNING` com `cancel_requested_at` preenchido (decisão do usuário, OQ-46: "ok"); é só uma regra de exibição, e o status na API continua `RUNNING`. Um segundo cancelamento responde 409 `JOB_NOT_CANCELLABLE`, "O cancelamento deste processamento já foi solicitado." (texto do worker; leitura do integrador).

Cada data tem, por cadeia, um status próprio, descrito em §10.4.

A lista de **Pendências** exibe problemas acionáveis: ativo, data necessária, motivo e ação. Problemas repetidos para a mesma obrigação são deduplicados na leitura, sem mudar nada do que está gravado (OQ-37): **preço de referência faltante** (`MISSING_REFERENCE_PRICE`) gera uma linha por (ativo, data do preço necessário), de modo que "Definir preço DI1F29 em 16/10" aparece uma vez; **contrato vencido com posição aberta** (`EXPIRED_OPEN_POSITION`) gera uma linha por ativo. Cada linha mostra a primeira data afetada. Tipos atuais (OQ-31): **preço de referência faltante** (ação: definir preço) e **contrato vencido com posição aberta** (§7.4). Dia anterior não processado não é pendência: é um erro do pedido (§10.1). Uma data com **Erro** mantém as pendências da sua publicação anterior, junto com os dados publicados anteriormente, até que a cadeia seja processada de novo na data (OQ-47 item 3).

### 10.4 Publicação por data e status das datas

- **Sem estágio** (OQ-23): o processamento percorre [A, B] em ordem de calendário e publica **cada data na sua própria transação**, diretamente nas tabelas do escopo — `cash_balances` (Caixa); `positions`, `position_metrics` e `portfolio_metrics` (Posições); todas (Tudo) — sem gravar o AUM, calculado na leitura (OQ-50 item 1). Em Tudo, enquanto as duas cadeias estão ativas, ambas são gravadas na mesma transação (OQ-36). O progresso (última data publicada) é consultável na UI.
- **Status de cada data** (OQ-23, OQ-31): `processing.date_status` guarda, para cada data corrida, o status atual de cada cadeia, **Caixa** e **Posições**, e o horário do último processamento de cada uma (`cash_processed_at`, `portfolio_processed_at`), gravado quando um pedido conclui aquela cadeia na data e vazio quando ela nunca foi processada. É a **única fonte** do status de processamento: todas as leituras (resumo, posições, série de P&L) e os dois indicadores (Caixa, Posições) vêm dele, com o horário de cada cadeia. Não se guarda o status de cada data de cada processamento; o pedido guarda só o seu status geral. Não existe status de desatualização (OQ-31).
  - sem status (ou sem linha): **Não processado**;
  - `PROCESSED`: **Processado**;
  - `PROCESSED_WITH_ISSUES`: **Processado com pendências** (preço ausente ou contrato vencido com posição aberta);
  - `RUNNING`: **Processando**. Desde OQ-50 (item 4), não é gravado: a leitura mostra Processando para as cadeias do pedido em execução na sua data corrente, `progress_date + 1` (ou `start_date` quando ainda não há progresso), e, num Tudo, só para a cadeia ainda ativa (leitura do integrador);
  - `FAILED`: **Erro** (a última tentativa falhou; a data mantém os dados publicados anteriormente e as pendências dessa publicação, OQ-47 item 3).
- **Processar a data D de uma cadeia** (OQ-23, OQ-50 item 4): uma transação curta verifica se o cancelamento foi pedido; nenhuma data é marcada como Processando. Em seguida, a transação de D bloqueia as linhas de status de D−1 e D (em ordem crescente de data), calcula D, grava as linhas publicadas de D (o AUM não é gravado: é calculado na leitura, OQ-50 item 1), substitui as pendências anteriores da cadeia nessa data pelas novas (posições: preço ausente e contrato vencido; caixa não gera pendências; OQ-26, OQ-31), registra D como progresso do pedido e define o status de D, **Processado**, ou **Processado com pendências** se D tem preço ausente ou contrato vencido com posição aberta, com o horário de processamento da cadeia. A transação de D leva a data do status antigo direto ao novo (Processado, Processado com pendências ou Erro); as colunas `*_previous` ficam sem uso.
  - Antes de calcular D, verifica a regra do predecessor (§10.1, OQ-31): se D−1 não está Processado nem Processado com pendências, nem é o estado zero da cadeia (OQ-40 item 5), D não é gravado, fica com **Erro** e o pedido termina `FAILED` (como na falha em D, abaixo). Num processamento Tudo, só a cadeia que falhou fica com **Erro** e para; a outra ainda é gravada em D, na mesma transação, e segue até o fim do intervalo (§10.1, OQ-36).
- **Falha em D** (OQ-23): a falha de uma cadeia (regra do predecessor ou erro técnico dentro da cadeia) desfaz só essa cadeia até o seu SAVEPOINT, dentro da transação de D, em qualquer escopo (escolha do integrador); na mesma transação, a cadeia fica com **Erro** em D e o código e a mensagem do erro são gravados no pedido, que termina `FAILED` (num processamento Tudo, só a cadeia que falhou para; a outra ainda é gravada em D, na mesma transação, e o pedido só termina `FAILED` se as duas falharem; OQ-36). Num processamento Tudo, D roda numa transação com um SAVEPOINT por cadeia (OQ-40): um erro técnico desfaz só a cadeia que falhou até o seu savepoint; o **Erro** dessa cadeia, o erro do pedido, as linhas da outra cadeia, o progresso e os status são gravados juntos na transação de D. Todo erro levantado pela chamada de gravação de uma cadeia pertence a essa cadeia. Uma falha que não pertence a nenhuma cadeia, fora do savepoint de todas as cadeias (por exemplo, tempo de espera de bloqueio nas linhas de status da data; lista definida pelo integrador), desfaz toda a data D, assim como um erro que derruba a conexão e não permite usar o savepoint; uma transação curta marca D com **Erro** em todas as cadeias ainda ativas no pedido, com `failed_chain` vazio, e o pedido termina `FAILED` (escolha do integrador). Uma queda do worker não é uma falha em D: o pedido é retomado quando o worker inicia (OQ-45). O pedido guarda a primeira falha em `failed_date` e `failed_chain` (OQ-40). As datas anteriores continuam publicadas; as seguintes não são tocadas.
- **Cancelamento**: §10.2. Num processamento Tudo em que uma cadeia já falhou, a data em curso é concluída, o pedido termina `CANCELLED` e o código e a mensagem da primeira falha continuam no pedido (OQ-36 item 10). **Recuperação** (OQ-45, que reverte OQ-43; OQ-46): só existe um worker, então não há lease, token de posse, dispatcher nem limite de tentativas. O worker trata uma mensagem por vez (prefetch 1) e pode confirmar (ACK) a mensagem ao recebê-la, pois ela não carrega dados (leitura do integrador); uma queda ou um SIGTERM do worker não gera reentrega pelo RabbitMQ: quando o worker inicia, antes de consumir mensagens, ele assume o pedido deixado em `RUNNING`, a única linha nesse status (`DISPATCHED` e `CANCELLING` não são mais usados, OQ-46). Nenhuma data fica gravada em Processando, então nada é restaurado (OQ-50 item 4); o pedido retoma a partir da data seguinte ao último progresso registrado (`progress_date`) (OQ-23). Num processamento Tudo, a cadeia que falhou primeiro (`failed_chain`) continua parada e só a outra segue, sem gravar nada novo (OQ-36 item 9). Um pedido encontrado no início do worker com `cancel_requested_at` preenchido (o worker parou com um cancelamento pendente) termina `CANCELLED` antes de processar qualquer data (decisão do usuário, 19/10/2026: "Keep it: a run with a cancel request found at worker restart ends CANCELLED before processing any date."; o cancelamento é cooperativo nas fronteiras de data). Em seguida a varredura periódica executa os pedidos `QUEUED` (§10.2, OQ-50 item 2). Não há vaga de pedido ativo: `calculation_state.active_request_id` não é usado e o término de um pedido não libera nada (OQ-46, leitura do integrador).
- **Nenhuma data fica em Processando** (OQ-50 item 4, que substitui OQ-26 item 4): um pedido que para (cancelado, interrompido por uma queda do worker ou encerrado por um erro) deixa cada data como estava ou como a gravou; não há o que restaurar nem linha a apagar. Uma falha em D marca D como **Erro** (acima). A leitura mostra **Processando** para as cadeias ainda ativas do pedido em execução na sua data corrente; o horário de processamento gravado da data é mantido.
- **Sem invalidação** (OQ-31): incluir ou excluir lançamento e inserir, corrigir ou remover preço apenas gravam o fato; nenhuma data é marcada e o status e o horário de processamento de cada data permanecem até o usuário processá-la de novo. Não há marcadores nem contadores de revisão (OQ-23).
- Novos processamentos são sempre uma decisão do usuário (D3, §15).
- **Limites operacionais** (OQ-5): sem tamanho máximo de intervalo; jobs mantidos como histórico; fila FIFO por `(created_at, id)`, aplicada pelo próprio worker (OQ-46); todos os valores configuráveis. Não há lease (OQ-45).

## 11. Telas e experiência do usuário

Os designs existentes no **Aura Build** são a base visual e devem ser implementados, não reconstruídos como um aplicativo de demonstração separado. Eles estão no Figma (Carteira, Ativos, Lançamentos, Central de Controle → Pendências) e no HTML clicável da Central de Controle (Processamentos); são preliminares e serão refinados durante o desenvolvimento. Dados e funcionalidades prevalecem: onde o design diverge desta especificação, valem as decisões OQ-19 e OQ-20. UI inteira em **pt-BR**, com React, Mantine e TanStack Query. Durante o desenvolvimento, o frontend real pode usar respostas simuladas via **MSW**, seguindo contratos de API revisáveis.

### 11.1 Central de Controle

Duas abas: **Pendências** e **Processamentos**.

- **Pendências:** problemas realmente identificados pela validação/processamento, não uma lista de todos os dias sem cotação. Somente os dois tipos de §10.3 (OQ-31); falha técnica ou dia anterior não processado (`FAILED`) aparece em Processamentos, não como pendência (OQ-19). Ação **Definir preço** conduz à entrada/correção da referência.
- **Processamentos:** escolher datas e escopo (Caixa, Posições ou Tudo; OQ-21), pré-visualizar o intervalo exato [A, B] (dias a processar, com aviso quando A−1 não está processado e o pedido terminaria com erro em A, OQ-31; sem "período efetivo" expandido), enfileirar, acompanhar progresso e status, ver erros e cancelar pedidos; cancelar e enfileirar são ações separadas, sem cancelar e substituir (OQ-30). Os jobs continuam existindo no histórico após conclusão/cancelamento (OQ-20). Os status dos pedidos são os oito de §10.3.
  - Cada data é publicada na sua própria transação (§10.4, OQ-23): os detalhes de um job cancelado ou com falha informam a última data publicada, que as datas até ela continuam publicadas e que as seguintes não foram tocadas; na falha, mostram a data com **Erro**, o código e a mensagem.
  - Um job cancelado ou com falha oferece **Solicitar novo processamento**, que preenche o formulário a partir da data com falha ou, para um job cancelado, da primeira data não alcançada, até a data final original (OQ-23). Um job **Concluído com pendências**, ou um job Tudo **Cancelado**, em que uma cadeia falhou também oferece **Solicitar novo processamento**, preenchido com o escopo da cadeia que falhou (Caixa ou Posições), de `failed_date` até a data final original; no job cancelado, o novo processamento comum, a partir da primeira data não alcançada, continua disponível; os detalhes do job mostram `failed_date` e `failed_chain` (OQ-40 itens 3 e 6).
  - Pedidos sobrepostos ou repetidos continuam permitidos; não há coluna "Motivo".
- Sem KPIs financeiros redundantes na Central de Controle.

### 11.2 Ativos

- Códigos de produto e instrumento são gravados sem espaços nas pontas e em maiúsculas (`' di1f27 '` vira `DI1F27`); a busca de produtos e instrumentos ignora maiúsculas e acentos (OQ-33).
- Navegar pelo cadastro `tipo → classe → produto → instrumento`. O catálogo mostra somente o que a API devolve (tipos como abas, produtos reais); nenhum produto ilustrativo (OQ-19).
- Ver contrato, especificações, datas e referências existentes. A lista de contratos de um produto mostra a última observação de referência (PU, taxa) **sempre ao lado da sua data**, nunca como preço de hoje. Desde OQ-48 o campo vem preenchido: o preço de referência preferencial (Manual antes de B3) da data mais recente com preço do contrato, com data, PU, taxa e fonte, nas colunas Último PU, Taxa a.a. e Data ref.; a tela mostra "—" só para um contrato sem preço (OQ-33, OQ-48).
- A tela de contrato permite cadastro/inspeção/correção de preço de referência de data específica. **Não há calculadora taxa ↔ PU** nessa tela (OQ-19): o usuário informa PU ou taxa e o valor complementar é calculado ao salvar.
- A página do produto também registra e remove preços (OQ-48): um botão **Registrar preço** acima da lista de contratos abre um formulário com contrato, data e PU ou taxa; cada linha de contrato tem um menu "…" com **Registrar preço** (contrato já preenchido) e **Remover preço** (escolher a data e depois a fonte a remover, como na tela de contrato). A tela de contrato mantém o seu botão. Só frontend: usa os `POST` e `DELETE /reference-prices` existentes.
- Calendário/serie de preços deve distinguir observações reais de dias sem observação; **não inventar** preços interpolados. Mostra a **Fonte** (Manual/B3) da observação preferencial; o menu da linha oferece **Corrigir** (mesmo `POST` de registrar: apaga a observação atual e grava a nova, com id novo) e **Remover** (apaga a observação). Não há "Ver revisões" (OQ-25, OQ-26).
- Um PU informado manualmente não precisa gerar obrigatoriamente um segundo campo visível para a taxa implícita, embora o motor possa calculá-la quando necessário. Quando a taxa existir, ela é exibida ao lado do PU (OQ-19).

### 11.3 Lançamentos

- Visualizar os lançamentos — operações e movimentações de caixa em uma única lista, na ordem `(data, hora, seq)` (OQ-24) — com filtro de intervalo inclusivo, busca e paginação (§12).
- Registrar compra, venda, aporte e retirada por formulários/drawers apropriados; todos exigem data e hora.
- O formulário de aporte e retirada tem o campo opcional **Descrição** (até 200 caracteres); a lista mostra a descrição de cada movimentação, "—" quando vazia (OQ-51). A busca também encontra uma movimentação pela sua descrição, sem diferenciar maiúsculas nem acentos.
- Distinguir **tipo de instrumento** de **tipo de lançamento**.
- Excluir um lançamento ou vários com confirmação, sem motivo e em uma única transação (tudo ou nada); a exclusão é definitiva, sem trilha de auditoria (OQ-32); **não editar** lançamentos existentes (OQ-24).
- Exibir data/hora efetiva e valores com formatação brasileira. Cada operação mostra PU **e** taxa de execução: o valor informado e o calculado pelo backend ao salvar (OQ-19).
- A coluna **Financeiro** mostra o `cash_amount` de cada lançamento, isto é, seu efeito no caixa: numa operação, −quantidade × PU de execução (compra negativa, venda positiva); numa movimentação, o valor (aporte positivo, retirada negativa). Não é valor de mercado; o cabeçalho tem a dica "Efeito no caixa: compra negativa, venda positiva; aporte positivo, retirada negativa." (usuário, 2026-10-19: "Financeiro is good"; o enunciado chama esse número de "Financeiro operação").
- Faixa de caixa (OQ-19): **Caixa D0** é o saldo publicado na data final do período selecionado e **Caixa D−1** o do dia anterior, lidos do caixa publicado (`cash_balances`, via resumo da carteira) e marcados conforme o status de **caixa** de cada data em `processing.date_status`, com "Processado em dd/mm/aaaa hh:mm" quando processado (§10.4; OQ-21, OQ-23, OQ-31).

### 11.4 Carteira

- Seleção de **uma data**; consulta a posições e métricas anteriormente publicadas, sem recalcular no GET. Uma data posterior a hoje é recusada com 422 `FUTURE_DATE`, inclusive a data final da série de P&L (OQ-35).
- Indicadores: **Saldo em caixa**, **AUM/Patrimônio**, **P&L diário**, **P&L de posições** e **P&L de operações**. Numa data com **Erro** ou **Processando**, o resumo mostra os valores gravados da publicação anterior com o indicador de status da cadeia; sem publicação anterior, os valores ficam indisponíveis. O AUM é a exceção: fica indisponível (`null`) a menos que as duas cadeias da data estejam Processado ou Processado com pendências (OQ-38, OQ-40), então uma cadeia com Erro ou Processando o deixa indisponível. O gráfico não muda: esses dias somam 0 (OQ-41 item 4); a diferença é deliberada (OQ-47 item 4).
- **Gráfico compacto de P&L acumulado** no nível da carteira, desenhado em todos os dias corridos do período (OQ-41).
- O gráfico termina sempre na data selecionada da Carteira (mesma publicação dos indicadores); o usuário escolhe apenas a **data inicial**, anterior a essa data. Padrão: os 30 dias corridos que terminam na data. A data inicial fica na URL (`?pnl_start=`); valor inválido é ignorado (OQ-27).
- O gráfico desenha `range_cumulative_pnl`, o agregado diário da data inicial até a data da Carteira: Σ `daily_pnl` da data inicial (inclusive) até D, somado pelo backend a cada consulta. O frontend só desenha. O P&L acumulado desde o início (`cumulative_pnl`) continua no resumo da API (OQ-31 item 8, OQ-49); desde OQ-48 o título do card não o mostra (item abaixo). Desde OQ-41, a série tem um ponto por dia corrido do período e `range_cumulative_pnl` nunca é `null`: um dia não processado (status `NOT_PROCESSED`, "Não processado"; None na view Python, com `daily_pnl` nulo) ou com `daily_pnl` nulo soma 0, e a linha segue plana. Um dia soma o seu `daily_pnl` somente quando o status da cadeia de posições é `PROCESSED` ou `PROCESSED_WITH_ISSUES` **e** o `daily_pnl` não é `null`; nos demais casos (não processado, `FAILED`, `RUNNING` ou dia processado com `daily_pnl` nulo por preço faltante) soma 0. Um ponto `FAILED` ou `RUNNING` mostra o seu status com `daily_pnl` `null`, mesmo que exista uma linha anterior em `portfolio_metrics` (OQ-41 item 4, OQ-49). O tooltip do gráfico mostra o status do dia ("Não processado", "Erro", "Processando") ou "P&L diário indisponível" para um dia processado com `daily_pnl` nulo, e o card mostra uma nota curta quando algum dia do período não está completo, isto é, soma 0 pela regra do item 4 (OQ-41 item 5). Esta é a **única exceção deliberada** a "`null`, nunca zero" (§8.3), e vale só para a soma do gráfico e para o título do card, que mostra a mesma soma desde OQ-48 item 3, com a mesma nota de período incompleto: o P&L diário do próprio dia continua indisponível, e o `cumulative_pnl` desde o início e os indicadores continuam indisponíveis a partir da primeira lacuna.
- O valor em destaque do card **P&L acumulado** é o total do período do gráfico (OQ-48): o `range_cumulative_pnl` da data selecionada, último ponto do gráfico (os dias sem P&L somam 0, OQ-41), rotulado com a data inicial do gráfico. O `cumulative_pnl` desde o início guardado não muda: continua no resumo, indisponível a partir da primeira lacuna (§8.3), e não vem no ponto da série (OQ-49).
- Tabela de posições consolida: ativo, vencimento, quantidade, PU médio, taxa média, PU de referência, taxa de referência (quando disponível), **valor de mercado** (`financial_total`), P&L posições e P&L operações. PU, taxa e fonte de referência vêm da observação preferencial atual na tabela de preços (OQ-30).
- Os resultados calculados por ativo e o total do portfólio derivam da mesma publicação coerente. Se um preço mudou depois da publicação, a tabela mostra o PU novo ao lado dos valores antigos e a data mantém o seu status de processamento até ser reprocessada (OQ-30, OQ-31). **Desde OQ-50 (item 3):** a linha cujo preço de referência atual de D **ou de D−1** (o P&L de posições usa os dois; leitura do integrador) foi cadastrado depois do processamento das posições da data (o `created_at` do preço é posterior ao `portfolio_processed_at` de D; um preço gravado de novo é uma linha nova com novo `created_at`, OQ-25) é marcada "Preço alterado após o processamento — reprocesse". Nada é gravado: a data mantém o seu status. Um preço removido não deixa preço atual para comparar, então a linha fica sem PU e sem marca (leitura do integrador).
- Exibir claramente métricas ausentes/incompletas ou não processadas; oferecer caminho contextual para Pendências ou Processamentos.
- Os indicadores de status **Caixa** e **Posições** da data vêm de `processing.date_status` (§10.4, OQ-23) e mostram "Processado em dd/mm/aaaa hh:mm", o horário do último processamento de cada cadeia (OQ-31).
- Não listar caixa como linha de posição de ativo. Não expor P&L realizado/não realizado ou P&L acumulado por ativo na tabela padrão.

## 12. Regras de API e integração com frontend

- API de Carteira devolve dados agregados para a tabela em **uma resposta**, sem obrigar o React a coordenar pedidos a Asset, Prices, Portfolio e PnL.
- Respostas identificam data, estado de processamento/completude e valores ausentes com `null` (não zero) (exceção: `range_cumulative_pnl`, OQ-41). O status de cada cadeia na data e o horário do seu último processamento vêm de `processing.date_status` (OQ-23, OQ-31).
- Valores monetários/PU/taxas trafegam como números decimais representados por **strings**, para preservar precisão no frontend.
- Processamentos expõem criação, listagem, status/progresso (última data publicada e erro, se houver) e cancelamento. O frontend pode consultar status periodicamente enquanto houver trabalho.
- **Paginação** (usuário, 18/10/2026): listas paginadas recebem `?limit=&cursor=` e devolvem `{items, next_cursor}`, com cursor por chave: `(data, hora, seq)` para lançamentos e `(created_at, id)` para processamentos. `limit` vale 50 por padrão e aceita de 1 a 200; fora disso, 422 `VALIDATION_ERROR` no campo `limit`, "Use um limite entre 1 e 200." (OQ-37).
- Lançamentos usam uma única rota para os dois tipos, que substitui as rotas separadas de operações e de movimentações; a exclusão múltipla é um único pedido com a lista de ids (OQ-24).
- **Erros** (OQ-15) seguem `application/problem+json` (RFC 9457) com `errors: [{code, message, field}]`; mensagens em pt-BR, códigos em inglês, catálogo em `interfaces.md`.
- O gráfico de P&L acumulado da Carteira usa `GET /portfolio/pnl` (OQ-16), com `end_date` = data da Carteira e `start_date` escolhida pelo usuário (OQ-27). Cada ponto traz `date`, `daily_pnl`, `range_cumulative_pnl` e o status da cadeia de posições (OQ-31 item 8, OQ-49). Desde OQ-41, há um ponto para cada dia corrido de [`start_date`, `end_date`]; num dia não processado, `status` é `NOT_PROCESSED` ("Não processado"; None na view Python) e `daily_pnl` é `null`, e `range_cumulative_pnl` nunca é `null`. Um dia soma o seu `daily_pnl` só quando o status de posições é `PROCESSED` ou `PROCESSED_WITH_ISSUES` e o `daily_pnl` não é `null`; senão soma 0. Um ponto `FAILED` ou `RUNNING` mostra o seu status com `daily_pnl` `null`, mesmo que exista uma linha anterior em `portfolio_metrics` (OQ-41 item 4). O ponto não traz `cumulative_pnl`, `pnl_status` nem `published_at`.
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
9. Mudança histórica em lançamento/PU sem invalidação (OQ-31): a gravação só salva o fato; o status e o horário de processamento de todas as datas ficam inalterados e nenhum job é criado.
10. Dois pedidos com intervalos sobrepostos, cancelamento na fila, cancelamento em execução (a data em curso é publicada, as seguintes não são tocadas, `CANCELLED`; durante a última data, `COMPLETED` ou `COMPLETED_WITH_ISSUES`) e novo pedido enfileirado como ação separada (sem cancelar e substituir, OQ-30). Cancelar pedido terminado é recusado (409); intervalo que termina após hoje é recusado (422) (OQ-29). O worker pega o pedido `QUEUED` mais antigo e o marca `RUNNING`, sem `DISPATCHED`; cancelamento na fila e a retirada pelo worker disputam o mesmo bloqueio de linha e um só vence (OQ-46).
11. Publicação por data (OQ-23): falha em D deixa D com **Erro**, mantém publicadas as datas anteriores e não toca as seguintes; regra do predecessor (OQ-31: D é processado somente com D−1 Processado, com ou sem pendências, ou estado zero; senão D fica com **Erro** e o pedido termina `FAILED`, ou `COMPLETED_WITH_ISSUES` num Tudo em que só uma cadeia falha, ver caso 14); o horário de processamento de cada cadeia é gravado com o status de D; uma gravação durante o job só grava o fato, sem marcar nada nem interromper o job; mensagem perdida, duplicada ou reentregue (a mensagem só identifica o pedido para rastreio; o worker pega o `QUEUED` mais antigo, OQ-50 item 2); recuperação na inicialização do único worker a partir do último progresso (nenhuma data fica em Processando, então nada é restaurado, OQ-50 item 4), um pedido com `cancel_requested_at` encerrado `CANCELLED` e depois a varredura periódica executando os pedidos `QUEUED` (OQ-45, OQ-50 item 2); "Solicitar novo processamento" a partir da data com falha ou da primeira não alcançada.
12. Resposta consolidada da Carteira coerente por data e status; mocks em conformidade com APIs.
13. Cadeias separadas (OQ-21, OQ-23): um job Tudo grava as duas cadeias e o AUM de cada data na mesma transação; `aum = caixa + valor de mercado` após publicar só Caixa, só Posições e Tudo, quando a outra cadeia da data está processada (Processado ou Processado com pendências); com a outra cadeia em **Erro** ou não processada, o AUM é `null` (OQ-38). Desde OQ-50 o AUM não é gravado: o teste verifica `aum = caixa + valor de mercado` na leitura.
14. Predecessor por dia (OQ-31): Caixa com A−1 não processado e lançamentos anteriores deixa A com **Erro** e termina `FAILED` (`CASH_PREDECESSOR_MISSING`, "Dia anterior não processado") sem tocar as datas seguintes; Posições ou Tudo com posições de A−1 não processadas e operações anteriores termina `FAILED` (`POSITIONS_PREDECESSOR_MISSING`); em Tudo (OQ-36), só a cadeia que falhou fica com **Erro** em A e suas datas seguintes não são tocadas, a outra ainda é gravada em A, na mesma transação, e segue até o fim do intervalo e o pedido termina `COMPLETED_WITH_ISSUES` com o código e a mensagem do erro; com as duas falhando, termina `FAILED`, com `POSITIONS_PREDECESSOR_MISSING` se falharem na mesma data; um erro técnico numa cadeia de um job Tudo tem o mesmo efeito e o pedido guarda o primeiro erro; A−1 com **Erro** conta como não processado; sem status da cadeia em nenhuma data anterior a A e sem lançamentos do tipo da cadeia antes de A, A é processado a partir do estado zero (OQ-40 item 5).
15. Dia sem ativo esperado (OQ-22): posição zerada em D e D+1 sem ativos publica P&L 0, AUM = caixa quando a cadeia de caixa está processada nessa data, senão `null` (OQ-38), e P&L acumulado levado adiante.
16. Lançamento único (OQ-24): operações e movimentações da mesma data seguem `(data, hora, seq)` entre os dois tipos; a exclusão múltipla mista é tudo ou nada e apaga as linhas de `ledger.entries` (OQ-32); um id inexistente ou já excluído responde 404 `NOT_FOUND` e nada é excluído; depois da exclusão, os lançamentos não aparecem em nenhuma leitura e os resultados já processados ficam inalterados.
17. Preços sem revisões (OQ-25): um novo preço no mesmo (instrumento, data, fonte) apaga o atual e grava o novo (id novo); remover o MANUAL faz o B3 prevalecer; gravar de novo ou remover um preço já usado é permitido e não marca nada (OQ-31). Desde OQ-30, a Carteira mostra o PU, a taxa e a fonte atuais da tabela de preços ao lado dos valores antigos, e a data mantém o seu status de processamento até o reprocessamento (OQ-31).
18. AUM após falha parcial (OQ-36, OQ-38): um job Tudo em que uma cadeia falha em D deixa `aum` `null` em D e nas datas seguintes do intervalo, embora a outra cadeia seja gravada.
19. Caixa sobre posições com Erro (OQ-38): um job Caixa sobre uma data cujas posições estão com **Erro** grava o caixa e deixa `aum` `null`.
20. Buraco na cadeia (OQ-37 item 4): D−1 sem status enquanto uma data anterior da cadeia tem status (inclusive Erro) deixa D com **Erro** (`CASH_PREDECESSOR_MISSING` ou `POSITIONS_PREDECESSOR_MISSING`) sem consultar o Lançamentos.
21. Deduplicação de Pendências (OQ-37): preço de referência faltante aparece uma vez por (ativo, data do preço necessário), de modo que "Definir preço DI1F29 em 16/10" aparece uma vez; contrato vencido com posição aberta aparece uma vez por ativo.
22. Limite de página (OQ-37): `limit=0` e `limit=201` respondem 422 `VALIDATION_ERROR` no campo `limit`.
23. Leituras da Carteira após hoje (OQ-35): resumo e posições com `date` após hoje, e série de P&L com `end_date` após hoje, respondem 422 `FUTURE_DATE`.
24. Erro técnico de uma cadeia em Tudo (OQ-40): um erro técnico numa cadeia em D desfaz só essa cadeia até o seu savepoint e a deixa com **Erro** em D; a outra cadeia é gravada em D, na mesma transação, e segue até o fim do intervalo; o pedido termina `COMPLETED_WITH_ISSUES` com `failed_date` = D e `failed_chain` = a cadeia que falhou.
25. Falha fora de uma cadeia (OQ-40): uma falha que não pertence a nenhuma cadeia em D (fora do savepoint de todas as cadeias, por exemplo tempo de espera de bloqueio nas linhas de status da data) desfaz toda a data D; D fica com **Erro** em todas as cadeias ainda ativas no pedido (nas duas, se nenhuma tinha parado) e o pedido termina `FAILED`; uma cadeia que já tinha parado não é tocada em D.
26. Estado zero com só Erro na cadeia (OQ-40 item 5): o único status do caixa é **Erro** em 01/10, sem lançamentos; um processamento de Caixa em 05/10 deixa 05/10 com **Erro** (`CASH_PREDECESSOR_MISSING`) sem consultar o Lançamentos, pois uma data anterior da cadeia tem status.
27. Gráfico de P&L acumulado com dias sem P&L (OQ-41): um gráfico de 30 dias que começa antes do primeiro dia processado tem um ponto por dia; um dia não processado (status `NOT_PROCESSED`, "Não processado") soma 0, e a linha segue plana (`range_cumulative_pnl` igual ao do dia anterior, ou 0 antes do primeiro dia processado); um dia processado com preço de referência faltante também soma 0 à linha, enquanto o seu próprio P&L diário aparece indisponível e o `cumulative_pnl` desde o início, no resumo, fica `null` a partir dele. Exemplo: D1 processado com P&L diário 100, D2 não processado, D3 processado com −40, D4 com status `FAILED` ("Erro") → `range_cumulative_pnl` 100, 100, 60, 60; o ponto de D4 traz `daily_pnl` `null`.

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
- Mudanças apenas gravam o fato, sem invalidação (OQ-31); processamento da carteira ocorre **sob comando explícito do usuário**.
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
- PU `D-1` lido da tabela de preços (OQ-9, OQ-30); preço alterado depois do processamento não marca nada (OQ-31).
- Ativo esperado: `Q[D-1] != 0` ou operação em D (OQ-10).
- Intervalo exato [A, B], sem expansão (OQ-11); predecessor verificado por dia desde OQ-31.
- Status de processamento de cada data (OQ-12, substituído por OQ-23 e OQ-31).
- Hora obrigatória em todo lançamento; ordem `(data, hora, seq)` entre operações e movimentações (OQ-13, OQ-24).
- Erros em problem+json (RFC 9457) com catálogo de códigos (OQ-15).
- `GET /portfolio/pnl` alimenta o gráfico de P&L acumulado (OQ-16).
- Gráfico de P&L acumulado da Carteira: só data inicial (anterior à data da Carteira, padrão 30 dias, na URL); termina sempre na data da Carteira (usuário, 18/10/2026, sessão do frontend; OQ-27).
- Lane H é dona de `platform/**` (OQ-17).
- Caixa e posições são duas cadeias processáveis separadamente (escopos Caixa, Posições e Tudo), cada uma com seu status por data (OQ-23); caixa publicado em `cash_balances`; AUM recalculado por quem publica (OQ-21).
- Dia sem ativo esperado é processado com P&L 0 e acumulado levado adiante; sem processo automático à meia-noite (OQ-22). A recusa ao iniciar e a pendência de predecessor foram substituídas pela regra do predecessor por dia (OQ-31).
- Arquitetura (usuário, 18/10/2026): `infrastructure/` contém persistência e outros adaptadores de saída; consumidores e handlers RabbitMQ de um módulo ficam em `presentation/messaging/`, a infraestrutura RabbitMQ compartilhada em `platform/messaging/`, e a lógica de processamento em `application/`. O domínio é determinístico e sem I/O nem efeitos colaterais (sem arquivo, rede, banco, mensageria, ambiente ou relógio do sistema); utilitários puros da biblioteca padrão (`datetime`, `Decimal`, `Enum`, `dataclasses`) são permitidos. O domínio não faz logging (que pertence às camadas de aplicação, infraestrutura e apresentação) e comunica falhas por exceções e resultados explícitos; não gera aleatoriedade internamente: um cálculo que precise dela (ex.: Monte Carlo) recebe uma semente explícita ou um gerador injetado.

- Desvios e interpretações do enunciado registrados em §15 (OQ-18).
- Design × especificação (usuário, 18/10/2026, sessão do frontend; OQ-19, OQ-20): dados e funcionalidades da especificação prevalecem sobre o design preliminar; Carteira com P&L de posições e de operações; tipos de pendência de §10.3 (dois desde OQ-31); faixa Caixa D0/D−1 em Lançamentos; catálogo só com dados da API; última referência sempre com sua data; coluna Fonte no calendário, com menu Corrigir e Remover (OQ-25); sem calculadora taxa ↔ PU nem prévia (valor complementar calculado ao salvar); intervalo exato [A, B]; oito status com rótulos em português e sem "Bloqueado" (OQ-23); publicação por data (OQ-23); novo processamento a partir da data com falha ou da primeira data não alcançada (OQ-23); sem cancelar e substituir (OQ-30).
- Processamento dia a dia (OQ-23): sem estágio, cada data publicada na sua própria transação; `processing.date_status` guarda o status atual de cada data por cadeia (nomes e status desde OQ-31: Processado, Processado com pendências, Processando, Erro; sem status = Não processado) e é a única fonte do status de processamento; sem marcadores, revisões nem `SUPERSEDED`; falha em D deixa D com Erro e não toca as datas seguintes; cancelamento publica a data em curso; recuperação a partir do último progresso.
- Lançamento único (OQ-24): `ledger.entries` para operações e movimentações de caixa, hora obrigatória, `seq` comum, valor de caixa com sinal; exclusão sem motivo, em uma única transação (definitiva desde OQ-32); rotas `/ledger/entries`.
- AUM sem status (OQ-28): `aum` é apenas o valor (caixa + valor de mercado, `null` se um lado falta); a tela mostra os status das duas cadeias.
- Intervalo de processamento que termina após hoje é recusado (`FUTURE_DATE`); cancelar pedido enviado o leva a `CANCELLING`, e cancelar pedido em `CANCELLING` ou terminado é recusado (409) (OQ-29). Desde OQ-46 não há pedido enviado nem `CANCELLING`; cancelar pedido terminado continua recusado (409). O RabbitMQ continua como o sinal de acordar o worker (OQ-46 item 10, decisão do usuário): o PostgreSQL é a fonte da verdade dos pedidos, da ordem e dos status; o outbox publica com confirmação, uma mensagem perdida é coberta pela próxima mensagem ou pelo próximo início do worker, e não há polling; LISTEN/NOTIFY ou polling foram rejeitados. É onde a mensageria agrega valor (§8 do enunciado): a API responde na hora e o processamento roda fora da requisição, num processo separado.
- Preços de referência sem revisões (OQ-25): uma observação por instrumento, data e fonte; um novo preço no mesmo (instrumento, data, fonte) apaga o atual e grava o novo (id novo; usuário, 19/10/2026); remoção apaga; rastreio pela tabela de preços desde OQ-30.
- Revisão dos contratos W0.3c (usuário, 19/10/2026, sessão do integrador; OQ-30): preços somente na tabela de preços (a Carteira mostra PU, taxa e fonte da observação preferencial atual; `position_metrics` sem PU de referência nem fonte; PU `D-1` da tabela de preços); posições de A−1 não publicadas recusam o job ao iniciar (`POSITIONS_PREDECESSOR_MISSING`; substituído pela regra por dia de OQ-31); sem cancelar e substituir: cancelar e enfileirar são ações separadas.
- Sem desatualização (usuário, 19/10/2026, sessões Lead Backend e do integrador; OQ-31): lançamentos e preços apenas gravam o fato, sem invalidação nem `FinancialResultInvalidator`; status das datas por cadeia `PROCESSED` Processado, `PROCESSED_WITH_ISSUES` Processado com pendências, `RUNNING` Processando, `FAILED` Erro, sem status = Não processado; `cash_processed_at` e `portfolio_processed_at` em `processing.date_status`, expostos no resumo e nas posições (a série de P&L não, desde OQ-49) e exibidos como "Processado em dd/mm/aaaa hh:mm"; regra do predecessor por dia (D−1 não processado deixa D com Erro, `CASH_PREDECESSOR_MISSING` ou `POSITIONS_PREDECESSOR_MISSING`, e o pedido termina `FAILED`; o item 7, sobre Tudo, foi substituído por OQ-36); série de P&L só com a cadeia de posições e `range_cumulative_pnl` somado pelo backend a partir da data inicial, desenhado no gráfico da Carteira (item 8); pendências só de preço ausente e contrato vencido com posição aberta, sem `processing.issues.chain`. O `null` de `range_cumulative_pnl` do item 8 foi substituído por OQ-41.
- Exclusão definitiva de lançamentos (usuário, 19/10/2026, sessões de Lançamentos e do integrador; OQ-32): `DELETE` real em `ledger.entries`, confirmada, sem motivo, tudo ou nada; id inexistente ou já excluído → 404 `NOT_FOUND` e nada é excluído; sem trilha de auditoria nem `deleted_at`/`deletion_batch_id`; regras de "lançamento ativo" passam a valer para todo lançamento. Substitui a exclusão lógica de OQ-24 item 4; não é desvio do enunciado, que não exige exclusão lógica (§15).
- Regras HTTP de Ativos (usuário, 19/10/2026, sessões de Ativos e do integrador; OQ-33): códigos sem espaços nas pontas e em maiúsculas; id inexistente no corpo da requisição → 422 `VALIDATION_ERROR` no campo, 404 `NOT_FOUND` só para o recurso do caminho (exceção: os ids da exclusão de lançamentos, OQ-32); busca por substring sem diferenciar maiúsculas nem acentos; `last_reference` sempre nulo por ora ("—"), preenchido desde OQ-48.
- Precificação (usuário, 19/10/2026, sessão de Precificação; OQ-34): a calculadora DI1 precifica só instrumentos do produto de código `DI1` (sem diferenciar maiúsculas); outro produto, ou instrumento sem vencimento ou valor de face, é recusado com 422 no campo `asset_id`; os erros usam os nomes de campo da precificação (`asset_id`, `reference_date`, `pu`, `rate`) e cada chamador os traduz para os seus (Prices: inalterado, os campos do seu pedido já usam esses nomes).
- Leituras da Carteira após hoje (usuário, 19/10/2026, sessão do integrador; OQ-35): resumo, posições e série de P&L com data (ou data final) posterior a hoje são recusados com 422 `FUTURE_DATE`.
- Falha de uma cadeia em Tudo (usuário, 19/10/2026, sessões de Processamento e do integrador; OQ-36): a cadeia que falha em D (predecessor ou erro técnico) fica com Erro em D e não toca as datas seguintes; a outra ainda é gravada em D, na mesma transação, e segue até o fim do intervalo, em ordem, uma transação por data, sem execução paralela; AUM nulo onde falta uma cadeia; o pedido termina `COMPLETED_WITH_ISSUES` com o código e a mensagem da primeira falha, e `FAILED` só se as duas cadeias falharem. `COMPLETED_WITH_ISSUES` pode ter erro só nesse caso. A outra cadeia ainda é gravada em D, na mesma transação; a recuperação retoma após `progress_date` e mantém parada a cadeia que tem uma data com Erro em [`start_date`, `progress_date`] neste pedido, lido de `date_status`, sem nada novo gravado; um cancelamento depois da falha de uma cadeia conclui a data em curso e termina `CANCELLED`, mantendo o código e a mensagem da primeira falha. Substitui OQ-31 item 7; Caixa e Posições isolados não mudam.
- Pendências, paginação e leitura de existência no Ledger (usuário, 19/10/2026, sessões de Processamento e do integrador; OQ-37): Pendências deduplicadas na leitura, sem mudar o que está gravado — preço faltante uma linha por (ativo, data do preço necessário), contrato vencido uma linha por ativo, cada linha com a primeira data afetada; `limit` das listas paginadas (lançamentos e histórico de processamentos) vale 50 por padrão, de 1 a 200, fora disso 422 `VALIDATION_ERROR` em `limit` (altera OQ-26); `ledger.public` ganha `EntryType` (TRADE, CASH) e `LedgerReader.has_entries_on_or_before(day, *, entry_type=None)` para a verificação do estado zero (OQ-31), implementado pela lane C.
- AUM após falha parcial (usuário, 19/10/2026, sessões de Processamento e do integrador; OQ-38): o AUM da data é `null` quando a outra cadeia não está Processado nem Processado com pendências; num Tudo é calculado depois das duas cadeias; o Processamento informa ao gravador da Carteira se a outra cadeia está processada.
- Pré-visualização com as duas cadeias (usuário, 19/10/2026, sessão de Processamento; OQ-39): `GET /processing/preview` devolve `predecessor.cash` e `predecessor.positions` em qualquer escopo; só as cadeias do escopo decidem o aviso, aplicado pelo frontend. A opção recomendada era anular a cadeia fora do escopo; o usuário escolheu manter as duas.
- Revisão do PR #54 (usuário, 19/10/2026, sessão Lead Backend; OQ-40): em Tudo, D roda numa transação com um SAVEPOINT por cadeia; um erro técnico desfaz só a cadeia que falhou, que fica com Erro, e a outra é gravada em D com AUM, progresso e status na mesma transação; uma falha que não pertence a nenhuma cadeia deixa D com Erro em todas as cadeias ainda ativas no pedido e o pedido `FAILED`. O AUM segue o status da outra cadeia na data, qualquer que seja o pedido que a gravou. O pedido guarda `failed_date` e `failed_chain` (migração 0006), e Concluído com pendências com uma cadeia que falhou oferece Solicitar novo processamento com o escopo dessa cadeia a partir de `failed_date`. Estado zero de uma cadeia em D (corrigido pelo usuário, OQ-40 item 5): nenhuma data anterior a D tem status da cadeia (Processado, Processado com pendências, Processando ou Erro) e nenhum lançamento do tipo da cadeia até D−1; as regras de OQ-37 (D−1 com Erro ou Processando, ou buraco) valem antes, e o Lançamentos só é consultado quando a cadeia não tem status antes de D. Um Tudo cancelado depois da falha de uma cadeia mantém `failed_date` e `failed_chain` e também oferece o novo processamento da cadeia que falhou, de `failed_date` até a data final original, além do novo processamento comum (OQ-40 item 6).
- Gráfico de P&L acumulado com zero nos dias sem P&L (usuário, 19/10/2026, sessões do frontend e do integrador; OQ-41): `GET /portfolio/pnl` devolve um ponto por dia corrido de [`start_date`, `end_date`]; num dia não processado o status é `NOT_PROCESSED` ("Não processado"; None na view Python) e `daily_pnl` é `null` (desde OQ-49 o ponto não traz `published_at`, `pnl_status` nem `cumulative_pnl`); `range_cumulative_pnl` soma 0 nos dias não processados ou com `daily_pnl` nulo e nunca é `null`. Única exceção deliberada a "`null`, nunca zero", só na soma do gráfico; o P&L diário do dia, o `cumulative_pnl` desde o início, os indicadores e os status não mudam. Substitui o `null` de OQ-31 item 8. Depois (sessão Lead Backend, 19/10/2026; itens 4 e 5): um dia soma o seu `daily_pnl` só com status de posições `PROCESSED` ou `PROCESSED_WITH_ISSUES` e `daily_pnl` não nulo, senão soma 0 (inclusive `FAILED` e `RUNNING`, cujo ponto traz o status e `daily_pnl` `null` (desde OQ-49 sem `published_at`, `cumulative_pnl` nem `pnl_status`)); o tooltip mostra o status do dia ou "P&L diário indisponível", e o card mostra uma nota quando algum dia do período não está completo.
- Leitura de preços com datas futuras (usuário, 19/10/2026, sessões do integrador e Lead Backend; OQ-42): `GET /reference-prices` aceita qualquer intervalo, inclusive depois de hoje, e simplesmente não devolve preços nessas datas; gravações continuam recusando datas futuras (OQ-14) e as leituras da Carteira seguem OQ-35.
- Limite de tentativas de recuperação (usuário, 19/10/2026, sessão Lead Backend; OQ-43): os redespachos após lease vencido (`attempt_count`) têm limite configurável, 3 por padrão (3 novos claims depois do primeiro, no máximo 4 no total; leitura do integrador); ao ultrapassá-lo o pedido termina `FAILED` com `RECOVERY_EXHAUSTED` e a mensagem "Processamento interrompido após repetidas falhas de recuperação.", as datas em Processando voltam ao status anterior e o pedido ativo é liberado. **Revertido por OQ-45:** não há limite de recuperação e `RECOVERY_EXHAUSTED` foi aposentado.
- Código do erro técnico (usuário, 19/10/2026, sessão Lead Backend; OQ-44): a falha técnica de uma cadeia, ou de nenhuma, em D grava no pedido `error_code` `PROCESSING_ERROR` com a mensagem "Erro técnico ao processar a data.", exibida em Processamentos (OQ-36 item 6).
- Um único worker (usuário, 19/10/2026, sessões Lead Backend e integrador; OQ-45; substituído por OQ-46 no que diz respeito ao dispatcher): o sistema roda exatamente um worker de processamento, mais o relay do outbox; o dispatcher continua um processo próprio, com uma réplica, que despacha o pedido `QUEUED` mais antigo só quando `active_request_id` é nulo, via outbox → relay → RabbitMQ, e, como salvaguarda, libera a vaga deixada num pedido já terminado (leitura do integrador). Sem lease, sem token de posse, sem recuperação pelo dispatcher e sem limite de recuperação (reverte OQ-43; `RECOVERY_EXHAUSTED` aposentado; `PROCESSING_ERROR` continua). Na inicialização, o worker assume o pedido deixado em `DISPATCHED`, `RUNNING` ou `CANCELLING`: devolve as datas em Processando ao status anterior (OQ-26); `DISPATCHED` ou `RUNNING` retoma após `progress_date`; `CANCELLING` termina `CANCELLED`. Todo término de pedido, inclusive `CANCELLING` → `CANCELLED` na inicialização, libera o pedido ativo na mesma transação que grava o status final (escolha do integrador, seguindo o código do #78). A entrega continua pelo menos uma vez, com idempotência do inbox. As colunas `claim_token`, `lease_expires_at` e `attempt_count` ficam no esquema sem uso, sem migração (escolha do integrador). **Desde OQ-46:** não há dispatcher, despacho nem vaga; o worker pega ele mesmo o pedido `QUEUED` mais antigo; na inicialização assume só um pedido `RUNNING` e depois esvazia a fila; `active_request_id` não é usado.
- Sem dispatcher (usuário, 19/10/2026, sessões do merger e Lead Backend; OQ-46): não há processo dispatcher, serviço no Compose, ciclo de despacho nem vaga; um único worker, com prefetch 1. `POST /processing/requests` grava o pedido `QUEUED` e, na mesma transação, uma mensagem no outbox que só avisa "há trabalho". A cada mensagem, e na inicialização depois da recuperação de OQ-45, o worker repete até não restar pedido `QUEUED`: numa transação bloqueia o pedido `QUEUED` mais antigo por `(created_at, id)` e o marca `RUNNING` com `started_at`, depois o executa; uma mensagem sem pedido na fila não faz nada. O PostgreSQL decide a ordem; mensagem perdida é coberta por outra mensagem ou por um reinício; duplicatas são inofensivas; ACK ao receber (leitura do integrador). `DISPATCHED` aposentado (`QUEUED` → `RUNNING`), e `CANCELLING` sem uso (leitura do integrador); ambos ficam no enum e no CHECK, e `dispatched_at` e `calculation_state.active_request_id` ficam sem uso, sem migração. A regra de cancelamento na reinicialização de OQ-45 não muda; Enviado e Cancelando nunca aparecem na interface. Altera OQ-5, OQ-29 item 2 e OQ-45 itens 2, 4 e 5.
- Revisão de código antes da entrega (usuário, 19/10/2026, sessão Lead Backend: "all recommended"; OQ-47): o schema fica como está, sem squash de migrações nem remoção de colunas, e os status e colunas sem uso (`DISPATCHED`, `CANCELLING`, `claim_token`, `lease_expires_at`, `attempt_count`, `dispatched_at`, `calculation_state`) seguem documentados como sem uso; o inbox continua, com limpeza por retenção; uma data com Erro mantém as pendências da publicação anterior; o resumo da Carteira mostra os valores gravados de uma data com Erro ou Processando com o seu status, enquanto o gráfico soma 0 nesses dias (OQ-41); o restante fica registrado como dívida técnica em `docs/development.md`. O mock MSW que reimplementava regras do backend (H6) foi removido por decisão do usuário ("lets go with A", 19/10/2026, OQ-47 item 6): sem backend simulado nem modo mock no desenvolvimento; o MSW fica só nos testes de componentes, com fixtures estáticas.
- Término de pedido que não pode ser gravado (OQ-47 item 7; leitura do integrador no #115, aprovada pelo usuário em 19/10/2026: "Keep OQ-47 item 7 as is; record that I approved it."): o worker repete a gravação só em erro transitório de banco; qualquer outro erro encerra o pedido `FAILED` com `PROCESSING_ERROR` numa transação nova, devolve as datas em Processando ao status anterior e deixa `failed_date` e `failed_chain` vazios (salvo a primeira falha de cadeia de um Tudo). Emenda OQ-40.
- Série de P&L da Carteira só com o que o gráfico lê (usuário, 19/10/2026, sessão do integrador: "so shouldnt we remove it and simplify the method?"; "perfect so lets make the changes"; OQ-49): cada ponto de `GET /portfolio/pnl` traz `date`, `daily_pnl`, `range_cumulative_pnl` e o status de posições. Saem do ponto `cumulative_pnl`, `pnl_status` e `published_at`. O `cumulative_pnl` desde o início e o `pnl_status` continuam no resumo e nas linhas de posição; o horário "Processado em …" continua no resumo e na tabela de posições. A soma do gráfico (OQ-41) não muda.
- Decisões de tela após testar o backend real (usuário, 19/10/2026, sessão do frontend; OQ-48): a página do produto em Ativos registra preço (botão acima da lista e menu "…" de cada contrato, que também remove preço); `Instrument.last_reference` vem preenchido com o preço preferencial mais recente de cada contrato, lido por `prices.public.PriceReader.latest` (reverte OQ-33 item 4); o destaque do card "P&L acumulado" da Carteira é o `range_cumulative_pnl` da data selecionada, rotulado com a data inicial do gráfico, e o `cumulative_pnl` desde o início não muda (§8.3).
- Revisão de staff do branch `simplify` (usuário, 19/10/2026, sessão Lead Backend: "lets do all of them with your recommendations"; sobre a fila: "Im not so sure about the doorbell. Is it really necessary? I want to keep the queue", e depois "option 1"; OQ-50; implementado em PRs posteriores): o AUM é calculado na leitura, só com as duas cadeias da data processadas, e não é mais gravado; o RabbitMQ leva uma mensagem por pedido (o seu `request_id`), publicada pelo outbox, só para rastreio; a cada mensagem, e numa varredura periódica, o worker pega o pedido `QUEUED` mais antigo por `(created_at, id)`, sem mudar a ordem FIFO; saem o inbox, a retenção, as filas dead-letter, o limite de entregas, o backoff e a fila pós-ACK (substitui a campainha de OQ-46; reverte OQ-47 item 2); a Carteira marca "Preço alterado após o processamento — reprocesse" na linha cujo preço atual de D ou de D−1 foi cadastrado (`created_at`) depois do `portfolio_processed_at` de D (D−1: leitura do integrador); Processando não é mais gravado por data, é derivado do pedido em execução (`progress_date + 1`), e `*_previous` fica sem uso. Mantidos: num Tudo, a outra cadeia continua quando uma falha (OQ-36), e um cancelamento durante a última data termina `COMPLETED`, sem mostrar depois "cancelamento solicitado". Um preço gravado de novo recebe novo id por desenho (OQ-25). Escopo: o usuário excluiu A5–A9 ("I still want all the other changes you recommended other than the 'A' part"), inclusive o squash das migrações; os itens C e as demais recomendações vão em PRs separados.
- Limite de intervalo (usuário, 19/10/2026, sessão do merger: "Approve the 3,660-day range cap; record it as an amendment of OQ-5 item 1 in #127."; emenda OQ-5 item 1): pedido de processamento, pré-visualização e série de P&L aceitam no máximo 3.660 datas, contando as duas pontas; acima disso, 422 `INVALID_RANGE` em `end_date`, "O período deve ter no máximo 3.660 dias."
- Descrição opcional nas movimentações de caixa (usuário, 19/10/2026, repassado pela sessão Lead Backend: "Ledger cash entries should have an optional description. We should save that in the table. We should also alter the backend and frontend so the user can input it and see it if he wishes to"; OQ-51): `ledger.entries.description VARCHAR(200)`, só em CASH (operação com descrição → 422), sem espaços nas pontas, vazia → nula, até 200 caracteres (mais → 422), incluída na busca e imutável; leituras do integrador; reverte OQ-26 item 2 e fecha a lacuna do enunciado §4.2.
- Portas do ambiente local escolhidas no `.env` (usuário, 19/10/2026, repassado pela sessão Lead Backend: "it would be good to let the user decide which port to host the api and which to host the db (this should be in the env file)"; OQ-52): `DI1_WEB_PORT`, `DI1_API_PORT`, `DI1_DB_PORT` (PostgreSQL, agora publicado) e `DI1_RABBITMQ_MANAGEMENT_PORT`, todas em 127.0.0.1; `make e2e` continua escolhendo portas livres.

### Aberto — requer decisão específica antes de codificar o comportamento

Nenhum item em aberto.

### TODO posterior à entrega principal

- Importação CSV de preços de referência via RabbitMQ.
- Integração para captura de preços oficiais B3.

## 15. Desvios e interpretações do enunciado

Fonte: `docs/desafio_tecnico_di1_1.pdf`. Auditoria de 18/10/2026; desvios aprovados pelo usuário (OQ-18). O `docs/development.md` repete esta seção, e o README a resume.

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
| D3 | §5 e requisito 6: a consulta reconstrói a carteira a partir dos eventos até a data | A reconstrução ocorre no processamento solicitado pelo usuário, a partir dos lançamentos e preços gravados; o GET só lê resultados publicados (§10, §11.4) | Após um processamento de 01/01/2027; antes disso a tela mostra "não processado", com link para Processamentos. Justifica onde o assíncrono agrega valor (§8 do enunciado). Os resultados processados ficam como estão até o usuário processar de novo: depois de alterar o histórico, o usuário reprocessa (OQ-31) |
| D4 | Os exemplos são datados de 01/01/2027, data futura em 18/10/2026 | Datas após hoje são rejeitadas (§6.1) | Testes automatizados rodam os exemplos exatamente como escritos, com relógio injetado fixo em 01/01/2027; a demonstração de `docs/development.md` usa os mesmos passos datados de hoje, com vencimento em hoje + 365 dias: números idênticos (PU 90.909,09, caixa 109.090,91, AUM 200.000) |

---

**Diretriz para agentes:** não reinterpretar campos, mudar o modelo de P&L, inserir recálculo automático, adicionar múltiplas carteiras ou carregar cotações anteriores sem solicitação expressa. Ao identificar ambiguidade, registrar a decisão pendente e propor alternativa com impactos, sem preencher silenciosamente a lacuna.
