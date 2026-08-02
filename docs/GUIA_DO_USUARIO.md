# Nexum — Guia do Usuário

Bem-vindo(a) ao **Nexum**, um aplicativo de gestão financeira pessoal para Windows.
Ele organiza suas contas, cartões, investimentos e metas em um só lugar — e **todos
os seus dados ficam somente no seu computador**. Nada é enviado para a nuvem.

---

## 1. Instalação

1. Baixe o instalador **NexumSetup.exe** na página de releases:
   `https://github.com/ImContradiction9/nexum/releases` (versão mais recente).
2. Execute o instalador e siga os passos (avançar → instalar).
3. Abra o **Nexum** pelo atalho criado no Menu Iniciar.

> **Atualizações**: o app avisa sozinho quando existe versão nova. Basta aceitar —
> ele baixa, instala em silêncio e reabre. Antes de atualizar, um backup do seu
> banco de dados é feito automaticamente.

**Onde ficam meus dados?** Em `%APPDATA%\Nexum\financeiro.db` no seu Windows.
Backups automáticos são criados na subpasta `backups` a cada inicialização
(mantém os 10 mais recentes).

---

## 2. Primeiros passos

A ordem recomendada para começar:

1. **Cadastre suas contas** — vá em **Configurações → Contas** e crie cada conta
   corrente e cartão de crédito que você usa (Nubank, Santander, etc.). Informe o
   banco, o tipo (Conta Corrente ou Cartão de Crédito) e, se quiser, o titular —
   útil quando você administra contas de mais de uma pessoa da família.
2. **Importe seus arquivos** — botão **"Importar arquivo"** no topo. O Nexum lê:
   - **OFX** de conta corrente (extrato exportado do app do banco);
   - **PDF** de fatura de cartão de crédito (aceita PDF com senha — ele pede a
     senha na hora e pode salvá-la para os próximos meses).

   Você pode selecionar **vários arquivos de uma vez**: eles entram numa fila e
   são processados um a um.
3. **Revise as categorias** — a maior parte das transações é categorizada
   automaticamente. O que ficar pendente aparece como "não categorizada" para
   você classificar (e o app **aprende** com suas escolhas).

> 💡 **Dica**: importe alguns meses de histórico logo no início. Os gráficos de
> evolução e os comparativos ficam muito mais úteis com 3+ meses de dados.

---

## 3. As abas do Nexum

### 📊 Dashboard

A visão geral do mês: **Receitas, Despesas e Saldo**, sempre comparados ao mês
anterior (setinhas de alta/baixa com percentual).

- **Período**: escolha o mês no seletor, ou use *Últimos 3 meses*, *Ano todo* e
  *Personalizado*.
- **Ver por Pagamento ou Emissão**: "Pagamento" agrupa pelo mês em que o dinheiro
  saiu (regime de caixa); "Emissão" pelo mês da compra.
- **Cards**: despesas essenciais × discricionárias, quanto da receita foi
  investido, saldo geral do período, pró-labore, empréstimos a terceiros.
- **Gráficos**: despesas por categoria, por atribuição (pessoa), por forma de
  pagamento, por banco, **à vista × parceladas** (quanto do mês vem de compras
  antigas), recebimentos por origem, evolução mensal e previsão dos próximos
  meses (parcelas já comprometidas).
- Cada bloco tem um botão **"ocultar"** — monte o dashboard do seu jeito.

### 💸 Transações

Todas as movimentações de cartões e contas, com filtros por mês/período, conta,
banco, categoria, atribuição, **entradas/saídas** e **à vista × parceladas**.

- **Nova transação**: lançamentos manuais (dinheiro, Pix avulso etc.).
- **Edição em massa**: selecione várias transações e aplique categoria ou
  atribuição de uma vez.
- **Dividir transação**: uma compra de mercado de R$ 300 pode virar partes
  (R$ 200 casa, R$ 100 outra pessoa), cada uma com categoria e atribuição próprias.
- **Suspeitas de duplicata**: quando o mesmo lançamento aparece em dois arquivos,
  ele fica num banner de revisão — você decide se aceita ou descarta. Suspeitas
  **não contam nos totais** até serem revisadas.
- **Estornos**: receitas que devolvem uma compra (estorno/reembolso) são
  detectadas e abatem da despesa em vez de inflar a receita.

### 🏦 Extrato

O espelho da sua conta corrente: movimentações em ordem cronológica com **saldo
acumulado linha a linha**, comparado ao saldo real do banco quando o OFX traz
essa informação.

Aqui você também marca movimentações internas:

- **Pagamento de fatura** — o débito que quita o cartão (para não contar como
  despesa duas vezes);
- **Transferência** — dinheiro que só mudou de conta (também fica fora dos totais).

O Nexum detecta boa parte disso sozinho (Pix entre contas do mesmo titular,
pagamentos de fatura), mas você pode marcar/desmarcar manualmente.

### 📅 Orçamento

Defina um **teto mensal por categoria** e acompanhe as barras de consumo. O app
mostra a **média dos últimos meses** e a tendência (subindo/descendo) para te
ajudar a definir tetos realistas.

### 📈 Investimentos

Cadastre seus ativos com **"+ Novo ativo"** (o formulário fica no fim da página):

- **Renda fixa atrelada ao CDI** (CDB, RDB, caixinhas): informe o % do CDI
  (ex.: 100%) e o app calcula o saldo dia a dia usando a **taxa CDI oficial do
  Banco Central** — incluindo estimativa de **IR e IOF** (bruto × líquido).
- **ETFs e ações**: informe o ticker (ex.: IVVB11, VOO) e o app busca a cotação
  e o histórico mensal automaticamente. Ativos em dólar são convertidos pelo
  câmbio do dia.
- **Outros**: qualquer ativo com saldo informado manualmente.

Registre **aportes e resgates** em cada ativo. Os gráficos mostram:

- **Evolução** do patrimônio (total ou por tipo);
- **Rendimento** ao longo do tempo (por tipo ou por ativo);
- **Aporte × rendimento** mês a mês — veja quanto você aportou e quanto o
  dinheiro rendeu sozinho;
- **Alocação** — distribuição da carteira com alvos percentuais por tipo.

### 🎯 Metas

Crie metas de patrimônio com **"Nova meta"**: valor alvo, prazo e escopo (todo o
patrimônio, só alguns tipos, ou ativos específicos). O app projeta **com juros
compostos** quando você deve atingir a meta no ritmo atual e qual aporte mensal
seria necessário para bater o prazo. Suporta metas em **dólar/euro** (convertidas
pelo câmbio do dia) e **sub-metas** (uma meta grande dividida em etapas).

### ⚙️ Configurações

- **Contas** e **Bancos**: cadastro e cores.
- **Categorias**: crie/edite, marque como essencial ou não, defina orçamento.
- **Atribuições**: pessoas ou grupos (ex.: você, cônjuge, "empresa") para saber
  de quem é cada gasto.
- **Regras**: automatize — "toda descrição contendo *iFood* → categoria
  Restaurantes". As regras têm prioridade sobre o aprendizado automático.
- **Arquivos**: tudo que foi importado, com o **mapa de cobertura** — uma grade
  que mostra, para cada conta, quais meses têm arquivo importado e onde há
  **buracos** na sequência. Ideal para não esquecer nenhum mês.

---

## 4. Recursos extras

### Exportar para Excel

Nas telas de Transações e Extrato há botão de **exportar .xlsx** (respeitando os
filtros ativos). No PC, o arquivo é salvo em `Downloads\Nexum` e o Explorer abre
com ele selecionado.

### Acessar do celular (rede local)

Em **Configurações** você pode ativar **"Compartilhar na rede"**: o app gera um
endereço e um **PIN**. Qualquer aparelho na *mesma rede Wi-Fi* acessa o Nexum
pelo navegador digitando o PIN. Operações sensíveis (configurações, atualização,
reset) só funcionam no próprio PC, mesmo com o PIN.

### Backups

- Automático a cada inicialização (1 por dia, mantém os 10 mais recentes);
- Automático antes de cada atualização de versão;
- Manual: basta copiar o arquivo `%APPDATA%\Nexum\financeiro.db`.

---

## 5. Perguntas frequentes

**Meus dados vão para algum servidor?**
Não. O Nexum roda 100% no seu computador. As únicas conexões externas são para
buscar dados públicos: taxa CDI e câmbio (Banco Central), cotações (Yahoo
Finance) e verificação de novas versões (GitHub). Nenhum dado seu é enviado.

**Importei o mesmo arquivo duas vezes. E agora?**
Nada acontece — o app reconhece o arquivo/lançamentos e não duplica. Se algum
lançamento parecido surgir de fontes diferentes, ele vai para a revisão de
suspeitas em vez de contar em dobro.

**O saldo do extrato não bate com o banco.**
Confira no mapa de cobertura (Configurações → Arquivos) se não falta importar
algum mês — um mês faltante desloca o saldo acumulado. Você também pode definir
um **saldo inicial manual** na conta.

**O valor do meu CDB difere alguns centavos do app do banco.**
O CDI do dia só é publicado pelo Banco Central no dia útil seguinte; o Nexum
projeta o dia corrente e se ajusta quando o valor oficial sai. Diferenças de
centavos são normais e temporárias.

**Errei um lançamento importado. Posso apagar?**
Lançamentos manuais podem ser excluídos direto. Para refazer um arquivo inteiro,
exclua-o em Configurações → Arquivos (remove todas as transações dele) e importe
de novo.

**Cadastrei um aporte antigo e o rendimento parecia zerado.**
O app baixa automaticamente o histórico de CDI necessário. Se acabou de cadastrar
uma operação bem antiga, aguarde alguns segundos e recarregue — ou use o botão de
sincronizar na aba Investimentos.

---

*Nexum — seus dados, no seu computador.*
