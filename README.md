# Financeiro Pessoal — v1.0 (Fase 1)

App local de gestão financeira. Roda no seu PC, dados ficam no seu HD.

## 🚀 Começar

1. Leia **GUIA_INSTALACAO.md** (instala Python + Poppler — uma vez só)
2. Duplo-clique em **iniciar.bat** (Windows) ou **iniciar.command** (Mac)
3. Navegador abre em http://localhost:8765

## ✅ O que tem nesta v1

- ✓ Importação de faturas Nubank, Bradesco e Santander (PDF)
- ✓ Detecção automática de PDFs já importados (não duplica)
- ✓ Auto-categorização: regras (~150 prontas) + memória de aprendizado
- ✓ Edição inline de categoria e atribuição
- ✓ Quando você corrige uma transação, o app **aprende** e aplica em outras
- ✓ Dashboard: receitas/despesas/saldo, breakdown por categoria, atribuição, conta, forma de pgto
- ✓ Filtros (mês, conta, categoria, atribuição, busca, "sem categoria")
- ✓ Conciliação básica: detecta pagamentos de fatura e duplicatas
- ✓ Gerenciamento de regras (criar/excluir)
- ✓ Gerenciamento de faturas importadas (excluir)

## ⏳ O que NÃO tem ainda (vem nas próximas fases)

**Fase 2** — me chame de volta com exemplos pra implementar:
- Importação de extratos bancários (cada banco tem layout diferente)
- Conciliação avançada (Pix x cartão, transferências entre contas)
- Categorização ML (modelo treinado nas suas correções)
- Gráficos no dashboard
- Backup automático
- Atribuição visual com drag-and-drop

**Fase 3** — refinamentos:
- Modo "app window" (sem barra de URL do navegador)
- Atalhos de teclado
- Relatórios PDF
- Export Excel
- Mobile responsivo (acessar pelo celular na rede de casa)

## 💾 Backup

**Seus dados estão num arquivo só**: `data/financeiro.db`. Faça backup periódico copiando esse arquivo. Recomendação: ponha a pasta inteira no Dropbox/Google Drive.

## 🆘 Suporte

Volte a me consultar quando precisar — explico mais em GUIA_INSTALACAO.md (seção "Quando voltar a falar comigo").
