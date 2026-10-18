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
| `prices` | Gerenciar observações de referência manuais e B3, versões, origens e seleção de preço preferencial | Não altera trades nem registra preços de execução |
| `portfolio` | Reconstruir posições e estado de caixa por dia; manter posições e métricas calculadas; servir consultas consolidadas | Não redefine as regras dos calculadores de P&L |
| `pnl` | Calcular P&L por ativo e agregá-lo para a carteira | Aportes/retiradas não são P&L; o módulo inicialmente não precisa persistir tabelas próprias |
| `processing` | Validar pedidos, enfileirar, executar, cancelar e publicar processamentos; administrar pendências e invalidação | Alterar entrada **não** dispara processamento automaticamente |

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

### 4.1 Metodologia em uso

Foi decidida a convenção simplificada **DC/365**, usando dias **corridos**, incluindo finais de semana e feriados:

```text
PU = 100000 / (1 + taxa) ^ (dias_corridos / 365)
taxa = (100000 / PU) ^ (365 / dias_corridos) - 1
```

- `taxa` é fração decimal anual: `0.10` significa 10% a.a.
- `dias_corridos` decorre da data de referência do cálculo e do vencimento do contrato.
- A constante de 100.000 é a base especificada pelo desafio DI1. O cadastro de futuros reserva dados como `face_value` para extensibilidade; qualquer variação de base exige metodologia explícita e testes.
- A aplicação aceita taxa **ou** PU e calcula o valor faltante; não deve tratar ambos como entradas independentes contraditórias.
- **Precisão (decidido, OQ-3):** cálculos em `Decimal` com contexto de 34 dígitos e arredondamento `ROUND_HALF_UP`. PU calculado é armazenado com 10 casas decimais e taxa calculada com 12. PU digitado com mais de 10 casas ou taxa digitada com mais de 12 é **rejeitado**, nunca arredondado. Valores monetários são armazenados exatos e arredondados a 2 casas apenas na exibição.
- Limites de valores: apenas os do schema (taxa > −1, PU > 0, quantidade ≠ 0, valor > 0) (OQ-14).
- Uma calculadora pode produzir uma prévia sem salvar nada.
- O mesmo motor de cálculo pode ser usado ao registrar uma operação ou quando o fluxo de preço de referência realmente precisar derivar o valor complementar.
- A convenção mais realista DU/252 discutida anteriormente **não** faz parte da implementação atual; pode ser adicionada futuramente como outra metodologia, sem alteração retroativa silenciosa.

### 4.2 Três valores diferentes que não podem ser confundidos

1. **PU/taxa calculados:** resultado matemático de uma calculadora; não implica persistência.
2. **PU/taxa de execução:** dados do negócio fechado, pertencentes ao registro imutável de trade no Ledger.
3. **PU/taxa de referência:** observação para determinada data, pertencente a Prices e usada na avaliação e no P&L.

O PriceService é o ponto único de gerenciamento dos **preços de referência**, não de qualquer preço calculado nem dos trades.

## 5. Preços de referência (`prices`)

- A observação identifica **instrumento, data de referência, fonte e valores**; registra também qual entrada foi autoritativa (PU ou taxa), quando pertinente.
- Fontes atuais planejadas: **`MANUAL`** e **`B3`**.
- Pode existir **uma observação atual por instrumento, data e fonte**; revisões anteriores ficam preservadas com auditoria.
- **Prioridade de seleção para avaliação:** `MANUAL` primeiro, `B3` em segundo. Se nenhuma existir na data exata, o preço exigido está ausente.
- Não utilizar automaticamente o último PU disponível antes da data solicitada. **Não há carry-forward**, nem aos sábados/domingos.
- O preço de referência efetivamente utilizado no cálculo precisa ser rastreável à **observação/revisão** selecionada, para não misturar valor revisado com P&L antigo.
- A correção/exclusão lógica de observação manual pode fazer a fonte B3 passar a prevalecer para a mesma data.
- Inserir ou corrigir preço invalida os resultados financeiros dependentes; **não altera trades e nem recalcula as quantidades**.
- Invalidação ocorre junto da gravação da observação; nenhuma atualização de preço inicia um job de P&L automaticamente.
- Importação massiva CSV e coleta de preços B3 são **TODOs futuros, após o núcleo estar concluído**. Quando introduzidas, devem reutilizar o PriceService; uma via assíncrona pode integrar via RabbitMQ.

## 6. Lançamentos (`ledger`)

### 6.1 Operações

Uma compra/venda inclui contrato, direção, quantidade, data/hora efetiva e PU **ou** taxa de execução. O sistema pode calcular a representação faltante através de Pricing.

- **Data e hora são obrigatórias** (OQ-13): `trade_time` em horário local de São Paulo; o formulário sugere a hora atual.
- **Datas aceitas** (OQ-7, OQ-14): qualquer data corrida, inclusive fins de semana e feriados; nada datado **após hoje** (America/Sao_Paulo) é aceito, para operações, movimentações e preços. Vencimentos são isentos.
- **Vencimento** (OQ-1): uma operação pode ser datada até a data de vencimento, inclusive; nessa data (dias corridos = 0) o PU é digitado e a taxa é armazenada como `0`. Operações datadas após o vencimento são rejeitadas.

- Cada operação é preservada individualmente, mesmo quando várias operações atingem o mesmo contrato no mesmo dia.
- Registro financeiro imutável: **não há edição direta** de operações. Exclusão lógica (soft delete) com auditoria; foi prevista exclusão múltipla com confirmação e operação atômica.
- A ordem de processamento é cronológica: `(data, hora, seq)`; não somar ou compensar todas as operações do dia antes de atualizar custos médios.
- `created_at` (instante de cadastro) é diferente do momento efetivo da operação.
- Alterações históricas por inclusão/exclusão invalidam os estados contábeis do dia afetado em diante, juntamente com os resultados dependentes.

### 6.2 Movimentações de caixa

- Dois tipos: **aporte** e **retirada**, cada qual com valor positivo informado, data efetiva e descrição opcional.
- Também são registros auditáveis, sem edição de valores depois do lançamento.
- Aportes/retiradas modificam **saldo de caixa** e AUM, **não** P&L.
- Não há obrigação de modelar BRL como um instrumento negociável para exibir caixa na carteira.

## 7. Contabilidade diária da carteira (`portfolio`)

### 7.1 Estado inicial e calendário

- Estado inicial antes do primeiro lançamento relevante: **caixa zero, posição zero, P&L zero**.
- Calcula-se **todos os dias corridos** na faixa efetiva do processamento, inclusive fins de semana e feriados.
- O cálculo do dia usa o estado contábil anterior válido e aplica sequencialmente as operações e movimentações daquele dia.
- Os resultados de dias anteriores só podem ser reutilizados como pontos de partida quando seu estado contábil está válido diante das revisões atuais.

### 7.2 Posição e custo médio

Uma posição diária tem, por ativo, quantidade assinada de fechamento: positivo = comprado, negativo = vendido, zero = sem posição.

- Ao aumentar posição no mesmo sentido, o PU médio de entrada é recalculado pela ponderação das quantidades; a **taxa média de entrada é controlada separadamente** conforme sua própria ponderação, não derivada automaticamente do PU médio.
- Reduzir parcialmente uma posição **não modifica** o custo médio dos contratos remanescentes sob a convenção de custo médio adotada.
- Fechar integralmente leva a posição a zero.
- Se uma operação **atravessa zero**, o cálculo fecha a posição antiga e abre a quantidade residual no sentido oposto **ao PU/taxa da operação reversora**. O Ledger mantém a operação original indivisa; não cria trades artificiais.
- Calcular os efeitos financeiros do fechamento e da abertura sem contar P&L duas vezes.
- Custos médios são também estado necessário para o próximo dia: devem ser calculáveis/persistíveis mesmo quando o preço de referência está ausente.

### 7.3 Caixa simplificado

Sob o modelo simplificado acordado (sem ajustes diários reais de futuros):

```text
cash[D] = cash[D-1]
          - Σ (signed_trade_quantity × execution_PU)
          + deposits[D] - withdrawals[D]
```

- `signed_trade_quantity`: compras positivas; vendas negativas.
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
- O PU de referência `D-1` usado é o registrado na linha `position_metrics` de `D-1` (OQ-9); uma mudança de preço em X invalida a avaliação de X em diante.
- Trades intradiários podem exigir preço de referência mesmo se a posição de fechamento for zero.

### 8.2 Valor de mercado e AUM

```text
financial_total[a,D]       = Q[a,D] × reference_PU[a,D]
positions_market_value[D]  = Σ financial_total[a,D]
aum[D]                     = cash_balance[D] + positions_market_value[D]
```

- `financial_total` significa **valor de mercado** da posição, **não** valor histórico investido.
- A quantidade é assinada, então uma posição vendida produz valor de mercado assinado negativo.
- **AUM**, neste simulador, é definido como saldo de caixa mais valor de mercado líquido das posições. Não incluir `gross_exposure`, `net_exposure` nem `total_equity` como campos adicionais.
- Mudanças de caixa por aporte e retirada podem alterar AUM sem alterar P&L.

### 8.3 Ausência e completude de dados

- Se a referência exigida não existe para a data exata, o sistema calcula **quantidade, custo médio e caixa**, mas deixa os resultados financeiros dependentes como **indisponíveis (`null`)**, nunca zero inventado.
- O valor de mercado de uma posição zero é zero mesmo sem referência; **isso não implica** que o P&L dos trades do dia seja calculável.
- Alguns ativos podem ter P&L disponível enquanto outros não. O P&L agregado da carteira **não é completo** se faltar resultado de qualquer ativo esperado.
- **Ativo esperado em D** (OQ-10): `Q[a,D-1] != 0` ou existe operação do ativo em D. Exatamente esses ativos têm linhas em `positions` e `position_metrics` para D, inclusive com quantidade 0 após zeragem ou round trip no dia.
- O P&L acumulado permanece indisponível a partir do primeiro dia com lacuna não resolvida na cadeia histórica, até a correção e o reprocessamento necessário.
- Uma data sem preços no calendário da tela de Ativos não gera automaticamente pendência; a pendência surge quando um cálculo requer efetivamente a observação ausente.
- Ausência de dado de mercado **não é falha técnica** da fila ou da calculadora.
- As telas devem distinguir dados **válidos, ausentes/incompletos e desatualizados**; não combinar PU recém-corrigido com P&L calculado em uma revisão anterior.

## 9. Persistência funcional das posições e métricas

| Tabela | Chave lógica | Conteúdo |
|---|---|---|
| `portfolio.positions` | `(asset_id, position_date)` | Quantidade de fechamento assinada |
| `portfolio.position_metrics` | `(asset_id, metric_date)` | PU/taxa médios de entrada, referência usada, `financial_total`, `position_pnl`, `trades_pnl`, `daily_pnl` e estados de completude |
| `portfolio.portfolio_metrics` | `metric_date` | Saldo de caixa, valor de mercado total, AUM, P&L de posições, P&L de operações, P&L diário, P&L acumulado e estados de completude |

- Não persistir uma entidade de negócio `portfolio` nem `portfolio_id`.
- Não criar simultaneamente tabelas PnL independentes duplicando exatamente os campos de `position_metrics`.
- O módulo PnL calcula; Portfolio armazena os resultados publicados.
- O frontend obtém uma **visão consolidada** por ativo/data a partir do Portfolio Query Service, em uma chamada HTTP, com leitura eficiente e controle de consistência de referência.
- Cálculos parciais de jobs são gravados em **tabelas temporárias de estágio associadas ao pedido**, no schema `portfolio` e de propriedade do módulo Portfolio (OQ-8); somente resultados coerentes são publicados para as três tabelas finais.

## 10. Processamentos sob solicitação do usuário

### 10.1 Regra principal

**Cadastrar/excluir operação ou adicionar/corrigir preço apenas persiste o fato e invalida as saídas dependentes. Não inicia processamento de carteira nem manda recalcular P&L automaticamente.**

O usuário acessa **Central de Controle → Processamentos**, escolhe intervalo inclusivo de datas e confirma o processamento. **O processamento cobre exatamente o intervalo solicitado [A, B]**; não há expansão automática (OQ-11).

- Se o estado de A−1 estiver desatualizado ou ausente, o job ainda executa e publica [A, B]: esses dias aparecem como desatualizados, o P&L fica `null` e uma pendência pede o processamento de um intervalo anterior. Sem lançamentos antes de A, o estado de A−1 é o estado zero, válido.
- A pré-visualização avisa quando o estado de A−1 está desatualizado.

### 10.2 Fila, simultaneidade e cancelamento

- Podem existir **múltiplos pedidos enfileirados**, inclusive com intervalos sobrepostos.
- **Somente um pedido é executado por vez** para a carteira única.
- O usuário pode cancelar pedidos **na fila** imediatamente.
- Para pedido **em execução**, cancelar sinaliza interrupção; o worker verifica o sinal em pontos seguros entre dias/transações, conclui a operação corrente com integridade e encerra sem publicar a faixa incompleta.
- O usuário pode registrar nova operação ou corrigir preço, enfileirar um novo intervalo e cancelar o job anterior. Opcionalmente, UI **Cancelar e criar novo processamento** faz os dois pedidos de forma coordenada.
- A fila durável e os estados de jobs pertencem ao **PostgreSQL**. RabbitMQ transporta comandos de execução; não é a fonte de verdade sobre a ordem dos jobs.
- O worker processa cronologicamente as datas com chamadas diretas aos módulos (Portfolio, Prices, PnL); não se publica uma mensagem para cada ativo ou dia.
- Um job calcula com versões dos inputs capturadas ao iniciar e verifica as versões antes de publicar. Se mudanças posteriores tornarem o resultado obsoleto, não pode sobrescrever dados atuais (**SUPERSEDED**).
- Reentrega de mensagens, reinicialização de worker e retomada de lease não podem gerar duas publicações concorrentes.

### 10.3 Status e pendências

Estados principais planejados:

- `QUEUED`: na fila.
- `DISPATCHED`: enviado para o worker, ainda não executando.
- `RUNNING`: em processamento.
- `CANCELLING`: cancelamento sinalizado.
- `CANCELLED`: cancelado sem publicar cálculo incompleto.
- `COMPLETED`: resultados exigidos completos.
- `COMPLETED_WITH_ISSUES`: cálculo contábil persistível, mas alguma métrica de mercado/P&L está incompleta por dependência ausente.
- `FAILED`: falha técnica inesperada.
- `SUPERSEDED`: fonte de dados mudou; publicação obsoleta foi bloqueada.

A lista de **Pendências** exibe problemas acionáveis: ativo, data necessária, motivo e ação. Deduplicar problemas repetidos para a mesma obrigação. Tipos atuais: **preço de referência faltante** (ação: definir preço), **contrato vencido com posição aberta** (§7.4) e **estado anterior desatualizado** (§10.1; ação: processar intervalo anterior).

### 10.4 Publicação e invalidação

- A saída de cada dia é calculada e armazenada em estágio por `request_id`; o progresso é consultável na UI.
- Na publicação, verificar cancelamento, revisão dos dados de origem e autorização do worker ativo; inserir/substituir coerentemente `positions`, `position_metrics` e `portfolio_metrics` em **uma operação transacional de publicação**.
- Cancelamento ou job obsoleto descarta seu estágio e mantém os resultados anteriores, com indicador de desatualização se necessário.
- Uma alteração no Ledger invalida estados contábeis da sua data em diante e, consequentemente, resultados dependentes.
- Uma alteração em Prices invalida avaliações e P&L dependentes, **sem** alterar quantidade, caixa ou custo médio.
- Invalidação deve ocorrer na **mesma transação** que salva a alteração original.
- Novos processamentos são uma decisão do usuário, não um efeito colateral da invalidação.
- **Marcadores de invalidação** (OQ-12): após publicar [A, B] com as revisões inalteradas desde o início, um marcador dentro de [A, B] avança para B+1; um marcador anterior a A permanece. Dias após B continuam desatualizados até serem processados.
- **Limites operacionais** (OQ-5): sem tamanho máximo de intervalo; jobs mantidos como histórico; estágios apagados ao publicar, cancelar ou ser `SUPERSEDED`; fila FIFO por `(created_at, id)`; lease de 60 s renovado a cada dia processado; todos os valores configuráveis.

## 11. Telas e experiência do usuário

Os designs existentes no **Aura Build** são a base visual e devem ser implementados, não reconstruídos como um aplicativo de demonstração separado. UI inteira em **pt-BR**, com React, Mantine e TanStack Query. Durante o desenvolvimento, o frontend real pode usar respostas simuladas via **MSW**, seguindo contratos de API revisáveis.

### 11.1 Central de Controle

Duas abas: **Pendências** e **Processamentos**.

- **Pendências:** problemas realmente identificados pela validação/processamento, não uma lista de todos os dias sem cotação. Ação **Definir preço** conduz à entrada/correção da referência.
- **Processamentos:** escolher datas, pré-visualizar o intervalo (com aviso quando o estado anterior está desatualizado), enfileirar, acompanhar progresso e status, ver erros, cancelar pedidos, eventualmente cancelar e substituir. Os jobs continuam existindo no histórico após conclusão/cancelamento.
- Sem KPIs financeiros redundantes na Central de Controle.

### 11.2 Ativos

- Navegar pelo cadastro `tipo → classe → produto → instrumento`.
- Ver contrato, especificações, datas e referências existentes.
- A tela de contrato permite cálculo taxa ↔ PU e cadastro/inspeção/correção de preço de referência de data específica.
- Calendário/serie de preços deve distinguir observações reais de dias sem observação; **não inventar** preços interpolados.
- Um PU informado manualmente não precisa gerar obrigatoriamente um segundo campo visível para a taxa implícita, embora o motor possa calculá-la quando necessário.

### 11.3 Lançamentos

- Visualizar histórico de trades e movimentações, com filtro de intervalo inclusivo e busca.
- Registrar compra, venda, aporte e retirada por formulários/drawers apropriados.
- Distinguir **tipo de instrumento** de **tipo de lançamento**.
- Excluir uma operação ou múltiplas com confirmação; **não editar** trades existentes.
- Exibir data/hora efetiva e valores com formatação brasileira.

### 11.4 Carteira

- Seleção de **uma data**; consulta a posições e métricas anteriormente publicadas, sem recalcular no GET.
- Indicadores: **Saldo em caixa**, **AUM/Patrimônio**, **P&L diário**, **P&L de posições** e **P&L de operações**.
- **Gráfico compacto de P&L acumulado** no nível da carteira, somente onde houver histórico completo e válido.
- Tabela de posições consolida: ativo, vencimento, quantidade, PU médio, taxa média, PU de referência, taxa de referência (quando disponível), **valor de mercado** (`financial_total`), P&L posições e P&L operações.
- Os resultados por ativo e o total do portfólio derivam da mesma publicação coerente; não juntar preço novo com P&L velho.
- Exibir claramente métricas ausentes/incompletas ou desatualizadas; oferecer caminho contextual para Pendências ou Processamentos.
- Não listar caixa como linha de posição de ativo. Não expor P&L realizado/não realizado ou P&L acumulado por ativo na tabela padrão.

## 12. Regras de API e integração com frontend

- API de Carteira devolve dados agregados para a tabela em **uma resposta**, sem obrigar o React a coordenar pedidos a Asset, Prices, Portfolio e PnL.
- Respostas identificam data, estado de processamento/completude e valores ausentes com `null` (não zero).
- Valores monetários/PU/taxas trafegam como números decimais representados por **strings**, para preservar precisão no frontend.
- Processamentos expõem criação, listagem, status/progresso e cancelamento. O frontend pode consultar status periodicamente enquanto houver trabalho.
- **Erros** (OQ-15) seguem `application/problem+json` (RFC 9457) com `errors: [{code, message, field}]`; mensagens em pt-BR, códigos em inglês, catálogo em `interfaces.md`.
- O gráfico de P&L acumulado da Carteira usa `GET /portfolio/pnl` (OQ-16).
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
9. Mudança histórica em operação/PU, revisões de preços e invalidação correta (sem auto-job).
10. Dois pedidos com intervalos sobrepostos, cancelamento na fila, cancelamento em execução, reposição e proteção de publicação atômica.
11. Mudança de fonte durante job; marcação `SUPERSEDED`, idempotência/reentrega RabbitMQ, recuperação de worker.
12. Resposta consolidada da Carteira coerente por data e versão; mocks em conformidade com APIs.

## 14. Decisões fechadas e itens ainda abertos

### Fechado

- Uma carteira; monólito modular; `market_data` renomeado para `prices`.
- Ledger é dono exclusivo de preços executados em trades; Prices apenas de referências.
- Prioridade de preços MANUAL > B3, cada fonte com sua revisão ativa.
- Ativos classificados por tipo, classe, produto e instrumento; `asset.futures` para especificações compartilhadas.
- DC/365, processamento em **cada dia corrido**, **sem carregamento implícito** de cotação antiga.
- Três tabelas finais de carteira: `positions`, `position_metrics`, `portfolio_metrics`.
- `financial_total` é valor de mercado; AUM é caixa + valor de mercado assinado; sem campos de exposição ou `total_equity` redundante.
- P&L por ativo e depois agregado; aportes/retiradas excluídos do P&L.
- Mudanças apenas invalidam; processamento da carteira ocorre **sob comando explícito do usuário**.
- Fila com sobreposição permitida, uma execução por vez, cancelamento seguro e publicação atômica.
- Frontend real baseado nos designs existentes, com chamadas mockadas por MSW em paralelo ao desenvolvimento do backend.

Decididos em 18/10/2026 (detalhes e palavras do usuário em `open-questions.md`):

- Sem liquidação automática no vencimento; o usuário encerra com operação a qualquer PU, inclusive na data de vencimento (taxa 0); após o vencimento, valor 0 e lançamentos rejeitados (OQ-1, OQ-6).
- Multiplicador mantido no cadastro e não aplicado nos cálculos atuais (OQ-2).
- Precisão: 34 dígitos, `ROUND_HALF_UP`, PU 10 casas, taxa 12 casas, excesso de casas rejeitado (OQ-3).
- Primeiro dia: `position_pnl` = 0 quando `Q[D-1] = 0` (OQ-4).
- Limites operacionais simples e configuráveis (OQ-5).
- Fins de semana e feriados aceitos; datas futuras rejeitadas; limites de valores apenas do schema (OQ-7, OQ-14).
- Estágios no schema `portfolio`, de propriedade do Portfolio (OQ-8).
- PU `D-1` rastreado pela linha de `D-1` (OQ-9).
- Ativo esperado: `Q[D-1] != 0` ou operação em D (OQ-10).
- Intervalo exato [A, B], sem expansão; predecessor desatualizado publica como desatualizado (OQ-11).
- Marcadores avançam para B+1 quando cobertos (OQ-12).
- Hora da operação obrigatória; ordem `(data, hora, seq)` (OQ-13).
- Erros em problem+json (RFC 9457) com catálogo de códigos (OQ-15).
- `GET /portfolio/pnl` alimenta o gráfico de P&L acumulado (OQ-16).
- Lane H é dona de `platform/**` (OQ-17).

### Aberto — requer decisão específica antes de codificar o comportamento

1. **Desvios do enunciado (OQ-18):** auditoria do PDF do desafio contra esta especificação.

### TODO posterior à entrega principal

- Importação CSV de preços de referência via RabbitMQ.
- Integração para captura de preços oficiais B3.
- Outras famílias de calculadoras/metodologias de PU e taxa, se justificadas.

---

**Diretriz para agentes:** não reinterpretar campos, mudar o modelo de P&L, inserir recálculo automático, adicionar múltiplas carteiras ou carregar cotações anteriores sem solicitação expressa. Ao identificar ambiguidade, registrar a decisão pendente e propor alternativa com impactos, sem preencher silenciosamente a lacuna.
