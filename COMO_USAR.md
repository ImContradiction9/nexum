# Nexum — Como usar (Windows)

## Instalação

Há duas formas de usar o Nexum. A recomendada é o **instalador**.

### Opção A — Instalador (recomendada) 🎉

1. Dê **duplo-clique** em **`NexumSetup.exe`**.
2. Siga o assistente (Avançar → Instalar). **Não precisa de administrador.**
3. No fim, o Nexum abre sozinho. Pronto.

O instalador:
- Instala o programa em `%LocalAppData%\Programs\Nexum` (perfil do usuário, sem UAC).
- Cria **atalho na Área de Trabalho** e no **Menu Iniciar** (lista de aplicativos).
- Guarda seus dados em **`%APPDATA%\Nexum`** (veja abaixo).
- Inclui um **desinstalador** (Painel de Controle → Aplicativos, ou Menu Iniciar).

### Opção B — Portátil (sem instalar)

1. Copie o **`Nexum.exe`** sozinho para qualquer pasta (ex.: pen drive).
2. Dê duplo-clique.

No modo portátil, os dados ficam em uma pasta **`data/`** ao lado do `Nexum.exe`
**se** existir um arquivo vazio chamado **`portable.txt`** na mesma pasta. Sem o
`portable.txt`, mesmo o `Nexum.exe` avulso usa `%APPDATA%\Nexum`.

> Na primeira vez, o Windows pode mostrar um aviso azul do "Windows protegeu
> seu PC" (SmartScreen), porque o programa não tem assinatura digital paga.
> Clique em **"Mais informações" → "Executar assim mesmo"**. É seguro: o app
> roda 100% no seu computador e não envia seus dados pra lugar nenhum.

## Onde ficam meus dados

Por padrão, em **`%APPDATA%\Nexum`** (cole isso na barra do Explorador):

- `financeiro.db` — **todos os seus dados** (faça backup deste arquivo!)
- `backups/` — cópias automáticas (uma por dia, mantém as 10 mais recentes)
- `nexum.log` — log de diagnóstico

**Backup:** copie `financeiro.db` para um pen drive / nuvem de vez em quando.
Para restaurar, é só substituir o arquivo.

**Mudar de computador:** instale o Nexum no PC novo e copie seu `financeiro.db`
para a pasta `%APPDATA%\Nexum` de lá.

### Vim da versão portátil antiga (dados ao lado do exe)?

Se você já usava o `Nexum.exe` com a pasta `data/` ao lado, traga seus dados:

- **Jeito simples:** copie seu `data\financeiro.db` antigo para `%APPDATA%\Nexum\`.
- **Migração automática:** na primeira vez, se `%APPDATA%\Nexum` ainda não tiver
  banco e existir um `data\financeiro.db` **na pasta onde o Nexum.exe está
  instalado**, o app traz o banco (e os backups) pra você automaticamente.

## Como fechar

Basta **fechar a janela do Nexum no navegador**. O servidor encerra sozinho
logo em seguida — não fica nada rodando em segundo plano nem janela nenhuma na
tela. Para usar de novo, é só abrir pelo atalho.

## Atualizações automáticas

Se você publicar novas versões no **GitHub Releases**, o Nexum avisa sozinho:

1. Em **Configurações → Perfil → Atualizações do app**, preencha o repositório
   no formato `usuario/repo` e clique em **"Salvar e verificar"**.
2. Quando houver versão nova, aparece uma **faixa amarela no topo** do app.
   Clique em **"Atualizar agora"**: o Nexum baixa o instalador, fecha, instala
   a nova versão e reabre sozinho — sem você fazer mais nada.

> A faixa só mostra o botão "Atualizar agora" na versão **instalada** (pelo
> `NexumSetup.exe`). Na versão portátil, ela mostra um link de download.

## Importar faturas (PDF)

Funciona para Nubank, Bradesco, Santander e Mercado Pago. A leitura de PDF já
vem embutida — **não precisa mais do Poppler**.

> Exceção rara: algumas faturas do Mercado Pago usam uma fonte "quebrada" que
> exige OCR. Só nesse caso é preciso instalar o Tesseract
> (https://github.com/UB-Mannheim/tesseract/wiki). As outras funcionam direto.

## Problemas?

- **Porta ocupada:** o Nexum acha outra porta livre automaticamente.
- **O navegador não abriu:** abra manualmente `http://127.0.0.1:8765`.
- **Antivírus reclamou:** é falso positivo comum com `.exe` empacotado; libere
  o arquivo na quarentena ou adicione exceção.
- **Quero os dados em outra pasta:** defina a variável de ambiente
  `NEXUM_DATA_DIR` apontando para a pasta desejada.
