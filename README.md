# Nexum

App local de gestão financeira para Windows. Roda 100% no seu PC — seus dados
ficam no seu computador (`%APPDATA%\Nexum\financeiro.db`), nada vai para a
internet. Interface em janela nativa (Edge WebView2), import de faturas em PDF,
dashboard, metas, investimentos e auto-update via GitHub Releases.

## Para usar (usuário final)

Baixe o **`NexumSetup.exe`** da última [release](../../releases), dê duplo-clique
e siga o assistente (sem admin). O passo a passo completo — onde ficam os dados,
backup, atualizações, importar faturas — está em **[COMO_USAR.md](COMO_USAR.md)**.

## Funcionalidades

- Importação de faturas **Nubank, Bradesco, Santander e Mercado Pago** (PDF) e
  extratos **OFX** — leitura embutida (pypdfium2), sem precisar de Poppler.
- Detecção de PDFs já importados (não duplica) e de duplicatas entre fontes.
- Auto-categorização: regras + memória que aprende com suas correções.
- Dashboard: receitas/despesas, **saldo em caixa**, breakdown por categoria,
  atribuição, conta e forma de pagamento; regime por **emissão** ou **pagamento**.
- Metas e investimentos (renda fixa rende via série CDI do BCB; IR/IOF no líquido).
- Conciliação de pagamento de fatura ↔ cartão; divisão de transações.
- Exportação para Excel (.xlsx).
- Acesso pelo celular na rede local (com PIN).
- Auto-update: avisa quando há versão nova e atualiza com um clique.

## Desenvolvimento

Requer Python 3.10+ (o build oficial usa o 3.14 do python.org).

```bash
pip install -r requirements.txt      # runtime
pip install -r requirements-dev.txt  # testes
python run_nexum.py                  # roda local (janela nativa / navegador)
python -m pytest -q                  # testes
```

Os dados em dev ficam em `data/` na raiz do projeto.

### Versão DEV isolada

Para testar sem misturar com o app real, rode em **modo dev** (banco em
`%APPDATA%\Nexum-Dev`, porta 8766, badge "DEV"):

```bash
set NEXUM_DEV=1 && python run_nexum.py        # ou crie um arquivo dev.txt ao lado do exe
```

O build dedicado `Nexum-Dev.spec` gera um `dist\Nexum-Dev.exe` já em modo dev.

## Build & publicação

A versão é única em `app/__init__.py`.

```powershell
.\build_exe.ps1          # dist\Nexum.exe (PyInstaller onefile, Nexum.spec)
.\build_installer.ps1    # dist\NexumSetup.exe (Inno Setup; winget install JRSoftware.InnoSetup)
.\publicar.ps1 1.0.58    # bump + build + commit + push + gh release create (auto-update)
```

Publicar exige `gh` autenticado (`winget install GitHub.cli` → `gh auth login`).
O repositório de releases precisa ser **público** (a verificação de update não usa
token). Nos clientes, configure o repo em **Configurações → Atualizações**
(`usuario/repo`) — eles recebem o aviso e atualizam com um clique. Override por
máquina: variável `NEXUM_UPDATE_REPO`.

## Estrutura

```
app/
  main.py            API FastAPI + serve a SPA + gate de rede
  deps.py            bootstrap (caminho do banco, engine, sessão, get_db)
  database.py        modelos SQLAlchemy + migrações
  routers/           endpoints por domínio (dashboard, transacoes, faturas, ...)
  parsers/           leitura de faturas/extratos (pdf_text via pypdfium2)
  templates/, static/  UI (Alpine.js + Tailwind + Chart.js)
run_nexum.py         launcher do exe (porta, janela nativa, modo dev/portátil)
tests/               pytest
```
