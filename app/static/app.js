function financeiro() {
  return {
    // Navegação
    view: 'dashboard',

    // Catálogos
    contas: [],
    categorias: [],
    atribuicoes: [],
    bancos: [],

    // Dashboard
    dashboard: {
      mes: '',
      meses_disponiveis: [],
      receitas: 0,
      despesas: 0,
      saldo: 0,
      n_nao_categorizadas: 0,
      n_nao_atribuidas: 0,
      por_categoria: [],
      por_atribuicao: [],
      por_conta: [],
      por_forma: [],
    },

    previsao: { meses: [] },
    previsaoExpandida: null,

    emprestimos: { pessoas: [], total_a_receber: 0, total_a_pagar: 0, sem_atribuicao: { despesa: 0, receita: 0 } },

    orcamentos: { itens: [], total_orcado: 0, total_gasto: 0, mes: '' },
    orcamentoMes: '',   // mês selecionado na aba Orçamento (MM/YYYY)

    // Transações
    transacoes: [],
    totalTransacoes: 0,
    ordenacao: { coluna: 'data', direcao: 'asc' },  // padrão: data ascendente

    // Seleção em massa de transações
    selecionadas: [],            // array de ids (Alpine não reage bem a Set)
    bulkForm: { categoria_id: '', atribuicao_id: '', aplicar_categoria: false, aplicar_atribuicao: false },
    filtros: {
      busca: '',
      mes: '',
      data_inicio: '',
      data_fim: '',
      conta_id: '',
      banco_id: '',
      tipo_conta: '',
      categoria_id: '',
      atribuicao_id: '',
      nao_categorizado: false,
      nao_atribuido: false,
      incluir_transferencias: false,
    },

    // Período do dashboard (preset escolhido)
    periodoPreset: 'mes',  // 'mes' | 'mes_anterior' | '30d' | '90d' | 'ano' | 'personalizado'
    periodoCustom: { data_inicio: '', data_fim: '' },

    // Totais monetários da listagem (atualizado a cada carregarTransacoes)
    totaisListagem: { receitas: 0, despesas: 0, saldo: 0 },

    // === Visibilidade de blocos do dashboard ===
    // Cada bloco do dashboard tem um id; persistimos quais estão ocultos
    // no localStorage pra preferência durar entre sessões.
    dashboardOcultos: {},
    dashboardAbertos: {},  // blocos colapsáveis: { id: true=aberto }. Default fechado.

    // Tipo de gráfico mostrado no card de "Distribuição" (alternável via select).
    tipoGrafico: 'categoria',
    opcoesGrafico: [
      { id: 'categoria',        nome: 'Despesas por categoria' },
      { id: 'essencial',        nome: 'Essenciais × não essenciais' },
      { id: 'atribuicao',       nome: 'Despesas por atribuição' },
      { id: 'forma',            nome: 'Despesas por forma de pagamento' },
      { id: 'banco',            nome: 'Despesas por banco' },
      { id: 'receita_despesa',  nome: 'Receitas × despesas' },
    ],

    blocosDashboard: [
      { id: 'kpis_principais',   nome: 'Receitas / Despesas / Saldo' },
      { id: 'kpis_secundarios',  nome: 'Essenciais / Discricionárias / Investido' },
      { id: 'emprestimos',       nome: 'Empréstimos a terceiros' },
      { id: 'alertas',           nome: 'Avisos de não categorizadas' },
      { id: 'graficos',          nome: 'Gráficos (categoria e evolução)' },
      { id: 'previsao',          nome: 'Próximos meses' },
      { id: 'por_categoria',     nome: 'Por categoria' },
      { id: 'por_atribuicao',    nome: 'Por atribuição' },
      { id: 'por_banco',         nome: 'Por banco' },
      { id: 'por_forma',         nome: 'Por forma de pagamento' },
    ],

    blocoOculto(id) { return !!this.dashboardOcultos[id]; },
    nBlocosOcultos() { return Object.values(this.dashboardOcultos).filter(Boolean).length; },

    ocultarBloco(id) {
      this.dashboardOcultos = { ...this.dashboardOcultos, [id]: true };
      this._persistirOcultos();
    },
    mostrarBloco(id) {
      const c = { ...this.dashboardOcultos };
      delete c[id];
      this.dashboardOcultos = c;
      this._persistirOcultos();
    },
    mostrarTodosBlocos() {
      this.dashboardOcultos = {};
      this._persistirOcultos();
    },
    _persistirOcultos() {
      try { localStorage.setItem('nexum_dashboard_ocultos', JSON.stringify(this.dashboardOcultos)); }
      catch (e) {}
    },
    _carregarOcultos() {
      try {
        const v = localStorage.getItem('nexum_dashboard_ocultos');
        if (v) this.dashboardOcultos = JSON.parse(v) || {};
        const a = localStorage.getItem('nexum_dashboard_abertos');
        if (a) this.dashboardAbertos = JSON.parse(a) || {};
        const g = localStorage.getItem('nexum_dashboard_tipo_grafico');
        if (g) this.tipoGrafico = g;
      } catch (e) {}
    },
    trocarTipoGrafico(t) {
      this.tipoGrafico = t;
      try { localStorage.setItem('nexum_dashboard_tipo_grafico', t); } catch (e) {}
      this.renderizarGraficos();
    },
    tituloGraficoAtual() {
      const o = this.opcoesGrafico.find(o => o.id === this.tipoGrafico);
      return o ? o.nome : 'Distribuição';
    },
    blocoAberto(id) { return !!this.dashboardAbertos[id]; },
    togglarBloco(id) {
      this.dashboardAbertos = { ...this.dashboardAbertos, [id]: !this.dashboardAbertos[id] };
      try { localStorage.setItem('nexum_dashboard_abertos', JSON.stringify(this.dashboardAbertos)); }
      catch (e) {}
    },

    // Suspeitas de duplicata
    nSuspeitas: 0,
    modalSuspeitas: false,
    suspeitasItems: [],
    carregandoSuspeitas: false,

    // Metas de patrimônio
    metas: [],          // árvore (raízes com sub_metas)
    metasFlat: [],      // lista achatada (pra select de meta-mãe)
    tiposAtivoDisp: [],
    ativosDisp: [],     // ativos (id+nome) para metas de escopo "ativos"
    metaModal: {
      aberto: false,
      editando_id: null,
      nome: '',
      descricao: '',
      escopo: 'patrimonio_total',
      escopo_tipos: [],
      valor_atual_manual: 0,
      valor_alvo: 0,
      data_alvo: '',
      taxa_retorno_anual: '',
      meta_pai_id: '',
    },

    // Conciliação
    sugestoes: { duplicatas: [], pagamentos_fatura: [] },

    // Regras
    regras: [],
    editandoRegra: false,
    regraForm: { palavra_chave: '', categoria_id: '', atribuicao_id: '', prioridade: 5, comentario: '' },

    // Faturas / Arquivos
    faturas: [],
    filtrosFaturas: { busca: '', banco: '', titular: '', tipo_conta: '', mes: '' },
    cobertura: { meses: [], contas: [], meses_n: '12' },

    // Configurações - sub-aba ativa
    subView: 'contas',

    // Contas (tela de gerenciamento — separada de this.contas que é só pro select)
    contasDetalhe: [],
    contaEditando: null,
    senhaForm: '',
    senhaVisivel: false,
    formContaAberto: false,
    contaForm: { nome: '', tipo: 'Cartão de Crédito', banco_id: '', titular: '', final: '',
                 dia_fechamento: '', dia_vencimento: '', observacoes: '' },

    // Bancos
    formBancoAberto: false,
    bancoForm: { nome: '', cor: '#888888' },

    // Categorias detalhadas (com edição)
    categoriasDetalhe: [],
    formCategoriaAberto: false,
    categoriaForm: { nome: '', tipo: 'Despesa', icone: '', orcamento_mensal: 0 },
    // Modal de edição de categoria
    editandoCategoria: null,    // categoria sendo editada (objeto completo) ou null
    editCategoriaForm: { nome: '', tipo: 'Despesa', icone: '', orcamento_mensal: 0, essencial: true },

    // Atribuições detalhadas
    atribuicoesDetalhe: [],
    formAtribuicaoAberto: false,
    atribuicaoForm: { nome: '', tipo: 'Pessoa', cor: '#888888', descricao: '' },
    // Modal de edição de atribuição
    editandoAtribuicao: null,
    editAtribuicaoForm: { nome: '', tipo: 'Pessoa', cor: '#888888', descricao: '' },

    // Modal de nova transação manual (avulsa)
    modalNovaTransacao: false,
    novaTransacaoForm: {
      data: '',
      descricao: '',
      valor: '',
      tipo: 'Despesa',
      conta_id: '',
      categoria_id: '',
      atribuicao_id: '',
      forma_pagamento: '',
      observacoes: '',
    },

    // Configurações chave-valor
    config: { nome_usuario: '', familia_nomes: '', familia_nomes_textarea: '' },

    // === Extrato bancário ===
    contasExtrato: [],
    extrato: {
      conta: { saldo_inicial_manual: null, saldo_inicial_data: null },
      conta_id: '',
      mes: '',
      meses_disponiveis: [],
      saldo_inicial: 0,
      saldo_final: 0,
      saldo_final_ofx: null,
      saldo_bate: null,
      fonte_saldo: 'zero',
      n_transacoes: 0,
      items: [],
    },
    modalSaldo: { show: false, valor: '', data: '' },

    // === Investimentos ===
    ativos: [],
    operacoesPorAtivo: {},  // { ativoId: [op, op, ...] }
    resumoInvest: { n_ativos: 0 },
    evolucaoTemDados: false,
    _chartPatrimonio: null,
    alocacao: { linhas: [], total_brl: 0, tem_alvo: false, soma_alvo: 0 },
    alocacaoAlvoEdit: {},
    _chartAlocacao: null,
    cdiStatus: null,
    sincronizandoCDI: false,
    cambioStatus: null,
    sincronizandoCambio: false,
    cambioManual: '',
    atualizandoTudo: false,
    cambioModalAberto: false,
    cambioManualEdit: { USD: '', EUR: '' },
    tiposAtivo: [],
    moedasAtivo: ['BRL', 'USD', 'EUR', 'GBP'],
    ativoExpandido: null,
    ordemInvest: 'valor',   // valor | tipo | data | rentab | nome (dentro do grupo)
    gruposAbertos: {},      // { tipo: bool } — grupos colapsáveis por tipo
    formAtivoAberto: false,
    editandoAtivoId: null,
    ativoForm: { nome: '', ticker: '', tipo: 'Tesouro Direto', moeda: 'BRL', instituicao: '', detalhes_taxa: '', data_vencimento: '', observacoes: '', rendimento_incorpora_saldo: null, cdi_percentual: '', objetivo: 'patrimonio' },

    // Tipos que por default incorporam rendimento ao saldo (renda fixa).
    TIPOS_RF: ['Tesouro Direto','CDB','RDB','LCI','LCA','Fundo DI'],
    formOpAtivoId: null,
    opForm: { tipo: 'Compra', data: '', quantidade: '', preco_unitario: '', valor_total: '', moeda_operacao: 'BRL', cotacao_cambio: '', taxas: '', resgate_total: false, observacoes: '' },

    // Modais de senha
    modalSenha: { show: false, filename: '', senha: '', file: null },
    modalEscolhaConta: { show: false, filename: '', banco: '', candidatas: [], escolhida: '' },
    contaIdEscolhida: null,
    modalSalvarSenha: { show: false, banco: '', senha: '' },

    // Fila de PDFs aguardando processamento
    filaUpload: [],

    // Toast
    toast: { show: false, msg: '', tipo: 'ok' },

    atualizando: false,

    // Auto-atualização do app (.exe instalado, via GitHub Releases)
    appUpdate: { tem_atualizacao: false, versao_atual: '', versao_disponivel: null,
                 notas: '', url_release: '', instalado: false, repo: '', erro: null },
    instalandoUpdate: false,
    verificandoUpdate: false,
    updateDispensado: false,

    // Compartilhamento na rede (acesso pelo celular)
    rede: { compartilhando: false, tem_pin: false, auto: false, ip: null, porta: null, url: null },
    redePin: '',
    redeBusy: false,
    redeQrPronto: false,

    async init() {
      this._carregarOcultos();
      await this.carregarCatalogos();
      await this.carregarDashboard();
      // Verifica e, se houver versão nova no app instalado, atualiza sozinho
      // (o servidor faz backup do banco antes). Em dev (.py) nunca instala.
      await this.verificarAtualizacao();
      if (this.appUpdate.tem_atualizacao && this.appUpdate.instalado) {
        this.instalarAtualizacao({ auto: true });
      }
    },

    async verificarAtualizacao() {
      try {
        const r = await fetch('/api/atualizacao/status');
        if (r.ok) this.appUpdate = await r.json();
      } catch (e) { /* offline / sem repo: silencioso */ }
    },

    async verificarAtualizacaoManual() {
      this.verificandoUpdate = true;
      try {
        await this.verificarAtualizacao();
        if (this.appUpdate.tem_atualizacao) this.notificar('Há uma versão nova disponível!', 'ok');
        else if (!this.appUpdate.erro) this.notificar('Você está na versão mais recente.', 'ok');
        else this.notificar('Não consegui verificar agora.', 'erro');
      } finally { this.verificandoUpdate = false; }
    },

    async instalarAtualizacao(opts = {}) {
      if (!this.appUpdate.instalado) {
        if (!opts.auto) this.notificar('Auto-instalação só no app instalado (.exe).', 'erro');
        return;
      }
      // No modo automático (início do app) não pergunta nada — só avisa.
      if (!opts.auto) {
        if (!confirm(`Atualizar para a versão ${this.appUpdate.versao_disponivel}?\n\n` +
                     'O Nexum vai fechar, instalar a nova versão e reabrir sozinho.')) return;
      }
      this.instalandoUpdate = true;
      this.updateDispensado = false;   // garante o banner visível durante a troca
      try {
        const r = await fetch('/api/atualizacao/instalar', { method: 'POST' });
        if (r.ok) {
          this.notificar(`Atualizando para ${this.appUpdate.versao_disponivel}… ` +
                         'backup do banco feito. O Nexum vai reabrir em instantes.', 'ok');
          // O servidor encerra logo após responder; a página vai cair — normal.
        } else {
          const d = await r.json().catch(() => ({}));
          this.notificar(d.detail || 'Falha ao atualizar', 'erro');
          this.instalandoUpdate = false;
        }
      } catch (e) {
        // Conexão caiu = o app fechou pra atualizar. Esperado.
        this.notificar('Atualizando… aguarde o Nexum reabrir.', 'ok');
      }
    },

    async atualizarTudo() {
      this.atualizando = true;
      try {
        await this.carregarCatalogos();
        await this.carregarDashboard();
        if (this.view === 'transacoes') await this.carregarTransacoes();
        if (this.view === 'investimentos') await this.carregarInvestimentos();
        if (this.view === 'metas') await this.carregarMetas();
        if (this.view === 'extrato') {
          await this.carregarContasExtrato();
          if (this.extrato.conta_id) await this.carregarExtrato();
        }
        if (this.view === 'config') {
          if (this.subView === 'perfil') await this.carregarConfig();
          else if (this.subView === 'contas') await this.carregarContas();
          else if (this.subView === 'bancos') await this.carregarBancos();
          else if (this.subView === 'categorias') await this.carregarCategoriasDetalhe();
          else if (this.subView === 'atribuicoes') await this.carregarAtribuicoesDetalhe();
          else if (this.subView === 'regras') await this.carregarRegras();
          else if (this.subView === 'arquivos') await this.carregarFaturas();
        }
        this.notificar('Atualizado', 'ok');
      } catch (e) {
        this.notificar('Erro ao atualizar: ' + e.message, 'erro');
      } finally {
        this.atualizando = false;
      }
    },

    async carregarCatalogos() {
      const [c, cat, atr, banc] = await Promise.all([
        fetch('/api/contas').then(r => r.json()),
        fetch('/api/categorias').then(r => r.json()),
        fetch('/api/atribuicoes').then(r => r.json()),
        fetch('/api/bancos').then(r => r.json()),
      ]);
      this.contas = c;
      this.categorias = cat;
      this.atribuicoes = atr;
      this.bancos = banc;
    },

    async carregarBancos() {
      this.bancos = await fetch('/api/bancos').then(r => r.json());
    },

    abrirFormBanco() {
      this.bancoForm = { nome: '', cor: '#888888' };
      this.formBancoAberto = true;
    },

    async salvarNovoBanco() {
      const f = this.bancoForm;
      if (!f.nome) { this.notificar('Nome obrigatório', 'erro'); return; }
      const r = await fetch('/api/bancos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(f),
      });
      const data = await r.json();
      if (!r.ok) { this.notificar(data.detail || 'Erro', 'erro'); return; }
      this.notificar(`Banco "${f.nome}" criado`, 'ok');
      this.formBancoAberto = false;
      await this.carregarBancos();
      await this.carregarCatalogos();
    },

    async renomearBanco(id, valor) {
      const novo = (valor || '').trim();
      const b = this.bancos.find(x => x.id === id);
      if (!b || novo === b.nome || !novo) {
        await this.carregarBancos();
        return;
      }
      const r = await fetch(`/api/bancos/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome: novo }),
      });
      if (r.ok) {
        this.notificar('Banco renomeado', 'ok');
        await this.carregarCatalogos();
        await this.carregarContas();
      } else {
        this.notificar('Erro', 'erro');
        await this.carregarBancos();
      }
    },

    async excluirBanco(id, nome) {
      if (!confirm(`Excluir o banco "${nome}"?\n\nNão dá pra excluir banco com contas vinculadas.`)) return;
      const r = await fetch(`/api/bancos/${id}`, { method: 'DELETE' });
      const data = await r.json();
      if (!r.ok) { this.notificar(data.detail || 'Erro', 'erro'); return; }
      this.notificar('Banco excluído', 'ok');
      await this.carregarBancos();
      await this.carregarCatalogos();
    },

    async carregarDashboard() {
      const t = Date.now();
      const params = new URLSearchParams({ _: t });

      // Resolve período baseado no preset
      const range = this.calcularRangePeriodo();
      if (range) {
        params.set('data_inicio', range.data_inicio);
        params.set('data_fim', range.data_fim);
      } else if (this.dashboard.mes) {
        params.set('mes', this.dashboard.mes);
      }

      const url = `/api/dashboard?${params.toString()}`;
      const data = await fetch(url).then(r => r.json());
      this.dashboard = { ...this.dashboard, ...data };

      // Carrega previsão de parcelas futuras (independe do mês selecionado)
      try {
        this.previsao = await fetch(`/api/dashboard/previsao?meses=6&_=${t}`).then(r => r.json());
      } catch (e) {
        this.previsao = { meses: [] };
      }

      // Carrega saldo de empréstimos (independe do mês — é cumulativo)
      try {
        this.emprestimos = await fetch(`/api/emprestimos/saldo?_=${t}`).then(r => r.json());
      } catch (e) {
        this.emprestimos = { pessoas: [], total_a_receber: 0, total_a_pagar: 0, sem_atribuicao: { despesa: 0, receita: 0 } };
      }

      // Renderiza gráficos depois que o DOM atualizar
      this.$nextTick(() => this.renderizarGraficos());
    },

    // === Orçamento (aba própria) ===
    async carregarOrcamentos() {
      try {
        const pmes = this.orcamentoMes ? `&mes=${encodeURIComponent(this.orcamentoMes)}` : '';
        const d = await fetch(`/api/orcamentos?_=${Date.now()}${pmes}`).then(r => r.json());
        this.orcamentos = d;
        if (d && d.mes) this.orcamentoMes = d.mes;   // sincroniza o seletor com o mês resolvido
      } catch (e) {
        this.orcamentos = { itens: [], total_orcado: 0, total_gasto: 0, mes: this.orcamentoMes };
      }
    },

    // Navega meses no seletor de orçamento (delta = -1 anterior, +1 próximo).
    mudarMesOrcamento(delta) {
      const base = this.orcamentoMes || this.orcamentos.mes;
      if (!base || !base.includes('/')) return;
      let [m, y] = base.split('/').map(Number);
      m += delta;
      if (m < 1) { m = 12; y -= 1; }
      else if (m > 12) { m = 1; y += 1; }
      this.orcamentoMes = String(m).padStart(2, '0') + '/' + y;
      this.carregarOrcamentos();
    },

    // Monta {labels, valores, cores, tipo} conforme o tipo de gráfico escolhido.
    _dadosGraficoDistribuicao() {
      const paleta = [
        '#f59e0b', '#dc2626', '#10b981', '#3b82f6', '#a855f7',
        '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#eab308',
        '#8b5cf6', '#14b8a6', '#ef4444', '#0ea5e9', '#22c55e',
      ];
      const d = this.dashboard;
      const t = this.tipoGrafico;

      if (t === 'essencial') {
        const ess = d.despesas_essenciais || 0;
        const dis = d.despesas_discricionarias || 0;
        if (ess + dis <= 0) return null;
        return {
          chart: 'doughnut',
          labels: ['Essenciais', 'Não essenciais'],
          valores: [ess, dis],
          cores: ['#3b82f6', '#f59e0b'],
        };
      }
      if (t === 'receita_despesa') {
        const rec = d.receitas || 0;
        const des = d.despesas || 0;
        if (rec + des <= 0) return null;
        // Receitas e despesas não são partes de um todo — comparar em barras
        // (lado a lado) faz mais sentido que pizza.
        return {
          chart: 'bar',
          labels: ['Receitas', 'Despesas'],
          valores: [rec, des],
          cores: ['#10b981', '#ef4444'],
        };
      }

      // Tipos baseados em listas nome/total.
      let itens = [];
      if (t === 'categoria')  itens = (d.por_categoria || []).map(c => ({ nome: `${c.icone || ''} ${c.nome}`.trim(), total: c.total }));
      if (t === 'atribuicao') itens = (d.por_atribuicao || []).map(a => ({ nome: a.nome, total: a.total, cor: a.cor }));
      if (t === 'forma')      itens = (d.por_forma || []).map(f => ({ nome: f.nome, total: f.total }));
      if (t === 'banco')      itens = (d.por_banco || []).map(b => ({ nome: b.nome, total: b.total }));
      itens = itens.filter(i => i.total > 0);
      if (itens.length === 0) return null;
      return {
        chart: 'doughnut',
        labels: itens.map(i => i.nome),
        valores: itens.map(i => i.total),
        cores: itens.map((i, idx) => i.cor || paleta[idx % paleta.length]),
      };
    },

    async renderizarGraficos() {
      // ===== Gráfico de distribuição (tipo alternável) =====
      const elCat = document.getElementById('chart-categoria');
      if (elCat && window.Chart) {
        // Destrói qualquer chart anterior associado a este canvas (inclusive
        // instâncias "fantasma" que sobreviveram a remontagem do DOM)
        const existenteCat = Chart.getChart(elCat);
        if (existenteCat) existenteCat.destroy();
        if (this._chartCat) { try { this._chartCat.destroy(); } catch (e) {} }
        this._chartCat = null;

        const dados = this._dadosGraficoDistribuicao();
        if (dados) {
          const ehBar = dados.chart === 'bar';
          this._chartCat = new Chart(elCat, {
            type: dados.chart,
            data: {
              labels: dados.labels,
              datasets: [{
                data: dados.valores,
                backgroundColor: dados.cores,
                borderColor: ehBar ? dados.cores : '#09090b',
                borderWidth: ehBar ? 0 : 2,
                borderRadius: ehBar ? 6 : 0,
                maxBarThickness: 120,
              }],
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                // Barras: rótulos ficam no eixo X, legenda lateral é redundante.
                legend: ehBar ? { display: false } : {
                  position: 'right',
                  labels: { color: '#a1a1aa', font: { family: 'IBM Plex Sans', size: 11 }, boxWidth: 12 },
                },
                tooltip: {
                  callbacks: {
                    label: (ctx) => {
                      if (ehBar) return `${ctx.label}: ${this.brl(ctx.parsed.y)}`;
                      const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                      const pct = total > 0 ? (ctx.parsed / total * 100).toFixed(1) : 0;
                      return `${ctx.label}: ${this.brl(ctx.parsed)} (${pct}%)`;
                    },
                  },
                },
              },
              ...(ehBar ? {
                scales: {
                  y: {
                    beginAtZero: true,
                    grid: { color: 'rgba(161,161,170,0.1)' },
                    ticks: { color: '#a1a1aa', font: { family: 'IBM Plex Sans', size: 11 }, callback: (v) => this.brl(v) },
                  },
                  x: {
                    grid: { display: false },
                    ticks: { color: '#a1a1aa', font: { family: 'IBM Plex Sans', size: 12 } },
                  },
                },
              } : { cutout: '60%' }),
            },
          });
        }
      }

      // ===== Linha de evolução mensal =====
      const elEvo = document.getElementById('chart-evolucao');
      if (elEvo && window.Chart) {
        const existenteEvo = Chart.getChart(elEvo);
        if (existenteEvo) existenteEvo.destroy();
        if (this._chartEvo) { try { this._chartEvo.destroy(); } catch (e) {} }
        this._chartEvo = null;
        try {
          const evo = await fetch('/api/dashboard/evolucao?meses=12').then(r => r.json());
          if (evo.labels && evo.labels.length > 0) {
            // Pós-await: uma chamada concorrente de renderizarGraficos() pode ter
            // criado um chart neste canvas enquanto buscávamos os dados. Destrói
            // o que estiver lá antes de recriar (evita "Canvas is already in use").
            const fantasmaEvo = Chart.getChart(elEvo);
            if (fantasmaEvo) fantasmaEvo.destroy();
            this._chartEvo = new Chart(elEvo, {
              type: 'line',
              data: {
                labels: evo.labels,
                datasets: [
                  {
                    label: 'Despesas',
                    data: evo.despesas,
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    fill: true,
                    tension: 0.3,
                  },
                  {
                    label: 'Receitas',
                    data: evo.receitas,
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    fill: true,
                    tension: 0.3,
                  },
                ],
              },
              options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                  legend: { labels: { color: '#a1a1aa', font: { family: 'IBM Plex Sans', size: 11 } } },
                  tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${this.brl(ctx.parsed.y)}` } },
                },
                scales: {
                  x: { ticks: { color: '#71717a', font: { family: 'IBM Plex Mono', size: 10 } }, grid: { color: '#27272a' } },
                  y: { ticks: { color: '#71717a', font: { family: 'IBM Plex Mono', size: 10 },
                                callback: (v) => 'R$ ' + (v/1000).toFixed(1) + 'k' },
                       grid: { color: '#27272a' } },
                },
              },
            });
          }
        } catch (e) { console.error('Erro gráfico evolução', e); }
      }
    },

    async carregarTransacoes() {
      const params = new URLSearchParams();
      Object.entries(this.filtros).forEach(([k, v]) => {
        if (v !== '' && v !== false && v !== null) params.set(k, v);
      });
      const data = await fetch('/api/transacoes?' + params).then(r => r.json());
      this.transacoes = data.items;
      this.totalTransacoes = data.total;
      this.totaisListagem = {
        receitas: data.total_receitas || 0,
        despesas: data.total_despesas || 0,
        saldo: data.saldo || 0,
      };
      this.nSuspeitas = data.n_suspeitas || 0;
    },

    // === Suspeitas de duplicata ===
    async abrirRevisaoSuspeitas() {
      this.modalSuspeitas = true;
      this.carregandoSuspeitas = true;
      try {
        const data = await fetch('/api/transacoes/suspeitas').then(r => r.json());
        this.suspeitasItems = data.items || [];
      } catch (e) {
        this.notificar('Erro ao carregar suspeitas', 'erro');
      } finally {
        this.carregandoSuspeitas = false;
      }
    },

    async aceitarSuspeita(id) {
      try {
        const r = await fetch(`/api/transacoes/${id}/aceitar-suspeita`, { method: 'POST' });
        if (!r.ok) throw new Error();
        this.suspeitasItems = this.suspeitasItems.filter(it => it.suspeita.id !== id);
        this.nSuspeitas = Math.max(0, this.nSuspeitas - 1);
        if (this.suspeitasItems.length === 0) {
          this.modalSuspeitas = false;
        }
        await this.carregarTransacoes();
        await this.carregarDashboard();
      } catch (e) {
        this.notificar('Erro ao aceitar', 'erro');
      }
    },

    async descartarSuspeita(id) {
      try {
        const r = await fetch(`/api/transacoes/${id}/descartar-suspeita`, { method: 'POST' });
        if (!r.ok) throw new Error();
        this.suspeitasItems = this.suspeitasItems.filter(it => it.suspeita.id !== id);
        this.nSuspeitas = Math.max(0, this.nSuspeitas - 1);
        if (this.suspeitasItems.length === 0) {
          this.modalSuspeitas = false;
        }
        await this.carregarTransacoes();
      } catch (e) {
        this.notificar('Erro ao descartar', 'erro');
      }
    },

    async aceitarTodasSuspeitas() {
      if (!confirm(`Aceitar todas as ${this.nSuspeitas} suspeitas? Vão virar transações normais.`)) return;
      try {
        const r = await fetch('/api/transacoes/aceitar-todas-suspeitas', { method: 'POST' });
        const data = await r.json();
        this.notificar(`${data.aceitas} suspeitas aceitas`, 'ok');
        this.modalSuspeitas = false;
        this.suspeitasItems = [];
        this.nSuspeitas = 0;
        await this.carregarTransacoes();
        await this.carregarDashboard();
      } catch (e) {
        this.notificar('Erro', 'erro');
      }
    },

    async descartarTodasSuspeitas() {
      if (!confirm(`Descartar todas as ${this.nSuspeitas} suspeitas? Elas serão excluídas permanentemente.`)) return;
      try {
        const r = await fetch('/api/transacoes/descartar-todas-suspeitas', { method: 'POST' });
        const data = await r.json();
        this.notificar(`${data.descartadas} suspeitas descartadas`, 'ok');
        this.modalSuspeitas = false;
        this.suspeitasItems = [];
        this.nSuspeitas = 0;
        await this.carregarTransacoes();
      } catch (e) {
        this.notificar('Erro', 'erro');
      }
    },

    // === Períodos ===
    /**
     * Calcula range de datas baseado no preset selecionado.
     * Retorna { data_inicio, data_fim } ou null (modo mês padrão).
     */
    calcularRangePeriodo() {
      const hoje = new Date();
      const fmt = (d) => d.toISOString().slice(0, 10);

      switch (this.periodoPreset) {
        case 'mes':
          return null;  // Modo mês padrão (mes_referencia)
        case '3meses': {
          // Últimos 3 meses CHEIOS (inclui o mês atual)
          // Ex: hoje 12/05/2026 → 01/03/2026 a 31/05/2026
          const fimMes = new Date(hoje.getFullYear(), hoje.getMonth() + 1, 0);  // último dia do mês atual
          const iniMes = new Date(hoje.getFullYear(), hoje.getMonth() - 2, 1);  // primeiro dia de 2 meses atrás
          return { data_inicio: fmt(iniMes), data_fim: fmt(fimMes) };
        }
        case 'ano': {
          const ini = new Date(hoje.getFullYear(), 0, 1);
          const fim = new Date(hoje.getFullYear(), 11, 31);
          return { data_inicio: fmt(ini), data_fim: fmt(fim) };
        }
        case 'personalizado':
          if (this.periodoCustom.data_inicio && this.periodoCustom.data_fim) {
            return { data_inicio: this.periodoCustom.data_inicio, data_fim: this.periodoCustom.data_fim };
          }
          return null;
        default:
          return null;
      }
    },

    rotuloPeriodo() {
      const r = this.calcularRangePeriodo();
      if (!r) return this.dashboard.mes || '';
      // Formata pra DD/MM/YYYY
      const fmt = (iso) => {
        const [y, m, d] = iso.split('-');
        return `${d}/${m}/${y}`;
      };
      return `${fmt(r.data_inicio)} a ${fmt(r.data_fim)}`;
    },

    labelInvestido() {
      switch (this.periodoPreset) {
        case 'mes': return 'Investido no mês';
        case '3meses': return 'Investido em 3 meses';
        case 'ano': return 'Investido no ano';
        case 'personalizado': return 'Investido no período';
        default: return 'Investido no período';
      }
    },

    /**
     * Alterna a ordenação ao clicar num cabeçalho.
     * Sequência: clicar coluna nova → asc; clicar de novo → desc; clicar de novo → asc.
     */
    toggleOrdem(coluna) {
      if (this.ordenacao.coluna === coluna) {
        this.ordenacao.direcao = this.ordenacao.direcao === 'asc' ? 'desc' : 'asc';
      } else {
        this.ordenacao.coluna = coluna;
        this.ordenacao.direcao = 'asc';
      }
    },

    setaOrdem(coluna) {
      if (this.ordenacao.coluna !== coluna) return '';
      return this.ordenacao.direcao === 'asc' ? '↑' : '↓';
    },

    /**
     * Retorna lista ordenada conforme estado atual.
     * Ordenação client-side — instantânea, sem ida ao backend.
     * Estratégia por tipo de coluna:
     *   - data, mes_referencia: cronológico
     *   - valor: numérico
     *   - resto: alfabético PT-BR (NFD + remove combining marks)
     */
    transacoesOrdenadas() {
      const { coluna, direcao } = this.ordenacao;
      const sinal = direcao === 'asc' ? 1 : -1;
      const lista = [...this.transacoes];

      // Helper: comparação alfabética PT-BR (Água ordena como agua)
      const norm = s => (s || '').normalize('NFD').replace(/\p{Mn}/gu, '').toLowerCase();

      lista.sort((a, b) => {
        let va, vb;
        switch (coluna) {
          case 'data': {
            // YYYY-MM-DD compara bem como string
            va = a.data || '';
            vb = b.data || '';
            return va.localeCompare(vb) * sinal;
          }
          case 'mes_referencia': {
            // MM/YYYY → YYYY*12 + MM pra comparar cronologicamente
            const toInt = m => {
              if (!m) return 0;
              const [mm, yy] = m.split('/');
              return parseInt(yy) * 12 + parseInt(mm);
            };
            return (toInt(a.mes_referencia) - toInt(b.mes_referencia)) * sinal;
          }
          case 'valor': {
            return ((a.valor || 0) - (b.valor || 0)) * sinal;
          }
          case 'tipo':
          case 'banco':
          case 'descricao':
          case 'descricao_personalizada':
          case 'categoria':
          case 'atribuicao': {
            // (sem categoria/atribuição) sempre vão pro fim, independente da direção
            const a_vazio = !a[coluna];
            const b_vazio = !b[coluna];
            if (a_vazio && !b_vazio) return 1;
            if (!a_vazio && b_vazio) return -1;
            if (a_vazio && b_vazio) return 0;
            return norm(a[coluna]).localeCompare(norm(b[coluna])) * sinal;
          }
          default:
            return 0;
        }
      });

      return lista;
    },

    // === Seleção em massa ===
    /** Verifica se um id está selecionado. */
    estaSelecionada(id) {
      return this.selecionadas.includes(id);
    },

    /** Alterna a seleção de uma transação. */
    toggleSelecao(id) {
      const idx = this.selecionadas.indexOf(id);
      if (idx >= 0) {
        this.selecionadas.splice(idx, 1);
      } else {
        this.selecionadas.push(id);
      }
    },

    /** Estado do checkbox do header: true se TODAS visíveis estão selecionadas.
     *  Usa a lista filtrada crua (a ORDEM não importa pra checar pertencimento),
     *  evitando re-ordenar tudo a cada clique de seleção. */
    todasSelecionadas() {
      const visiveis = this.transacoes;
      if (visiveis.length === 0) return false;
      const sel = new Set(this.selecionadas);
      return visiveis.every(t => sel.has(t.id));
    },

    /** Checkbox do header: marca/desmarca todas as visíveis. */
    toggleTodas() {
      const visiveis = this.transacoes;
      if (this.todasSelecionadas()) {
        // Desmarca só as visíveis (não mexe em outras que possam estar selecionadas)
        const idsVisiveis = new Set(visiveis.map(t => t.id));
        this.selecionadas = this.selecionadas.filter(id => !idsVisiveis.has(id));
      } else {
        // Marca todas as visíveis
        const idsVisiveis = visiveis.map(t => t.id);
        const novosIds = idsVisiveis.filter(id => !this.selecionadas.includes(id));
        this.selecionadas = [...this.selecionadas, ...novosIds];
      }
    },

    limparSelecao() {
      this.selecionadas = [];
      this.bulkForm = { categoria_id: '', atribuicao_id: '', aplicar_categoria: false, aplicar_atribuicao: false };
    },

    /**
     * Aplica categoria/atribuição em todas as selecionadas.
     * Pelo menos um dos dois switches precisa estar marcado.
     */
    async aplicarEmMassa() {
      const f = this.bulkForm;
      if (!f.aplicar_categoria && !f.aplicar_atribuicao) {
        this.notificar('Marque categoria, atribuição, ou ambos', 'erro');
        return;
      }
      if (this.selecionadas.length === 0) {
        this.notificar('Nenhuma transação selecionada', 'erro');
        return;
      }

      const body = { ids: this.selecionadas };
      if (f.aplicar_categoria) {
        body.categoria_id = f.categoria_id ? parseInt(f.categoria_id) : null;
      }
      if (f.aplicar_atribuicao) {
        body.atribuicao_id = f.atribuicao_id ? parseInt(f.atribuicao_id) : null;
      }

      // Confirm pra evitar acidente — descreve o que vai acontecer
      const partes = [];
      if (f.aplicar_categoria) {
        const cat = this.categorias.find(c => c.id === parseInt(f.categoria_id));
        partes.push(`categoria → ${cat ? cat.nome : '(sem categoria)'}`);
      }
      if (f.aplicar_atribuicao) {
        const atr = this.atribuicoes.find(a => a.id === parseInt(f.atribuicao_id));
        partes.push(`atribuição → ${atr ? atr.nome : '(sem atribuição)'}`);
      }
      const confirma = confirm(
        `Aplicar em ${this.selecionadas.length} transação(ões):\n  ${partes.join('\n  ')}\n\nProsseguir?`
      );
      if (!confirma) return;

      try {
        const r = await fetch('/api/transacoes/atualizar-em-massa', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await r.json();
        if (!r.ok) {
          this.notificar(data.detail || 'Erro ao aplicar', 'erro');
          return;
        }
        this.notificar(`${data.atualizadas} transação(ões) atualizadas`, 'ok');
        this.limparSelecao();
        await this.carregarTransacoes();
        await this.carregarDashboard();
      } catch (e) {
        console.error(e);
        this.notificar('Erro de rede', 'erro');
      }
    },

    async atualizarTransacao(id, campo, valor) {
      const dados = {};
      dados[campo] = valor ? parseInt(valor) : null;

      try {
        // 1. Salva no servidor
        const r = await fetch(`/api/transacoes/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(dados),
        });
        if (!r.ok) {
          this.notificar('Erro ao atualizar', 'erro');
          return;
        }

        // 2. Se a transação é parcelada, oferece propagar pras irmãs
        const propagado = await this.propagarSeParcelado(id);

        // 3. Tenta reclassificar pendentes (memória aprende com edições)
        let nReclassificadas = 0;
        try {
          const recRes = await fetch('/api/transacoes/reclassificar', { method: 'POST' });
          if (recRes.ok) {
            const rec = await recRes.json();
            nReclassificadas = rec.reclassificadas || 0;
          }
        } catch (e) {
          console.error('Reclassificar falhou (não crítico):', e);
        }

        // 4. Sempre re-busca a lista completa do servidor (evita divergências)
        await this.carregarTransacoes();

        // 5. Notificação consolidada
        const partes = [];
        if (propagado.atualizadas > 0) {
          partes.push(`${propagado.atualizadas} parcela(s) espelhadas`);
        }
        if (nReclassificadas > 0) {
          partes.push(`${nReclassificadas} classificada(s) pela memória`);
        }
        const msg = partes.length ? `Salvo. ${partes.join(', ')}.` : 'Salvo';
        this.notificar(msg, 'ok');
      } catch (e) {
        console.error('Erro em atualizarTransacao:', e);
        this.notificar('Erro inesperado: ' + e.message, 'erro');
        await this.carregarTransacoes();
      }
    },

    /**
     * Se a transação é parcelada (campo `parcela` tipo "X/N"), olha quais irmãs
     * existem e propaga categoria/atribuição/descrição_personalizada.
     *
     * Lógica:
     *   - Sem irmãs: não faz nada
     *   - Irmãs com campos vazios ou já iguais: propaga silenciosamente (forcar=false)
     *   - Irmãs com valores divergentes: pergunta antes (confirm)
     *
     * Retorna {atualizadas, divergentes}.
     */
    async propagarSeParcelado(id) {
      try {
        const previewRes = await fetch(`/api/transacoes/${id}/preview-propagacao`);
        if (!previewRes.ok) return { atualizadas: 0, divergentes: 0 };
        const preview = await previewRes.json();

        if (preview.irmas_total === 0) {
          return { atualizadas: 0, divergentes: 0 };
        }

        let forcar = false;
        if (preview.divergentes > 0) {
          // Pergunta antes de sobrescrever divergências
          const ok = confirm(
            `Esta compra tem ${preview.irmas_total} outras parcelas.\n\n` +
            `${preview.divergentes} delas têm classificação diferente da que você acabou de definir.\n` +
            `${preview.vazias} estão sem classificação.\n` +
            `${preview.iguais} já batem.\n\n` +
            `Sobrescrever as ${preview.divergentes} divergentes pela nova classificação?`
          );
          if (ok) {
            forcar = true;
          } else {
            // Usuário recusou — só propaga pras vazias (forcar=false)
            // Se não tem vazias, retorna sem fazer nada
            if (preview.vazias === 0) {
              return { atualizadas: 0, divergentes: preview.divergentes };
            }
          }
        }

        const propRes = await fetch(
          `/api/transacoes/${id}/propagar?forcar=${forcar}`,
          { method: 'POST' }
        );
        if (!propRes.ok) return { atualizadas: 0, divergentes: 0 };
        return await propRes.json();
      } catch (e) {
        console.error('Erro propagando parcelas:', e);
        return { atualizadas: 0, divergentes: 0 };
      }
    },

    /**
     * Alterna o estado essencial/discricionário de uma transação.
     *
     * Lógica do ciclo:
     *   - Sem override (segue categoria): clica → vira override DO CONTRÁRIO da categoria
     *   - Com override: clica → volta a "sem override" (segue categoria de novo)
     *
     * Exemplos:
     *   - Transação Lazer (cat = discricionário ☆), sem override
     *     → clica → vira ★ override (essencial mesmo a categoria sendo discricionária)
     *     → clica → volta a ☆ (segue categoria)
     */
    abrirModalNovaTransacao() {
      // Preenche conta padrão (Dinheiro, se existir)
      const contaDinheiro = this.contas.find(c => c.tipo === 'Carteira') || this.contas[0];
      this.novaTransacaoForm = {
        data: new Date().toISOString().slice(0, 10),
        descricao: '',
        valor: '',
        tipo: 'Despesa',
        conta_id: contaDinheiro ? contaDinheiro.id : '',
        categoria_id: '',
        atribuicao_id: '',
        forma_pagamento: '',
        observacoes: '',
      };
      this.modalNovaTransacao = true;
    },

    async salvarNovaTransacao() {
      const f = this.novaTransacaoForm;
      if (!f.descricao.trim()) { this.notificar('Descrição obrigatória', 'erro'); return; }
      if (!f.valor || parseFloat(f.valor) <= 0) { this.notificar('Valor inválido', 'erro'); return; }
      if (!f.conta_id) { this.notificar('Conta obrigatória', 'erro'); return; }
      if (!f.data) { this.notificar('Data obrigatória', 'erro'); return; }

      try {
        const r = await fetch('/api/transacoes', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            data: f.data,
            descricao: f.descricao.trim(),
            valor: parseFloat(f.valor),
            tipo: f.tipo,
            conta_id: parseInt(f.conta_id),
            categoria_id: f.categoria_id ? parseInt(f.categoria_id) : null,
            atribuicao_id: f.atribuicao_id ? parseInt(f.atribuicao_id) : null,
            forma_pagamento: f.forma_pagamento || null,
            observacoes: f.observacoes || null,
          }),
        });
        const data = await r.json();
        if (!r.ok) {
          this.notificar(data.detail || 'Erro ao criar', 'erro');
          return;
        }
        this.notificar('Transação criada', 'ok');
        this.modalNovaTransacao = false;
        await this.carregarTransacoes();
        await this.carregarDashboard();
      } catch (e) {
        console.error(e);
        this.notificar('Erro de rede', 'erro');
      }
    },

    async detectarEstornos() {
      if (!confirm('Vou analisar todas as receitas e tentar identificar estornos automaticamente. Continuar?')) return;
      try {
        const r = await fetch('/api/transacoes/detectar-estornos', { method: 'POST' });
        const data = await r.json();
        if (!r.ok) {
          this.notificar(data.detail || 'Erro', 'erro');
          return;
        }
        this.notificar(
          `${data.receitas_analisadas} receitas analisadas, ${data.vinculadas} estornos identificados`,
          'ok'
        );
        await this.carregarTransacoes();
        await this.carregarDashboard();
      } catch (e) {
        console.error(e);
        this.notificar('Erro de rede', 'erro');
      }
    },

    async toggleEssencial(t) {
      let novoOverride;
      if (t.essencial_override !== null && t.essencial_override !== undefined) {
        // Já tem override → remove, volta ao padrão da categoria
        novoOverride = null;
      } else {
        // Sem override → cria override do oposto da categoria
        novoOverride = !t.categoria_essencial;
      }

      try {
        const r = await fetch(`/api/transacoes/${t.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ essencial_override: novoOverride }),
        });
        if (!r.ok) {
          this.notificar('Erro ao alternar essencial', 'erro');
          return;
        }
        // Re-busca lista pra refletir + atualiza dashboard
        await this.carregarTransacoes();
        await this.carregarDashboard();
      } catch (e) {
        console.error(e);
        this.notificar('Erro de rede', 'erro');
      }
    },

    async salvarDescricaoPersonalizada(id, valor) {
      const t = this.transacoes.find(x => x.id === id);
      if (!t) return;
      const novo = (valor || '').trim();
      // se não mudou, não chama API
      if (novo === (t.descricao_personalizada || '')) return;

      const r = await fetch(`/api/transacoes/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ descricao_personalizada: novo }),
      });
      if (!r.ok) {
        this.notificar('Erro ao salvar descrição', 'erro');
        return;
      }

      // Propaga descrição pras parcelas irmãs também
      const propagado = await this.propagarSeParcelado(id);

      // Re-busca lista pra ficar consistente
      await this.carregarTransacoes();

      if (propagado.atualizadas > 0) {
        this.notificar(`Descrição salva. ${propagado.atualizadas} parcela(s) espelhadas.`, 'ok');
      }
    },

    async importarPDFs(event) {
      const files = Array.from(event.target.files);
      event.target.value = '';
      if (!files.length) return;
      this.filaUpload = files.slice();
      this.estatsImport = { novas: 0, dups: 0, cat: 0, jaImp: 0, erros: 0, detalhes: [], ultimoMes: null };
      await this.processarProximoUpload();
    },

    async processarProximoUpload(senhaExplicita = null) {
      if (this.filaUpload.length === 0) {
        // Acabou — mostra resumo
        const e = this.estatsImport;
        let msg = `${e.novas} novas, ${e.cat} categorizadas, ${e.dups} duplicadas`;
        if (e.jaImp) msg += `, ${e.jaImp} já importado(s)`;
        if (e.erros) {
          msg += `, ${e.erros} erro(s)`;
          if (e.detalhes.length > 0) msg += `\n${e.detalhes[0]}`;
        }
        this.notificar(msg, e.erros ? 'erro' : 'ok');

        // Pula o dashboard pro mês da fatura mais recente importada (se houver)
        if (e.ultimoMes) {
          this.dashboard.mes = e.ultimoMes;
        } else {
          // Sem mês específico: recarrega lista e deixa backend escolher o mais recente
          this.dashboard.mes = '';
        }
        await this.carregarDashboard();
        if (this.view === 'transacoes') await this.carregarTransacoes();
        if (this.view === 'faturas') await this.carregarFaturas();
        return;
      }

      const file = this.filaUpload[0];
      const fd = new FormData();
      fd.append('file', file);
      if (senhaExplicita) fd.append('senha', senhaExplicita);
      if (this.contaIdEscolhida) fd.append('conta_id', this.contaIdEscolhida);

      try {
        const r = await fetch('/api/import/fatura', { method: 'POST', body: fd });
        const data = await r.json();

        if (data.precisa_senha) {
          // Pausa a fila e abre modal pedindo senha
          this.modalSenha = { show: true, filename: file.name, senha: '', file };
          return;
        }

        if (data.ambiguidade_conta) {
          // Pausa fila e abre modal pra usuário escolher conta
          this.modalEscolhaConta = {
            show: true,
            filename: file.name,
            banco: data.banco,
            candidatas: data.contas_candidatas,
            escolhida: data.contas_candidatas[0]?.id || '',
          };
          return;
        }

        // Limpa a escolha após uso (não vaza pro próximo arquivo)
        this.contaIdEscolhida = null;

        if (data.ja_importado) {
          this.estatsImport.jaImp++;
        } else if (data.sucesso) {
          this.estatsImport.novas += data.n_inseridas;
          this.estatsImport.dups += data.n_duplicadas;
          this.estatsImport.cat += data.n_categorizadas;
          // Guarda o mês da fatura mais recente importada para navegar até ele
          this.estatsImport.ultimoMes = data.mes_referencia || this.estatsImport.ultimoMes;

          // Se uma senha explícita funcionou e ainda não está cadastrada, oferece salvar
          if (data.senha_funcionou) {
            this.modalSalvarSenha = {
              show: true,
              banco: data.banco,
              senha: data.senha_funcionou,
            };
          }
        } else {
          this.estatsImport.erros++;
          this.estatsImport.detalhes.push(`${file.name}: ${data.erro}`);
        }
      } catch (e) {
        this.estatsImport.erros++;
        // Tenta extrair mensagem mais útil que "erro de rede"
        const msg = e?.message ? `falha: ${e.message}` : 'erro de rede';
        this.estatsImport.detalhes.push(`${file.name}: ${msg}`);
        console.error('Falha no upload:', e);
      }

      // Avança fila
      this.filaUpload.shift();
      await this.processarProximoUpload();
    },

    async confirmarSenhaModal() {
      if (!this.modalSenha.senha) return;
      const senha = this.modalSenha.senha;
      this.modalSenha.show = false;
      this.modalSenha.senha = '';
      // Reprocessa o PDF atual da fila com a senha
      await this.processarProximoUpload(senha);
    },

    async confirmarEscolhaConta() {
      const id = this.modalEscolhaConta.escolhida;
      if (!id) return;
      this.contaIdEscolhida = parseInt(id);
      this.modalEscolhaConta.show = false;
      // Reprocessa o arquivo atual com a conta escolhida
      await this.processarProximoUpload();
    },

    cancelarEscolhaConta() {
      // Pula este arquivo
      this.modalEscolhaConta.show = false;
      this.contaIdEscolhida = null;
      this.estatsImport.erros++;
      this.estatsImport.detalhes.push(`${this.modalEscolhaConta.filename}: cancelado pelo usuário`);
      this.filaUpload.shift();
      this.processarProximoUpload();
    },

    async salvarSenhaSugerida() {
      const banco = this.modalSalvarSenha.banco;
      const senha = this.modalSalvarSenha.senha;
      // Procura a conta de cartão de crédito desse banco
      const conta = this.contas.find(c =>
        c.banco === banco && (c.tipo || '').toLowerCase().includes('cr')
      );
      if (!conta) {
        this.notificar('Não achei a conta correspondente para salvar a senha', 'erro');
        this.modalSalvarSenha.show = false;
        return;
      }
      const r = await fetch(`/api/contas/${conta.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ senha_pdf: senha }),
      });
      if (r.ok) {
        this.notificar(`Senha do ${banco} salva`, 'ok');
        await this.carregarCatalogos();
      }
      this.modalSalvarSenha.show = false;
    },

    async carregarContas() {
      this.contasDetalhe = await fetch('/api/contas').then(r => r.json());
    },

    iniciarEdicaoSenha(conta) {
      this.contaEditando = conta.id;
      this.senhaForm = '';
      this.senhaVisivel = false;
    },

    async salvarSenhaConta(contaId) {
      const r = await fetch(`/api/contas/${contaId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ senha_pdf: this.senhaForm }),
      });
      if (r.ok) {
        this.notificar('Senha salva', 'ok');
        this.contaEditando = null;
        this.senhaForm = '';
        await this.carregarContas();
        await this.carregarCatalogos();
      } else {
        this.notificar('Erro ao salvar', 'erro');
      }
    },

    async removerSenha(contaId) {
      if (!confirm('Remover a senha cadastrada desta conta?')) return;
      const r = await fetch(`/api/contas/${contaId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ senha_pdf: '' }),
      });
      if (r.ok) {
        this.notificar('Senha removida', 'ok');
        await this.carregarContas();
      }
    },

    async carregarSugestoes() {
      const data = await fetch('/api/conciliacao/sugestoes').then(r => r.json());
      this.sugestoes = data;
    },

    async confirmarConciliacao(s) {
      const r = await fetch('/api/conciliacao/aplicar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(s),
      });
      if (r.ok) {
        this.notificar('Conciliação aplicada', 'ok');
        await this.carregarSugestoes();
      } else {
        this.notificar('Erro ao aplicar', 'erro');
      }
    },

    async carregarRegras() {
      this.regras = await fetch('/api/regras').then(r => r.json());
    },

    novaRegra() {
      this.regraForm = { palavra_chave: '', categoria_id: '', atribuicao_id: '', prioridade: 5, comentario: '' };
      this.editandoRegra = true;
    },

    async salvarRegra() {
      if (!this.regraForm.palavra_chave) {
        this.notificar('Palavra-chave obrigatória', 'erro');
        return;
      }
      const dados = {
        palavra_chave: this.regraForm.palavra_chave,
        categoria_id: this.regraForm.categoria_id ? parseInt(this.regraForm.categoria_id) : null,
        atribuicao_id: this.regraForm.atribuicao_id ? parseInt(this.regraForm.atribuicao_id) : null,
        prioridade: parseInt(this.regraForm.prioridade) || 5,
        comentario: this.regraForm.comentario || '',
      };
      const r = await fetch('/api/regras', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dados),
      });
      if (r.ok) {
        this.editandoRegra = false;
        this.notificar('Regra criada', 'ok');
        await this.carregarRegras();
        // Reclassifica pendentes
        const rec = await fetch('/api/transacoes/reclassificar', { method: 'POST' }).then(r => r.json());
        if (rec.reclassificadas > 0) {
          this.notificar(`Regra aplicada a ${rec.reclassificadas} transações`, 'ok');
        }
      } else {
        this.notificar('Erro ao criar regra', 'erro');
      }
    },

    async excluirRegra(id) {
      if (!confirm('Excluir esta regra?')) return;
      await fetch(`/api/regras/${id}`, { method: 'DELETE' });
      await this.carregarRegras();
    },

    async carregarFaturas() {
      const t = Date.now();
      this.faturas = await fetch(`/api/faturas?_=${t}`).then(r => r.json());
      await this.carregarCobertura();
    },

    async carregarCobertura() {
      const t = Date.now();
      try {
        const data = await fetch(`/api/faturas/cobertura?meses=${this.cobertura.meses_n || 12}&_=${t}`).then(r => r.json());
        this.cobertura = { ...data, meses_n: this.cobertura.meses_n };
      } catch (e) {
        console.error('Erro carregando cobertura:', e);
      }
    },

    async marcarInicioUso(conta, mes) {
      // mes formato MM/YYYY — converte pra YYYY-MM-01
      const [mm, yyyy] = mes.split('/');
      const dataIso = `${yyyy}-${mm}-01`;
      if (!confirm(`Marcar ${mes} como início de uso da conta "${conta.nome_completo}"?\n\nMeses anteriores vão aparecer como "não se aplica" (sem alerta).`)) return;
      const r = await fetch(`/api/contas/${conta.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data_inicio_uso: dataIso }),
      });
      if (r.ok) {
        this.notificar('Início de uso definido', 'ok');
        await this.carregarCobertura();
      } else {
        const data = await r.json().catch(() => ({}));
        this.notificar(data.detail || 'Erro', 'erro');
      }
    },

    async limparInicioUso(conta, mes) {
      if (!confirm(`Remover marca de início de uso da conta "${conta.nome_completo}"?\n\nTodos os meses voltam a ser monitorados normalmente.`)) return;
      const r = await fetch(`/api/contas/${conta.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data_inicio_uso: null }),
      });
      if (r.ok) {
        this.notificar('Marca removida', 'ok');
        await this.carregarCobertura();
      }
    },

    bancosUnicosDeFaturas() {
      return [...new Set(this.faturas.map(f => f.banco).filter(Boolean))].sort();
    },
    titularesUnicosDeFaturas() {
      return [...new Set(this.faturas.map(f => f.titular || '(você)'))].sort();
    },
    mesesUnicosDeFaturas() {
      return [...new Set(this.faturas.map(f => f.mes_referencia).filter(Boolean))]
        .sort((a, b) => {
          const [ma, ya] = a.split('/');
          const [mb, yb] = b.split('/');
          return (parseInt(yb) * 12 + parseInt(mb)) - (parseInt(ya) * 12 + parseInt(ma));
        });
    },

    faturasFiltradas() {
      const f = this.filtrosFaturas;
      const busca = f.busca.toLowerCase().trim();
      return this.faturas.filter(x => {
        if (busca && !(x.pdf_filename || '').toLowerCase().includes(busca)) return false;
        if (f.banco && x.banco !== f.banco) return false;
        if (f.titular && (x.titular || '(você)') !== f.titular) return false;
        if (f.tipo_conta && x.tipo_conta !== f.tipo_conta) return false;
        if (f.mes && x.mes_referencia !== f.mes) return false;
        return true;
      });
    },

    async excluirFatura(id) {
      if (!confirm('Excluir esta fatura E TODAS as transações dela? Esta ação é irreversível.')) return;
      await fetch(`/api/faturas/${id}`, { method: 'DELETE' });
      await this.carregarFaturas();
      await this.carregarDashboard();
    },

    // === Configurações: Perfil / Config ===
    async carregarConfig() {
      try {
        const data = await fetch('/api/config').then(r => r.json());
        this.config = { ...this.config, ...data };
        // Converte familia_nomes (";"-separated) pra textarea (linha por linha)
        if (this.config.familia_nomes) {
          this.config.familia_nomes_textarea = this.config.familia_nomes
            .split(';').map(s => s.trim()).filter(Boolean).join('\n');
        } else {
          this.config.familia_nomes_textarea = '';
        }
      } catch (e) {
        console.error('Erro carregando config:', e);
      }
    },

    async salvarConfig(chave, valor) {
      const r = await fetch(`/api/config/${chave}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ valor: valor || '' }),
      });
      if (r.ok) {
        this.notificar('Salvo', 'ok');
      } else {
        this.notificar('Erro ao salvar', 'erro');
      }
    },

    // === Compartilhar na rede (celular) ===
    async carregarRedeStatus() {
      try {
        const r = await fetch('/api/rede/status');
        if (!r.ok) return;
        this.rede = await r.json();
        if (this.rede.compartilhando && this.rede.url) this.$nextTick(() => this.renderQrRede());
      } catch (e) { /* silencioso */ }
    },

    async salvarAutoRede() {
      try {
        const r = await fetch('/api/rede/auto', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ativar: this.rede.auto }),
        });
        if (!r.ok) {
          const e = await r.json().catch(() => ({}));
          this.rede.auto = false;   // reverte o checkbox
          this.notificar(e.detail || 'Não consegui salvar.', 'erro');
          return;
        }
        const data = await r.json();
        await this.carregarRedeStatus();   // se ligou, já reflete compartilhando + URL/QR
        this.notificar(data.auto ? 'Ligado: vai compartilhar sozinho ao abrir o Nexum.' : 'Início automático desligado.', 'ok');
      } catch (e) {
        this.rede.auto = false;
        this.notificar('Erro ao salvar.', 'erro');
      }
    },

    async salvarPinRede() {
      const pin = (this.redePin || '').trim();
      if (pin.length < 4) { this.notificar('O PIN precisa ter ao menos 4 dígitos.', 'erro'); return; }
      try {
        const r = await fetch('/api/rede/pin', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pin }),
        });
        if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || 'erro'); }
        this.rede.tem_pin = true;
        this.redePin = '';
        this.notificar('PIN definido.', 'ok');
      } catch (e) { this.notificar('Não consegui salvar o PIN: ' + e.message, 'erro'); }
    },

    async toggleCompartilhar() {
      this.redeBusy = true;
      try {
        const ativar = !this.rede.compartilhando;
        const body = { ativar };
        // Se ainda não há PIN e o usuário digitou um, manda junto ao ligar.
        if (ativar && !this.rede.tem_pin && (this.redePin || '').trim().length >= 4) {
          body.pin = this.redePin.trim();
        }
        const r = await fetch('/api/rede/compartilhar', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!r.ok) {
          const e = await r.json().catch(() => ({}));
          if ((e.detail || '').includes('PIN')) this.notificar('Defina um PIN antes de compartilhar.', 'erro');
          else this.notificar(e.detail || 'Não consegui ligar o compartilhamento.', 'erro');
          return;
        }
        const data = await r.json();
        this.rede.compartilhando = data.compartilhando;
        if (data.url) { this.rede.url = data.url; this.rede.ip = data.ip; this.rede.porta = data.porta; this.rede.tem_pin = true; this.redePin = ''; }
        if (data.compartilhando) {
          this.$nextTick(() => this.renderQrRede());
          this.notificar('No ar! Acesse pelo celular.', 'ok');
        } else {
          this.redeQrPronto = false;
          this.notificar('Compartilhamento desligado.', 'ok');
        }
      } catch (e) {
        this.notificar('Erro: ' + e.message, 'erro');
      } finally { this.redeBusy = false; }
    },

    renderQrRede() {
      const el = document.getElementById('rede-qr');
      if (!el || !this.rede.url) return;
      el.innerHTML = '';
      if (typeof QRCode === 'undefined') { this.redeQrPronto = false; return; }
      try {
        new QRCode(el, { text: this.rede.url, width: 168, height: 168 });
        this.redeQrPronto = true;
      } catch (e) { this.redeQrPronto = false; }
    },

    copiarUrlRede() {
      if (!this.rede.url) return;
      navigator.clipboard?.writeText(this.rede.url)
        .then(() => this.notificar('Endereço copiado.', 'ok'))
        .catch(() => this.notificar('Copie manualmente: ' + this.rede.url, 'erro'));
    },

    async liberarFirewallRede() {
      try {
        const r = await fetch('/api/rede/firewall', { method: 'POST' });
        const data = await r.json().catch(() => ({}));
        if (data.ok) this.notificar('Firewall liberado para a rede local.', 'ok');
        else this.notificar('Não consegui liberar o Firewall automaticamente. Pode ser preciso permitir o acesso manualmente.', 'erro');
      } catch (e) { this.notificar('Erro ao liberar Firewall.', 'erro'); }
    },

    async salvarFamilia() {
      // Converte textarea (linha por linha) pra string ";"-separated
      const linhas = (this.config.familia_nomes_textarea || '')
        .split('\n').map(s => s.trim()).filter(Boolean);
      const valor = linhas.join(';');
      await this.salvarConfig('familia_nomes', valor);
      this.config.familia_nomes = valor;
    },

    // === Configurações: Contas ===
    abrirFormConta() {
      this.contaForm = { nome: '', tipo: 'Cartão de Crédito', banco_id: '', titular: '', final: '',
                         dia_fechamento: '', dia_vencimento: '', observacoes: '' };
      this.formContaAberto = true;
    },

    async salvarNovaConta() {
      const f = this.contaForm;
      if (!f.nome) {
        this.notificar('Nome obrigatório', 'erro');
        return;
      }
      const dados = {
        nome: f.nome, tipo: f.tipo,
        banco_id: f.banco_id ? parseInt(f.banco_id) : null,
        titular: f.titular || null,
        final: f.final, observacoes: f.observacoes,
        dia_fechamento: f.dia_fechamento ? parseInt(f.dia_fechamento) : null,
        dia_vencimento: f.dia_vencimento ? parseInt(f.dia_vencimento) : null,
      };
      const r = await fetch('/api/contas', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dados),
      });
      const data = await r.json();
      if (!r.ok) {
        this.notificar(data.detail || 'Erro ao criar conta', 'erro');
        return;
      }
      this.notificar(`Conta "${data.nome}" criada`, 'ok');
      this.formContaAberto = false;
      await this.carregarContas();
      await this.carregarCatalogos();
    },

    async excluirConta(id, nome) {
      if (!confirm(`Excluir a conta "${nome}"?\n\nNão dá pra excluir contas com transações ou faturas.`)) return;
      const r = await fetch(`/api/contas/${id}`, { method: 'DELETE' });
      const data = await r.json();
      if (!r.ok) {
        this.notificar(data.detail || 'Erro ao excluir', 'erro');
        return;
      }
      this.notificar('Conta excluída', 'ok');
      await this.carregarContas();
      await this.carregarCatalogos();
    },

    async renomearConta(id, campo, valor) {
      const c = this.contasDetalhe.find(x => x.id === id);
      if (!c) return;

      // banco_id: null ou int
      let novo;
      if (campo === 'banco_id') {
        novo = valor ? parseInt(valor) : null;
        if (novo === c.banco_id) return;
      } else {
        novo = (valor || '').trim();
        const atual = (c[campo] || '');
        if (novo === atual) return;
        if (campo === 'nome' && !novo) {
          this.notificar('Nome não pode ficar em branco', 'erro');
          await this.carregarContas();
          return;
        }
      }

      const r = await fetch(`/api/contas/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [campo]: novo }),
      });
      if (r.ok) {
        this.notificar('Atualizado', 'ok');
        await this.carregarContas();
        await this.carregarCatalogos();
      } else {
        // Pega mensagem real do backend
        let detalhe = '';
        try {
          const data = await r.json();
          detalhe = data.detail || '';
        } catch (e) { /* resposta não é JSON */ }
        this.notificar(detalhe || `Erro ao atualizar (HTTP ${r.status})`, 'erro');
        await this.carregarContas();
      }
    },

    // === Configurações: Categorias ===
    async carregarCategoriasDetalhe() {
      this.categoriasDetalhe = await fetch('/api/categorias').then(r => r.json());
    },

    abrirFormCategoria() {
      this.categoriaForm = { nome: '', tipo: 'Despesa', icone: '', orcamento_mensal: 0 };
      this.formCategoriaAberto = true;
    },

    async salvarNovaCategoria() {
      const f = this.categoriaForm;
      if (!f.nome) { this.notificar('Nome obrigatório', 'erro'); return; }
      const r = await fetch('/api/categorias', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          nome: f.nome, tipo: f.tipo, icone: f.icone,
          orcamento_mensal: parseFloat(f.orcamento_mensal) || 0,
        }),
      });
      const data = await r.json();
      if (!r.ok) {
        this.notificar(data.detail || 'Erro ao criar', 'erro');
        return;
      }
      this.notificar(`Categoria "${f.nome}" criada`, 'ok');
      this.formCategoriaAberto = false;
      await this.carregarCategoriasDetalhe();
      await this.carregarCatalogos();
    },

    async reaplicarPadroes() {
      const msg =
        'Adicionar apenas o que estiver faltando:\n\n' +
        '  • Categorias/atribuições/regras padrão que ainda não existem serão CRIADAS\n' +
        '  • Itens existentes NÃO são alterados\n' +
        '  • Suas exclusões anteriores serão revertidas (o que você apagou volta)\n\n' +
        'Continuar?';
      if (!confirm(msg)) return;
      try {
        const r = await fetch('/api/seed/reaplicar-padroes', { method: 'POST' });
        const data = await r.json();
        if (!r.ok) {
          this.notificar(data.detail || 'Erro', 'erro');
          return;
        }
        const total = data.categorias_adicionadas + data.atribuicoes_adicionadas + data.regras_adicionadas;
        if (total === 0) {
          this.notificar('Nada a adicionar — já está completo', 'ok');
        } else {
          this.notificar(
            `Adicionados: ${data.categorias_adicionadas} categorias, ${data.atribuicoes_adicionadas} atribuições, ${data.regras_adicionadas} regras`,
            'ok'
          );
        }
        await this.carregarCategoriasDetalhe();
        await this.carregarAtribuicoesDetalhe();
        await this.carregarCatalogos();
        await this.carregarRegras();
      } catch (e) {
        console.error(e);
        this.notificar('Erro de rede', 'erro');
      }
    },

    async resetarClassificacao() {
      const msg =
        'ATENÇÃO — operação destrutiva\n\n' +
        'Isto vai:\n' +
        '  • LIMPAR a classificação de TODAS as transações (ficam "sem categoria")\n' +
        '  • APAGAR a memória de palavras-chave aprendida\n' +
        '  • APAGAR todas as regras (incluindo as que você criou manualmente)\n' +
        '  • Recriar categorias e regras na estrutura padrão atual\n' +
        '  • Re-classificar tudo automaticamente com as regras novas\n\n' +
        'Suas TRANSAÇÕES e ATRIBUIÇÕES não são tocadas.\n\n' +
        'Continuar?';
      if (!confirm(msg)) return;

      try {
        const r = await fetch('/api/categorias/reset-classificacao', { method: 'POST' });
        const data = await r.json();
        if (!r.ok) {
          this.notificar(data.detail || 'Erro no reset', 'erro');
          return;
        }
        let msgFinal = `Reset OK — ${data.transacoes_reclassificadas}/${data.transacoes_total} transações reclassificadas, ${data.regras_novas_criadas} regras novas`;
        if (data.categorias_apagadas > 0) {
          msgFinal += `, ${data.categorias_apagadas} órfãs apagadas`;
        }
        this.notificar(msgFinal, 'ok');
        // Recarrega tudo afetado
        await this.carregarCategoriasDetalhe();
        await this.carregarCatalogos();
        await this.carregarRegras();
        await this.carregarDashboard();
      } catch (e) {
        this.notificar('Erro de rede no reset', 'erro');
        console.error(e);
      }
    },

    async toggleCategoriaEssencial(c) {
      // Inverte o flag essencial e persiste
      const novoValor = !c.essencial;
      try {
        const r = await fetch(`/api/categorias/${c.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ essencial: novoValor }),
        });
        if (!r.ok) {
          this.notificar('Erro ao alternar', 'erro');
          return;
        }
        // Atualiza local pra resposta visual imediata
        c.essencial = novoValor;
        // Recarrega o que depende dessa flag
        await this.carregarCatalogos();   // listas usadas em selects (categorias)
        await this.carregarDashboard();   // recalcula essencial vs discricionário
        // Se está vendo transações, recarrega tb pra estrelas atualizarem
        if (this.view === 'transacoes') {
          await this.carregarTransacoes();
        }
      } catch (e) {
        console.error(e);
        this.notificar('Erro de rede', 'erro');
      }
    },

    async excluirCategoria(id, nome) {
      if (!confirm(`Excluir a categoria "${nome}"?`)) return;
      const r = await fetch(`/api/categorias/${id}`, { method: 'DELETE' });
      const data = await r.json();
      if (!r.ok) {
        this.notificar(data.detail || 'Erro ao excluir', 'erro');
        return;
      }
      this.notificar('Categoria excluída', 'ok');
      await this.carregarCategoriasDetalhe();
      await this.carregarCatalogos();
    },

    abrirEdicaoCategoria(c) {
      // Cópia rasa pra não mexer no objeto da lista até salvar
      this.editCategoriaForm = {
        nome: c.nome,
        tipo: c.tipo,
        icone: c.icone || '',
        orcamento_mensal: c.orcamento_mensal || 0,
        essencial: !!c.essencial,
      };
      this.editandoCategoria = c;
    },

    async salvarEdicaoCategoria() {
      if (!this.editandoCategoria) return;
      const f = this.editCategoriaForm;
      if (!f.nome.trim()) { this.notificar('Nome obrigatório', 'erro'); return; }

      try {
        const r = await fetch(`/api/categorias/${this.editandoCategoria.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            nome: f.nome.trim(),
            tipo: f.tipo,
            icone: f.icone || '',
            orcamento_mensal: parseFloat(f.orcamento_mensal) || 0,
            essencial: !!f.essencial,
          }),
        });
        const data = await r.json();
        if (!r.ok) {
          this.notificar(data.detail || 'Erro ao salvar', 'erro');
          return;
        }
        this.notificar('Categoria atualizada', 'ok');
        this.editandoCategoria = null;
        await this.carregarCategoriasDetalhe();
        await this.carregarCatalogos();
        // Se está vendo dashboard, atualiza (essencial pode ter mudado)
        if (this.view === 'dashboard') await this.carregarDashboard();
        if (this.view === 'transacoes') await this.carregarTransacoes();
      } catch (e) {
        console.error(e);
        this.notificar('Erro de rede', 'erro');
      }
    },

    // === Configurações: Atribuições ===
    async carregarAtribuicoesDetalhe() {
      this.atribuicoesDetalhe = await fetch('/api/atribuicoes').then(r => r.json());
    },

    abrirFormAtribuicao() {
      this.atribuicaoForm = { nome: '', tipo: 'Pessoa', cor: '#888888', descricao: '' };
      this.formAtribuicaoAberto = true;
    },

    async salvarNovaAtribuicao() {
      const f = this.atribuicaoForm;
      if (!f.nome) { this.notificar('Nome obrigatório', 'erro'); return; }
      const r = await fetch('/api/atribuicoes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(f),
      });
      const data = await r.json();
      if (!r.ok) {
        this.notificar(data.detail || 'Erro ao criar', 'erro');
        return;
      }
      this.notificar(`Atribuição "${f.nome}" criada`, 'ok');
      this.formAtribuicaoAberto = false;
      await this.carregarAtribuicoesDetalhe();
      await this.carregarCatalogos();
    },

    async excluirAtribuicao(id, nome) {
      if (!confirm(`Excluir a atribuição "${nome}"?`)) return;
      const r = await fetch(`/api/atribuicoes/${id}`, { method: 'DELETE' });
      const data = await r.json();
      if (!r.ok) {
        this.notificar(data.detail || 'Erro ao excluir', 'erro');
        return;
      }
      this.notificar('Atribuição excluída', 'ok');
      await this.carregarAtribuicoesDetalhe();
      await this.carregarCatalogos();
    },

    abrirEdicaoAtribuicao(a) {
      this.editAtribuicaoForm = {
        nome: a.nome,
        tipo: a.tipo,
        cor: a.cor || '#888888',
        descricao: a.descricao || '',
      };
      this.editandoAtribuicao = a;
    },

    async salvarEdicaoAtribuicao() {
      if (!this.editandoAtribuicao) return;
      const f = this.editAtribuicaoForm;
      if (!f.nome.trim()) { this.notificar('Nome obrigatório', 'erro'); return; }

      try {
        const r = await fetch(`/api/atribuicoes/${this.editandoAtribuicao.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            nome: f.nome.trim(),
            tipo: f.tipo,
            cor: f.cor || '#888888',
            descricao: f.descricao || '',
          }),
        });
        const data = await r.json();
        if (!r.ok) {
          this.notificar(data.detail || 'Erro ao salvar', 'erro');
          return;
        }
        this.notificar('Atribuição atualizada', 'ok');
        this.editandoAtribuicao = null;
        await this.carregarAtribuicoesDetalhe();
        await this.carregarCatalogos();
        if (this.view === 'transacoes') await this.carregarTransacoes();
      } catch (e) {
        console.error(e);
        this.notificar('Erro de rede', 'erro');
      }
    },

    // Helpers
    brl(v) {
      if (v == null || isNaN(v)) return 'R$ 0,00';
      return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v);
    },
    /**
     * Calcula variação percentual de atual vs anterior.
     * Retorna número (pode ser negativo) ou null se anterior é zero.
     */
    pctVar(atual, anterior) {
      if (!anterior || anterior === 0) return null;
      return ((atual - anterior) / Math.abs(anterior)) * 100;
    },
    /**
     * Renderiza seta colorida baseado no contexto:
     *   maior_melhor: subir é positivo (Receitas, Saldo)
     *   menor_melhor: subir é negativo (Despesas)
     */
    setaVar(atual, anterior, contexto) {
      if (anterior == null) return '<span class="text-zinc-600">—</span>';
      const diff = atual - anterior;
      if (Math.abs(diff) < 0.01) return '<span class="text-zinc-500">●</span>';
      const subiu = diff > 0;
      const ehBom = contexto === 'maior_melhor' ? subiu : !subiu;
      const cor = ehBom ? 'text-emerald-400' : 'text-red-400';
      const seta = subiu ? '↑' : '↓';
      return `<span class="${cor} font-bold">${seta}</span>`;
    },
    /**
     * Texto da variação: "+12,5%" ou "−8,2%" ou "novo" (quando não há anterior).
     */
    textoVar(atual, anterior) {
      const pct = this.pctVar(atual, anterior);
      if (pct === null) {
        if (Math.abs(atual) < 0.01) return 'sem movimento';
        return 'sem comparativo';
      }
      const sinal = pct >= 0 ? '+' : '−';
      return `${sinal}${Math.abs(pct).toFixed(1).replace('.', ',')}%`;
    },
    formatarData(s) {
      if (!s) return '';
      const [y, m, d] = s.split('-');
      return `${d}/${m}/${y}`;
    },
    formatarDataHora(s) {
      if (!s) return '';
      const dt = new Date(s);
      return dt.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    },
    // === Extrato bancário ===
    async carregarContasExtrato() {
      try {
        this.contasExtrato = await fetch(`/api/extrato/contas?_=${Date.now()}`).then(r => r.json());
        // Auto-seleciona a primeira conta se há só uma e ainda não tem nada selecionado
        if (this.contasExtrato.length > 0 && !this.extrato.conta_id) {
          this.extrato.conta_id = this.contasExtrato[0].id;
          await this.carregarExtrato();
        }
      } catch (e) {
        console.error('Erro carregando contas do extrato:', e);
      }
    },

    async carregarExtrato() {
      if (!this.extrato.conta_id) {
        this.extrato.items = [];
        return;
      }
      const t = Date.now();
      try {
        const params = new URLSearchParams({ conta_id: this.extrato.conta_id, _: t });
        if (this.extrato.mes) params.append('mes', this.extrato.mes);
        const data = await fetch(`/api/extrato?${params}`).then(r => r.json());
        // Mantém conta_id e mes selecionados, atualiza o resto
        this.extrato = {
          ...this.extrato,
          ...data,
          conta_id: this.extrato.conta_id,
          mes: this.extrato.mes,
        };
      } catch (e) {
        console.error('Erro carregando extrato:', e);
        this.notificar('Erro ao carregar extrato', 'erro');
      }
    },

    // Marca/desmarca uma transação do extrato como movimentação interna
    // (pagamento de fatura / transferência). Some da lista de Transações e
    // dos totais; valor vazio devolve a transação ao fluxo normal.
    async marcarMovimentacao(t, tipo) {
      const valor = (tipo === 'fatura' || tipo === 'transferencia') ? tipo : null;
      try {
        const r = await fetch(`/api/transacoes/${t.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ movimentacao: valor }),
        });
        if (!r.ok) throw new Error('patch falhou');
        t.movimentacao = valor;
        if (valor) { t.categoria = null; t.categoria_icone = null; }
        this.notificar(
          valor === 'fatura' ? 'Marcada como pagamento de fatura'
          : valor === 'transferencia' ? 'Marcada como transferência'
          : 'Voltou a ser transação normal', 'ok');
      } catch (e) {
        console.error('Erro ao marcar movimentação:', e);
        this.notificar('Erro ao marcar movimentação', 'erro');
        await this.carregarExtrato();
      }
    },

    async salvarSaldoManual() {
      const valor = parseFloat(this.modalSaldo.valor);
      if (isNaN(valor)) {
        this.notificar('Informe um valor válido', 'erro');
        return;
      }
      if (!this.modalSaldo.data) {
        this.notificar('Informe a data do saldo', 'erro');
        return;
      }
      const r = await fetch(`/api/contas/${this.extrato.conta_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          saldo_inicial_manual: valor,
          saldo_inicial_data: this.modalSaldo.data,
        }),
      });
      if (r.ok) {
        this.notificar('Saldo cadastrado', 'ok');
        this.modalSaldo.show = false;
        await this.carregarExtrato();
      } else {
        this.notificar('Erro ao salvar', 'erro');
      }
    },

    async limparSaldoManual() {
      if (!confirm('Remover saldo manual cadastrado?')) return;
      const r = await fetch(`/api/contas/${this.extrato.conta_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          saldo_inicial_manual: null,
          saldo_inicial_data: null,
        }),
      });
      if (r.ok) {
        this.notificar('Saldo removido', 'ok');
        this.modalSaldo.show = false;
        await this.carregarExtrato();
      }
    },

    // === Investimentos ===
    ativosOrdenados() {
      const arr = [...this.ativos];
      const cmps = {
        // Maior posição (em R$, comparável entre moedas)
        valor:  (a, b) => (b.saldo_atual_brl || 0) - (a.saldo_atual_brl || 0),
        // Maior rentabilidade (%) — usa o % em R$, igual ao que a lista exibe
        rentab: (a, b) => (b.rentab_brl_pct || 0) - (a.rentab_brl_pct || 0),
        // Aquisição mais recente primeiro
        data:   (a, b) => (b.data_aquisicao || '').localeCompare(a.data_aquisicao || ''),
        // Por tipo (alfabético), depois maior posição
        tipo:   (a, b) => (a.tipo || '').localeCompare(b.tipo || '') || (b.saldo_atual_brl || 0) - (a.saldo_atual_brl || 0),
        nome:   (a, b) => (a.nome || '').localeCompare(b.nome || '', 'pt-BR'),
      };
      return arr.sort(cmps[this.ordemInvest] || cmps.valor);
    },

    // Agrupa os ativos (já ordenados) por tipo; grupos ordenados por maior posição.
    ativosAgrupados() {
      const grupos = {};
      for (const a of this.ativosOrdenados()) {
        const t = a.tipo || 'Outros';
        if (!grupos[t]) grupos[t] = { tipo: t, ativos: [], total_brl: 0, rentab_brl: 0, investido_brl: 0 };
        const g = grupos[t];
        g.ativos.push(a);
        g.total_brl += a.saldo_atual_brl || 0;
        g.rentab_brl += a.rentab_brl || 0;
        g.investido_brl += Math.max(a.valor_investido_brl || 0, 0);
      }
      return Object.values(grupos).sort((x, y) => y.total_brl - x.total_brl);
    },

    toggleGrupo(tipo) {
      this.gruposAbertos = { ...this.gruposAbertos, [tipo]: !this.gruposAbertos[tipo] };
    },

    async carregarInvestimentos() {
      const t = Date.now();
      try {
        const [ativos, resumo, tipos, cdi, cambio] = await Promise.all([
          fetch(`/api/investimentos/ativos?_=${t}`).then(r => r.json()),
          fetch(`/api/investimentos/resumo?_=${t}`).then(r => r.json()),
          fetch(`/api/investimentos/tipos?_=${t}`).then(r => r.json()),
          fetch(`/api/investimentos/cdi/status?_=${t}`).then(r => r.json()).catch(() => null),
          fetch(`/api/cambio/status?_=${t}`).then(r => r.json()).catch(() => null),
        ]);
        this.ativos = ativos;
        this.resumoInvest = resumo;
        this.tiposAtivo = tipos.tipos;
        this.moedasAtivo = tipos.moedas;
        this.cdiStatus = cdi;
        this.cambioStatus = cambio;
        this.renderEvolucaoPatrimonio();   // gráfico de evolução (assíncrono)
        this.carregarAlocacao();           // alocação + pizza (assíncrono)
      } catch (e) {
        console.error('Erro carregando investimentos:', e);
        this.notificar('Erro ao carregar investimentos', 'erro');
      }
    },

    async renderEvolucaoPatrimonio() {
      try {
        const d = await fetch(`/api/investimentos/evolucao?_=${Date.now()}`).then(r => r.json());
        const serie = (d && d.serie) || [];
        this.evolucaoTemDados = serie.length > 0;
        if (!serie.length || typeof Chart === 'undefined') return;
        await this.$nextTick();
        const el = document.getElementById('chart-patrimonio');
        if (!el) return;
        const ex = Chart.getChart(el); if (ex) ex.destroy();
        if (this._chartPatrimonio) { try { this._chartPatrimonio.destroy(); } catch (e) {} }
        const fmtMes = (m) => { const [y, mm] = m.split('-'); return mm + '/' + y.slice(2); };
        this._chartPatrimonio = new Chart(el, {
          type: 'line',
          data: {
            labels: serie.map(p => fmtMes(p.mes)),
            datasets: [
              { label: 'Patrimônio', data: serie.map(p => p.patrimonio),
                borderColor: '#34d399', backgroundColor: 'rgba(52,211,153,.12)',
                fill: true, tension: .25, spanGaps: true, pointRadius: 2 },
              { label: 'Investimentos', data: serie.map(p => p.investido),
                borderColor: '#60a5fa', borderDash: [4, 4], fill: false, tension: .25, pointRadius: 0 },
            ],
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
              legend: { labels: { color: '#a1a1aa', boxWidth: 12 } },
              tooltip: { callbacks: { label: (c) => c.dataset.label + ': ' + (c.parsed.y == null ? '—' : this.brl(c.parsed.y)) } },
            },
            scales: {
              x: { ticks: { color: '#71717a', maxRotation: 0, autoSkip: true }, grid: { color: 'rgba(255,255,255,.04)' } },
              y: { ticks: { color: '#71717a', callback: (v) => this.brl(v) }, grid: { color: 'rgba(255,255,255,.04)' } },
            },
          },
        });
      } catch (e) { /* sem internet (Chart.js CDN) ou sem dados: silencioso */ }
    },

    async carregarAlocacao() {
      try {
        const d = await fetch(`/api/investimentos/alocacao?_=${Date.now()}`).then(r => r.json());
        this.alocacao = d;
        const edit = {};
        (d.linhas || []).forEach(l => { if (l.pct_alvo != null) edit[l.tipo] = String(l.pct_alvo); });
        this.alocacaoAlvoEdit = edit;
        this.renderAlocacaoChart();
      } catch (e) { /* silencioso */ }
    },

    async renderAlocacaoChart() {
      if (typeof Chart === 'undefined') return;
      await this.$nextTick();
      const el = document.getElementById('chart-alocacao');
      if (!el) return;
      const ex = Chart.getChart(el); if (ex) ex.destroy();
      if (this._chartAlocacao) { try { this._chartAlocacao.destroy(); } catch (e) {} }
      const linhas = (this.alocacao.linhas || []).filter(l => (l.atual_brl || 0) > 0);
      if (!linhas.length) return;
      const cores = ['#34d399', '#60a5fa', '#fbbf24', '#f87171', '#a78bfa', '#22d3ee', '#f472b6', '#a3e635', '#fb923c'];
      this._chartAlocacao = new Chart(el, {
        type: 'doughnut',
        data: {
          labels: linhas.map(l => l.tipo),
          datasets: [{ data: linhas.map(l => l.atual_brl), backgroundColor: cores, borderColor: '#18181b', borderWidth: 2 }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { position: 'right', labels: { color: '#a1a1aa', boxWidth: 12, font: { size: 11 } } },
            tooltip: { callbacks: { label: (c) => c.label + ': ' + this.brl(c.parsed) + ' (' + (this.alocacao.total_brl ? (c.parsed / this.alocacao.total_brl * 100).toFixed(1) : 0) + '%)' } },
          },
        },
      });
    },

    async salvarAlocacaoAlvo() {
      const alvo = {};
      for (const [t, v] of Object.entries(this.alocacaoAlvoEdit)) {
        const n = parseFloat(String(v).replace(',', '.'));
        if (n > 0) alvo[t] = n;
      }
      try {
        this.alocacao = await fetch('/api/investimentos/alocacao/alvo', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ alvo }),
        }).then(r => r.json());
        this.notificar('Alvos de alocação salvos', 'ok');
        this.renderAlocacaoChart();
      } catch (e) { this.notificar('Erro ao salvar alvos', 'erro'); }
    },

    async sincronizarCDI() {
      this.sincronizandoCDI = true;
      try {
        const r = await fetch('/api/investimentos/cdi/sincronizar', { method: 'POST' });
        const data = await r.json();
        if (data.ok) {
          this.cdiStatus = data.status;
          this.notificar(
            data.dias_baixados > 0
              ? `CDI atualizado (${data.dias_baixados} dia(s) novo(s))`
              : 'CDI já estava em dia',
            'ok');
          await this.carregarInvestimentos();
        } else {
          this.notificar('Não consegui falar com o Banco Central agora. Tente mais tarde.', 'erro');
        }
      } catch (e) {
        this.notificar('Erro ao sincronizar CDI', 'erro');
      } finally {
        this.sincronizandoCDI = false;
      }
    },

    // Atualiza CDI + dólar + euro + cotações de uma vez (botão da aba Investimentos).
    async atualizarCotacoes() {
      this.atualizandoTudo = true;
      try {
        const [cdi, cambio, cot] = await Promise.all([
          fetch('/api/investimentos/cdi/sincronizar', { method: 'POST' }).then(r => r.json()).catch(() => null),
          fetch('/api/cambio/sincronizar', { method: 'POST' }).then(r => r.json()).catch(() => null),
          fetch('/api/investimentos/cotacoes/sincronizar', { method: 'POST' }).then(r => r.json()).catch(() => null),
        ]);
        if (cdi && cdi.status) this.cdiStatus = cdi.status;
        if (cambio && cambio.status) this.cambioStatus = cambio.status;
        const cotN = (cot && cot.status) ? cot.status.n_tickers : 0;
        if ((cdi && cdi.ok) || (cambio && cambio.ok) || (cot && cot.ok)) {
          this.notificar('CDI, câmbio e cotações atualizados' + (cotN ? ` (${cotN} ativos)` : ''), 'ok');
        } else {
          this.notificar('Não consegui atualizar agora. Tente mais tarde.', 'erro');
        }
        await this.carregarInvestimentos();
      } catch (e) {
        this.notificar('Erro ao atualizar', 'erro');
      } finally {
        this.atualizandoTudo = false;
      }
    },

    abrirCambioManual() {
      const m = (this.cambioStatus && this.cambioStatus.moedas) || {};
      this.cambioManualEdit = {
        USD: (m.USD && m.USD.manual != null) ? String(m.USD.manual) : '',
        EUR: (m.EUR && m.EUR.manual != null) ? String(m.EUR.manual) : '',
      };
      this.cambioModalAberto = true;
    },

    async salvarCambioManualModal() {
      for (const moeda of ['USD', 'EUR']) {
        const raw = String(this.cambioManualEdit[moeda] || '').replace(',', '.').trim();
        let valor = '';                         // vazio = limpa o manual (volta ao BCB)
        if (raw !== '') {
          valor = parseFloat(raw);
          if (!(valor > 0)) { this.notificar(`Cotação inválida para ${moeda}`, 'erro'); return; }
        }
        try {
          this.cambioStatus = await fetch('/api/cambio/manual', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ moeda, valor }),
          }).then(r => r.json());
        } catch (e) { this.notificar('Erro ao salvar a cotação manual', 'erro'); return; }
      }
      this.cambioModalAberto = false;
      this.notificar('Cotações salvas', 'ok');
      await this.carregarInvestimentos();
    },

    async carregarOperacoes(ativoId) {
      try {
        const ops = await fetch(`/api/investimentos/operacoes?ativo_id=${ativoId}&_=${Date.now()}`).then(r => r.json());
        this.operacoesPorAtivo = { ...this.operacoesPorAtivo, [ativoId]: ops };
      } catch (e) {
        console.error('Erro carregando operações:', e);
      }
    },

    // === Metas de patrimônio ===
    formatarBRL(v) {
      const n = Number(v) || 0;
      return 'R$ ' + n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },

    get metasComNivel() {
      // Achata a árvore de metas mantendo o nível pra indentação visual.
      const lista = [];
      const visitar = (nodes, nivel) => {
        for (const n of nodes) {
          lista.push({ ...n, nivel });
          if (n.sub_metas && n.sub_metas.length) visitar(n.sub_metas, nivel + 1);
        }
      };
      visitar(this.metas, 0);
      return lista;
    },

    async carregarMetas() {
      try {
        const t = Date.now();
        const [d, ativos] = await Promise.all([
          fetch(`/api/metas?_=${t}`).then(r => r.json()),
          fetch(`/api/investimentos/ativos?_=${t}`).then(r => r.json()).catch(() => []),
        ]);
        this.metas = d.metas || [];
        this.metasFlat = d.flat || [];
        this.tiposAtivoDisp = d.tipos_disponiveis || [];
        // Ativos disponíveis para metas de escopo "ativos" (id + nome).
        this.ativosDisp = Array.isArray(ativos) ? ativos : [];
      } catch (e) {
        console.error('Erro carregando metas:', e);
        this.notificar('Erro ao carregar metas', 'erro');
      }
    },

    nomeAtivo(id) {
      const a = (this.ativosDisp || []).find(x => x.id === id);
      return a ? a.nome : ('Ativo #' + id);
    },

    abrirMetaNova() {
      this.metaModal = {
        aberto: true,
        editando_id: null,
        nome: '',
        descricao: '',
        escopo: 'patrimonio_total',
        objetivo: 'patrimonio',
        escopo_tipos: [],
        escopo_ativos: [],
        escopo_excluir_ativos: [],
        valor_atual_manual: 0,
        valor_alvo: 0,
        data_alvo: '',
        taxa_retorno_anual: '',
        meta_pai_id: '',
      };
    },

    abrirMetaEdit(m) {
      this.metaModal = {
        aberto: true,
        editando_id: m.id,
        nome: m.nome || '',
        descricao: m.descricao || '',
        escopo: m.escopo,
        objetivo: m.objetivo || 'patrimonio',
        escopo_tipos: [...(m.escopo_tipos || [])],
        escopo_ativos: [...(m.escopo_ativos || [])],
        escopo_excluir_ativos: [...(m.escopo_excluir_ativos || [])],
        valor_atual_manual: m.valor_atual_manual || 0,
        valor_alvo: m.valor_alvo || 0,
        data_alvo: m.data_alvo || '',
        taxa_retorno_anual: m.taxa_retorno_anual_override ?? '',
        meta_pai_id: m.meta_pai_id || '',
      };
    },

    toggleTipoMeta(tipo) {
      const i = this.metaModal.escopo_tipos.indexOf(tipo);
      if (i >= 0) this.metaModal.escopo_tipos.splice(i, 1);
      else this.metaModal.escopo_tipos.push(tipo);
    },

    toggleAtivoMeta(id) {
      const i = this.metaModal.escopo_ativos.indexOf(id);
      if (i >= 0) this.metaModal.escopo_ativos.splice(i, 1);
      else this.metaModal.escopo_ativos.push(id);
    },

    toggleExcluirMeta(id) {
      const i = this.metaModal.escopo_excluir_ativos.indexOf(id);
      if (i >= 0) this.metaModal.escopo_excluir_ativos.splice(i, 1);
      else this.metaModal.escopo_excluir_ativos.push(id);
    },

    async salvarMeta() {
      const m = this.metaModal;
      if (!m.nome.trim()) { this.notificar('Dê um nome para a meta', 'erro'); return; }
      if (!m.valor_alvo || m.valor_alvo <= 0) { this.notificar('Valor alvo precisa ser maior que zero', 'erro'); return; }
      if (m.escopo === 'tipos_ativo' && m.escopo_tipos.length === 0) {
        this.notificar('Selecione pelo menos uma classe de ativo', 'erro'); return;
      }
      if (m.escopo === 'ativos' && (!m.escopo_ativos || m.escopo_ativos.length === 0)) {
        this.notificar('Selecione pelo menos um ativo', 'erro'); return;
      }

      const payload = {
        nome: m.nome.trim(),
        descricao: m.descricao || null,
        escopo: m.escopo,
        objetivo: m.objetivo || 'patrimonio',
        escopo_tipos: m.escopo === 'tipos_ativo' ? m.escopo_tipos : [],
        escopo_ativos: m.escopo === 'ativos' ? m.escopo_ativos : [],
        escopo_excluir_ativos: (m.escopo === 'patrimonio_total' || m.escopo === 'tipos_ativo') ? m.escopo_excluir_ativos : [],
        valor_atual_manual: m.escopo === 'manual' ? Number(m.valor_atual_manual) : 0,
        valor_alvo: Number(m.valor_alvo),
        data_alvo: m.data_alvo || null,
        taxa_retorno_anual: (m.taxa_retorno_anual === '' || m.taxa_retorno_anual == null)
          ? null : Number(m.taxa_retorno_anual),
        meta_pai_id: m.meta_pai_id ? Number(m.meta_pai_id) : null,
      };

      const url = m.editando_id ? `/api/metas/${m.editando_id}` : '/api/metas';
      const method = m.editando_id ? 'PATCH' : 'POST';
      try {
        const r = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          this.notificar(err.detail || 'Erro ao salvar meta', 'erro');
          return;
        }
        this.metaModal.aberto = false;
        await this.carregarMetas();
        this.notificar(m.editando_id ? 'Meta atualizada' : 'Meta criada');
      } catch (e) {
        console.error(e);
        this.notificar('Erro ao salvar meta', 'erro');
      }
    },

    async deletarMeta(id) {
      if (!confirm('Excluir esta meta? Sub-metas (se houver) sobem um nível.')) return;
      try {
        const r = await fetch(`/api/metas/${id}`, { method: 'DELETE' });
        if (!r.ok) { this.notificar('Erro ao excluir', 'erro'); return; }
        this.metaModal.aberto = false;
        await this.carregarMetas();
        this.notificar('Meta excluída');
      } catch (e) {
        console.error(e);
        this.notificar('Erro ao excluir', 'erro');
      }
    },

    async atualizarManual(id, valor) {
      const v = Number(valor);
      if (isNaN(v) || v < 0) { this.notificar('Valor inválido', 'erro'); return; }
      try {
        const r = await fetch(`/api/metas/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ valor_atual_manual: v }),
        });
        if (!r.ok) { this.notificar('Erro ao atualizar', 'erro'); return; }
        await this.carregarMetas();
      } catch (e) {
        console.error(e);
        this.notificar('Erro ao atualizar', 'erro');
      }
    },

    abrirFormAtivo() {
      this.editandoAtivoId = null;
      this.ativoForm = {
        nome: '', ticker: '',
        tipo: this.tiposAtivo[0] || 'Tesouro Direto',
        moeda: 'BRL', instituicao: '', detalhes_taxa: '', data_vencimento: '', observacoes: '',
        rendimento_incorpora_saldo: null, cdi_percentual: '', objetivo: 'patrimonio',
      };
      this.formAtivoAberto = true;
    },

    abrirFormEditarAtivo(a) {
      this.editandoAtivoId = a.id;
      // O backend retorna `rendimento_incorpora_saldo` calculado (com o default
      // por tipo aplicado). Pra detectar override explícito, comparamos com
      // o default que o tipo geraria — se for igual ao default, mantemos null.
      const defaultRF = this.TIPOS_RF.includes(a.tipo);
      const explicito = a.rendimento_incorpora_saldo !== defaultRF
                        ? a.rendimento_incorpora_saldo
                        : null;
      this.ativoForm = {
        nome: a.nome || '',
        ticker: a.ticker || '',
        tipo: a.tipo || (this.tiposAtivo[0] || 'Tesouro Direto'),
        moeda: a.moeda || 'BRL',
        instituicao: a.instituicao || '',
        detalhes_taxa: a.detalhes_taxa || '',
        data_vencimento: a.data_vencimento || '',
        observacoes: a.observacoes || '',
        rendimento_incorpora_saldo: explicito,
        cdi_percentual: (a.cdi_percentual ?? '') === null ? '' : (a.cdi_percentual ?? ''),
        objetivo: a.objetivo || 'patrimonio',
      };
      this.formAtivoAberto = true;
      this.$nextTick(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
    },

    // Pra UI: o que o flag está efetivamente fazendo agora (com fallback no tipo).
    rendimentoIncorporaEfetivo() {
      const v = this.ativoForm.rendimento_incorpora_saldo;
      if (v === true || v === false) return v;
      return this.TIPOS_RF.includes(this.ativoForm.tipo);
    },

    async salvarNovoAtivo() {
      const f = this.ativoForm;
      if (!f.nome) {
        this.notificar('Nome obrigatório', 'erro');
        return;
      }
      const editando = this.editandoAtivoId;
      const url = editando ? `/api/investimentos/ativos/${editando}` : '/api/investimentos/ativos';
      const method = editando ? 'PATCH' : 'POST';
      const r = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(f),
      });
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        this.notificar(data.detail || 'Erro ao salvar', 'erro');
        return;
      }
      this.notificar(editando ? `Ativo "${f.nome}" atualizado` : `Ativo "${f.nome}" criado`, 'ok');
      this.formAtivoAberto = false;
      this.editandoAtivoId = null;
      await this.carregarInvestimentos();
    },

    async excluirAtivo(id, nome) {
      if (!confirm(`Excluir o ativo "${nome}"?\n\nSe houver operações registradas, ele será só desativado (histórico preservado).`)) return;
      const r = await fetch(`/api/investimentos/ativos/${id}`, { method: 'DELETE' });
      const data = await r.json();
      if (!r.ok) {
        this.notificar(data.detail || 'Erro', 'erro');
        return;
      }
      this.notificar(data.soft_delete ? `Ativo desativado (${data.n_operacoes} operações preservadas)` : 'Ativo excluído', 'ok');
      await this.carregarInvestimentos();
    },

    async atualizarSaldoAtivo(id, valor) {
      const novo = parseFloat(valor) || 0;
      const a = this.ativos.find(x => x.id === id);
      if (!a) return;
      if (novo === (a.saldo_atual || 0)) return;
      const r = await fetch(`/api/investimentos/ativos/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ saldo_atual: novo }),
      });
      if (r.ok) {
        this.notificar('Saldo atualizado', 'ok');
        await this.carregarInvestimentos();
      } else {
        this.notificar('Erro ao atualizar', 'erro');
      }
    },

    abrirFormOperacao(ativo, tipo) {
      const hoje = new Date().toISOString().slice(0, 10);
      this.opForm = {
        tipo: tipo,
        data: hoje,
        quantidade: '',
        preco_unitario: '',
        valor_total: '',
        moeda_operacao: ativo.moeda,
        cotacao_cambio: '',
        taxas: '',
        resgate_total: false,
        observacoes: '',
      };
      this.formOpAtivoId = ativo.id;
    },

    async salvarNovaOperacao() {
      const f = this.opForm;
      if (!f.data) {
        this.notificar('Data obrigatória', 'erro');
        return;
      }
      const tem_valor = f.valor_total && parseFloat(f.valor_total) > 0;
      const tem_qtd_preco = f.quantidade && f.preco_unitario;
      if (!tem_valor && !tem_qtd_preco) {
        this.notificar('Informe Valor total OU Quantidade + Preço unitário', 'erro');
        return;
      }
      if (f.moeda_operacao !== 'BRL' && !f.cotacao_cambio) {
        this.notificar('Câmbio é obrigatório quando moeda ≠ BRL', 'erro');
        return;
      }

      const dados = {
        ativo_id: this.formOpAtivoId,
        tipo: f.tipo,
        data: f.data,
        quantidade: f.quantidade ? parseFloat(f.quantidade) : null,
        preco_unitario: f.preco_unitario ? parseFloat(f.preco_unitario) : null,
        valor_total: f.valor_total ? parseFloat(f.valor_total) : null,
        moeda_operacao: f.moeda_operacao,
        cotacao_cambio: f.cotacao_cambio ? parseFloat(f.cotacao_cambio) : null,
        taxas: f.taxas ? parseFloat(f.taxas) : 0,
        resgate_total: !!f.resgate_total,
        observacoes: f.observacoes,
      };
      const r = await fetch('/api/investimentos/operacoes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dados),
      });
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        this.notificar(data.detail || 'Erro ao criar operação', 'erro');
        return;
      }
      this.notificar(`${f.tipo} registrada`, 'ok');
      const ativoId = this.formOpAtivoId;
      this.formOpAtivoId = null;
      await this.carregarInvestimentos();
      await this.carregarOperacoes(ativoId);
    },

    async excluirOperacao(opId, ativoId) {
      if (!confirm('Excluir esta operação?')) return;
      const r = await fetch(`/api/investimentos/operacoes/${opId}`, { method: 'DELETE' });
      if (r.ok) {
        this.notificar('Operação excluída', 'ok');
        await this.carregarInvestimentos();
        await this.carregarOperacoes(ativoId);
      } else {
        this.notificar('Erro ao excluir', 'erro');
      }
    },

    notificar(msg, tipo='ok') {
      this.toast = { show: true, msg, tipo };
      setTimeout(() => this.toast.show = false, tipo === 'erro' ? 12000 : 4000);
    },
  };
}
