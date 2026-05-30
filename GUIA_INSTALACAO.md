# Guia de Instalação — Nexum

Este app roda no **seu próprio computador** — nada vai para a internet. Os dados
ficam em um arquivo SQLite (por padrão em `%APPDATA%\Nexum\financeiro.db`).

## ⭐ Jeito mais fácil (Windows): o instalador `NexumSetup.exe`

Não precisa instalar Python, Poppler, nem nada. Veja [COMO_USAR.md](COMO_USAR.md):

1. Duplo-clique em **`NexumSetup.exe`** → Avançar → Instalar (**sem admin**).
2. Cria atalhos na **Área de Trabalho** e no **Menu Iniciar**; o app abre sozinho.

Dados em `%APPDATA%\Nexum` (preservados ao desinstalar/atualizar). Também há um
**modo portátil**: o `Nexum.exe` avulso com um `portable.txt` ao lado guarda os
dados em `data/` na própria pasta.

**Gerar os artefatos a partir do código:**
- `build_exe.ps1` → `dist\Nexum.exe` (executável único).
- `build_installer.ps1` → `dist\NexumSetup.exe` (instalador; requer Inno Setup:
  `winget install JRSoftware.InnoSetup`). A versão vem de `app/__init__.py`.

**Publicar uma atualização (auto-update via GitHub Releases):**

Há três formas — escolha uma. As duas primeiras são **automatizadas**.

**A) GitHub Actions (nuvem — recomendado):** não precisa buildar nada local.
```bash
# 1. suba a versão em app/__init__.py (ex: 1.0.3), commit
git tag v1.0.3
git push origin master --tags
```
O workflow `.github/workflows/release.yml` builda o exe+instalador num runner
Windows (instala o Inno Setup via choco) e publica a release com o
`NexumSetup.exe` anexado. Requer só que o repositório esteja no GitHub.

**B) Script local (`publicar.ps1`):** builda aqui e publica via GitHub CLI.
```powershell
# pré-requisito uma vez: winget install GitHub.cli ; gh auth login
.\publicar.ps1 1.0.3      # bump + build + commit + tag + release num passo só
```
(O workflow detecta que a release já tem o instalador e não duplica.)

**C) Manual:**
1. Suba o número em `app/__init__.py` (`__version__ = "1.1.0"`).
2. Rode `build_installer.ps1` para gerar o `dist\NexumSetup.exe`.
3. No GitHub, crie uma **Release** com tag `v1.1.0` e anexe o `NexumSetup.exe`.

Em qualquer caso, nos clientes basta ter o repositório configurado em
**Configurações → Atualizações** (`usuario/repo`) — eles recebem o aviso e
atualizam com um clique. (Override por máquina: variável `NEXUM_UPDATE_REPO`.)
⚠️ O repositório precisa ser **público** (a API de releases que o app consulta
não usa token; repo privado não é visível).

O restante deste guia descreve a forma **manual** (rodar pelo código-fonte), útil
no Mac ou para desenvolvimento.

---

## 🪟 Instalação no Windows

### Passo 1 — Instalar Python

1. Acesse https://www.python.org/downloads/
2. Clique no botão grande **"Download Python 3.x.x"** (qualquer versão 3.10+)
3. Abra o instalador
4. **MUITO IMPORTANTE**: marque a caixinha **"Add Python to PATH"** na primeira tela. Sem isso, nada funciona.
5. Clique em "Install Now" e aguarde
6. No final, clique em "Disable path length limit" se aparecer

Para confirmar que funcionou: abra o **Prompt de Comando** (tecla Windows → digite `cmd` → Enter) e digite:
```
python --version
```
Deve aparecer algo como `Python 3.12.x`. Se aparecer "comando não reconhecido", o PATH não foi marcado — desinstale e reinstale marcando a caixinha.

### Passo 2 — (não precisa mais de Poppler)

A leitura de PDF agora é feita pela biblioteca `pypdfium2`, que é instalada
junto pelo `pip` (Passo 3) — **não precisa instalar Poppler nem mexer no PATH**.

> Opcional: algumas faturas do Mercado Pago usam uma fonte "quebrada" que só é
> lida com OCR. Só nesse caso instale o Tesseract:
> https://github.com/UB-Mannheim/tesseract/wiki (instalador Windows).

### Passo 3 — Rodar o app

1. Extraia a pasta `financeiro_app` em qualquer lugar (ex.: `C:\Users\Micael\Documentos\financeiro_app`)
2. Dê um duplo-clique em `iniciar.bat`
3. Na primeira vez, vai aparecer "Instalando dependências..." — isso leva 1-2 minutos
4. Depois disso, o navegador abre sozinho em `http://localhost:8765`

**Pronto.** Para fechar, basta fechar a janela preta.

---

## 🍎 Instalação no Mac

### Passo 1 — Instalar Homebrew

Homebrew é um gerenciador que facilita instalar programas no Mac. Abra o **Terminal** (Cmd+Espaço → "Terminal") e cole:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Aperte Enter. Vai pedir senha do Mac (normal). Aguarde terminar (5-10 minutos).

No final, ele provavelmente vai pedir para você rodar duas linhas começando com `echo` — copie e cole essas linhas no terminal antes de continuar.

Para confirmar: feche e abra o Terminal de novo, e digite:
```bash
brew --version
```
Deve aparecer `Homebrew 4.x.x`.

### Passo 2 — Instalar Python e Poppler

No mesmo Terminal, rode:

```bash
brew install python poppler
```

Vai instalar os dois. Aguarde.

Confirme:
```bash
python3 --version
pdftotext -v
```

### Passo 3 — Rodar o app

1. Extraia a pasta `financeiro_app` em qualquer lugar (ex.: na sua pasta Documentos)
2. Dê um duplo-clique em `iniciar.command`
3. **Primeira vez no Mac**: o macOS pode bloquear dizendo "não pode ser aberto porque é de um desenvolvedor não identificado". Para liberar:
   - Abra **Ajustes do Sistema** → **Privacidade e Segurança**
   - Role até embaixo, vai ter "iniciar.command foi bloqueado..." → clique em **"Abrir mesmo assim"**
4. Na primeira vez, instala as dependências (1-2 minutos)
5. Navegador abre em `http://localhost:8765`

---

## ✅ Como usar (depois de instalado)

### Importar uma fatura

1. Abra o app (clica em `iniciar.bat` ou `iniciar.command`)
2. Topo direito: botão **"Importar PDF"**
3. Selecione o(s) PDFs das faturas (Nubank, Bradesco ou Santander)
4. Pronto — as transações aparecem nas abas Dashboard e Transações

### Categorizar manualmente

1. Aba **Transações**
2. Filtros no topo: marque **"Sem categoria"** para ver só as não classificadas
3. Clique no select da coluna "Categoria" e escolha
4. **O app aprende.** Da próxima vez que aparecer descrição igual, vai categorizar automaticamente
5. Mesma coisa para Atribuição (Casa, Cachorros, etc.)

### Criar regras

Diferente da memória (aprende com correções), regras pegam **palavras-chave**:
1. Aba **Regras** → **+ Nova regra**
2. Palavra-chave: parte da descrição (ex.: `MERCADO LIVRE`, `IFOOD`)
3. Categoria + Atribuição (atribuição é opcional)
4. Salvar — o app aplica em todas as transações pendentes

### Conciliação (Fase 1, básico)

A aba **Conciliação** mostra sugestões automáticas:
- **Pagamentos de fatura**: quando você importar extratos, vai detectar "Pagamento Bradescard - R$ 3.119,58" e ligar à fatura
- **Duplicatas**: mesma compra que apareceu em duas fontes

⚠️ **Na Fase 1, só faturas estão implementadas.** Importação de extratos vem na Fase 2 — vou precisar de exemplos dos seus extratos PDF/OFX para fazer.

---

## 💾 Backup

Seus dados estão **inteiros** num arquivo só: `financeiro_app/data/financeiro.db`.

**Backup simples**: copie esse arquivo para outro lugar (Google Drive, pen drive, etc.) periodicamente. Para restaurar, é só substituir.

**Recomendação**: coloque a pasta `financeiro_app/` inteira dentro do Dropbox ou Google Drive. Aí backup é automático e quando você migrar pro Mac, é só sincronizar.

---

## 🔧 Resolução de problemas

### "python não é reconhecido como comando" (Windows)
PATH não foi configurado. Desinstale o Python e reinstale **marcando "Add to PATH"**.

### "pdftotext: command not found" (Mac)
Rode no terminal: `brew install poppler`

### "ModuleNotFoundError: fastapi"
A instalação automática falhou. Abra o Prompt/Terminal na pasta do app e rode:
- Windows: `pip install -r requirements.txt`
- Mac: `pip3 install -r requirements.txt --break-system-packages`

### "Address already in use" / "Porta 8765 ocupada"
Outro app está usando a porta. Feche todas as janelas pretas e tente de novo. Se persistir, edite `iniciar.bat` ou `iniciar.command` e troque `8765` por outro número (ex.: `8766`).

### O navegador não abriu sozinho
Sem problema — abra manualmente: http://localhost:8765

### Erro ao parsear um PDF
O parser foi testado nos seus PDFs específicos. Se um banco mudar o layout, ele pode quebrar. Nesse caso me mande o PDF para eu ajustar o parser.

### Quero mover o app para outro computador
Copie a pasta `financeiro_app` inteira (incluindo `data/`). Instale Python + Poppler no novo computador e dê duplo-clique em `iniciar.bat`/`iniciar.command`.

---

## 🚀 Atalho de área de trabalho (opcional)

### Windows
Botão direito em `iniciar.bat` → "Criar atalho" → arraste o atalho para a área de trabalho. Pode renomear para "Financeiro" e mudar o ícone (botão direito no atalho → Propriedades → Alterar Ícone).

### Mac
Botão direito em `iniciar.command` → "Criar Apelido" → arraste para a área de trabalho ou Dock.

---

## 📋 Estrutura de pastas (pra você entender)

```
financeiro_app/
├── iniciar.bat              ← clique aqui no Windows
├── iniciar.command          ← clique aqui no Mac
├── requirements.txt         ← lista de dependências (não mexer)
├── GUIA_INSTALACAO.md       ← este arquivo
├── data/
│   └── financeiro.db        ← TODOS OS SEUS DADOS aqui (faça backup!)
└── app/
    ├── main.py              ← API web (FastAPI)
    ├── database.py          ← schema do banco
    ├── parsers/             ← código que lê os PDFs
    │   ├── nubank.py
    │   ├── bradesco.py
    │   └── santander.py
    ├── seed.py              ← contas, categorias, regras padrão
    ├── categorizacao.py     ← engine de auto-categorização
    ├── conciliacao.py       ← engine de conciliação
    ├── importacao.py        ← orquestra import
    ├── templates/index.html ← UI
    └── static/
        ├── app.js           ← lógica do front
        └── style.css        ← estilo
```

Se você quiser **personalizar regras**, pode editar `app/seed.py` (lista `REGRAS_PADRAO` lá embaixo) ou usar a tela de Regras no app.

Se quiser **mudar cores/estilos**, edite `app/templates/index.html` (cores Tailwind: troque `amber` por `blue`, `green`, etc.).

---

## ❓ Quando voltar a falar comigo

Você me chama de volta quando precisar:
- Adicionar importação de extrato (mande exemplos em PDF)
- Ajustar layout/cores do app
- Corrigir parser que quebrou (banco mudou layout)
- Adicionar features novas (gráficos, exports, mobile, etc.)
- Migrar para Mac (te ajudo no processo)

Bom uso 👋
