"""
Popula o banco com dados iniciais (contas, categorias, atribuições, regras).
Idempotente — só insere o que ainda não existe.
"""
try:
    from sqlalchemy.orm import Session
    from .database import Conta, Categoria, Atribuicao, Regra, Banco, Configuracao, Transacao
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


BANCOS_PADRAO = [
    # (nome, cor)
    ("Nubank",       "#820AD1"),
    ("Bradesco",     "#CC092F"),
    ("Santander",    "#EC0000"),
    ("Mercado Pago", "#00B1EA"),
    ("Banco do Brasil", "#FBBF24"),
    ("Itaú",         "#EC7000"),
    ("Inter",        "#FF7A00"),
    ("Caixa",        "#0076D6"),
]


CONTAS_PADRAO = [
    # (nome, tipo, banco, fechamento, vencimento, final, observacoes)
    ("Nubank Crédito",       "Cartão de Crédito", "Nubank",       2,  10, None, "Confirme o dia conforme seu cartão"),
    ("Bradesco Crédito",     "Cartão de Crédito", "Bradesco",     None, 15, "3015", "Amazon Mastercard Platinum"),
    ("Santander Crédito",    "Cartão de Crédito", "Santander",    27, 5,  "6391", "ELITE CASHBACK Visa Signature"),
    ("Mercado Pago Crédito", "Cartão de Crédito", "Mercado Pago", 9,  14, "2298", "Visa"),
    ("Nubank Conta",         "Conta Corrente",    "Nubank",       None, None, None, "Conta digital"),
    ("Bradesco Conta",       "Conta Corrente",    "Bradesco",     None, None, None, ""),
    ("Santander Conta",      "Conta Corrente",    "Santander",    None, None, None, ""),
    ("Banco do Brasil",      "Conta Corrente",    "BB",           None, None, None, ""),
    ("Dinheiro",             "Carteira",          None,           None, None, None, ""),
]


CATEGORIAS_PADRAO = [
    # (nome, tipo, orcamento, icone, essencial)
    # essencial=True: gasto recorrente/obrigatório que não dá pra cortar facilmente
    # essencial=False: discricionário/desejos — onde dá pra cortar primeiro

    # === Casa & contas fixas — todas essenciais ===
    ("Moradia",                "Despesa", 2000, "🏠", True),
    ("Energia",                "Despesa", 250,  "⚡", True),
    ("Água",                   "Despesa", 100,  "💧", True),
    ("Internet",               "Despesa", 150,  "📡", True),    # essencial hoje (trabalho/info)
    ("Telefone",               "Despesa", 100,  "📱", True),
    ("Assinaturas",            "Despesa", 150,  "📺", False),   # Netflix etc — dá pra cortar
    ("Serviços domésticos",    "Despesa", 400,  "🧹", True),    # fronteira → marcado essencial conforme regra

    # === Comida ===
    ("Mercado",                "Despesa", 1200, "🛒", True),
    ("Restaurante & Delivery", "Despesa", 600,  "🍽️", False),  # comer fora é discricionário

    # === Transporte ===
    ("Combustível",            "Despesa", 500,  "⛽", True),
    ("Transporte",             "Despesa", 200,  "🚕", True),
    ("Manutenção",             "Despesa", 300,  "🔧", True),    # fronteira → essencial

    # === Saúde — todas essenciais ===
    ("Saúde",                  "Despesa", 400,  "⚕️", True),
    ("Farmácia",               "Despesa", 200,  "💊", True),

    # === Pessoal ===
    ("Vestuário",              "Despesa", 200,  "👕", False),
    ("Cuidados pessoais",      "Despesa", 200,  "💇", True),    # fronteira → essencial
    ("Lazer",                  "Despesa", 400,  "🎬", False),
    ("Educação",               "Despesa", 300,  "📚", True),    # fronteira → essencial
    ("Viagem",                 "Despesa", 500,  "✈️", False),
    ("Presentes",              "Despesa", 150,  "🎁", False),

    # === Pet ===
    ("Pet Care",               "Despesa", 200,  "🐾", True),    # fronteira → essencial
    ("Veterinário",            "Despesa", 200,  "🏥", True),    # fronteira → essencial

    # === Diversos ===
    ("Compras",                "Despesa", 500,  "🛍️", False),  # eletrônicos, decoração — discricionário
    ("Impostos & taxas",       "Despesa", 200,  "🧾", True),
    ("Tarifas bancárias",      "Despesa", 50,   "🏦", True),
    ("Outros",                 "Despesa", 200,  "📦", True),    # padrão seguro

    # === Receitas — flag essencial não importa, mas precisa ter valor ===
    ("Salário",                "Receita", 0,    "💰", True),
    ("Pró-labore",             "Receita", 0,    "💼", True),
    ("Freelance",              "Receita", 0,    "👨‍💻", True),
    ("Rendimentos",            "Receita", 0,    "📊", True),
    ("Cashback",               "Receita", 0,    "🪙", True),
    ("Outros recebimentos",    "Receita", 0,    "💵", True),

    # === Especiais (não contam nos totais) ===
    ("Pagamento de Fatura",         "Despesa", 0, "💳", True),
    ("Transferência entre Contas",  "Despesa", 0, "🔁", True),
    ("Empréstimos a Terceiros",     "Despesa", 0, "🤝", True),
    ("Investimentos",               "Despesa", 0, "📈", True),
]


ATRIBUICOES_PADRAO = [
    # (nome, tipo, descricao, cor)
    ("Micael",      "Pessoa", "Despesa pessoal do Micael",       "#3B82F6"),
    ("Andreina",    "Pessoa", "Despesa pessoal da Andreina",     "#EC4899"),
    ("Casa",        "Grupo",  "Despesas comuns da casa",          "#10B981"),
    ("Suprimentos", "Grupo",  "Mantimentos e consumo do dia",     "#F59E0B"),
    ("Cachorros",   "Grupo",  "Pets, veterinário, ração",         "#8B5CF6"),
    ("Carro",       "Grupo",  "Combustível, peças, manutenção",   "#EF4444"),
    ("Saúde",       "Grupo",  "Plano, médico, farmácia",          "#06B6D4"),
    ("Lazer",       "Grupo",  "Diversão, viagens compartilhadas", "#F97316"),
]


# Regras: (palavra-chave, categoria_nome, atribuicao_nome, prioridade, comentario)
REGRAS_PADRAO = [
    # === Restaurante & Delivery ===
    ("IFOOD", "Restaurante & Delivery", None, 5, "Delivery"),
    ("UBER EATS", "Restaurante & Delivery", None, 5, "Delivery"),
    ("UBEREATS", "Restaurante & Delivery", None, 5, "Delivery"),
    ("RAPPI", "Restaurante & Delivery", None, 5, "Delivery"),
    ("AIQFOME", "Restaurante & Delivery", None, 5, "Delivery"),
    ("RESTAURANTE", "Restaurante & Delivery", None, 3, ""),
    ("REST ", "Restaurante & Delivery", None, 3, ""),
    ("LANCHONETE", "Restaurante & Delivery", None, 3, ""),
    ("PIZZARIA", "Restaurante & Delivery", None, 3, ""),
    ("HAMBURGUERIA", "Restaurante & Delivery", None, 3, ""),
    ("SUBWAY", "Restaurante & Delivery", None, 4, "Fast food"),
    ("MCDONALD", "Restaurante & Delivery", None, 4, "Fast food"),
    ("BURGER KING", "Restaurante & Delivery", None, 4, "Fast food"),
    ("HABIB", "Restaurante & Delivery", None, 4, "Fast food"),
    ("OUTBACK", "Restaurante & Delivery", None, 4, ""),
    ("STARBUCKS", "Restaurante & Delivery", None, 4, "Cafeteria"),
    # Padaria continua em "Restaurante & Delivery" (consumo de fora, não compra do mês)
    ("PADARIA", "Restaurante & Delivery", "Suprimentos", 3, ""),
    ("BOUTIQUE DO PAO", "Restaurante & Delivery", "Suprimentos", 4, ""),
    ("CASA DO BOLO", "Restaurante & Delivery", "Suprimentos", 4, ""),

    # === Mercado ===
    ("CARREFOUR", "Mercado", "Suprimentos", 5, ""),
    ("EXTRA ", "Mercado", "Suprimentos", 5, ""),
    ("PAO DE ACUCAR", "Mercado", "Suprimentos", 5, ""),
    ("PÃO DE AÇÚCAR", "Mercado", "Suprimentos", 5, ""),
    ("ASSAI", "Mercado", "Suprimentos", 5, "Atacado"),
    ("ASSAÍ", "Mercado", "Suprimentos", 5, "Atacado"),
    ("ATACADAO", "Mercado", "Suprimentos", 5, "Atacado"),
    ("ATACADÃO", "Mercado", "Suprimentos", 5, "Atacado"),
    ("ATACAREJO", "Mercado", "Suprimentos", 5, "Atacado"),
    ("SAM'S CLUB", "Mercado", "Suprimentos", 5, "Atacado"),
    ("HORTIFRUTI", "Mercado", "Suprimentos", 5, ""),
    ("SUPERMERCADO", "Mercado", "Suprimentos", 4, ""),
    ("HIPERMERCADO", "Mercado", "Suprimentos", 4, ""),
    ("MERCADO ", "Mercado", "Suprimentos", 3, ""),
    ("MERCADO*MERCADOLIVRE", "Mercado", "Suprimentos", 5, "Mercado Livre"),

    # === Transporte (apps + público) ===
    ("UBER", "Transporte", None, 5, "App"),
    ("99 ", "Transporte", None, 5, "App"),
    ("99POP", "Transporte", None, 5, "App"),
    ("CABIFY", "Transporte", None, 5, "App"),
    ("METRÔ", "Transporte", None, 5, "Público"),
    ("METRO ", "Transporte", None, 4, "Público"),
    ("CPTM", "Transporte", None, 5, "Público"),
    ("BILHETE UNICO", "Transporte", None, 5, "Público"),
    ("ESTAPAR", "Transporte", "Carro", 5, "Estacionamento"),
    ("ESTACIONAMENTO", "Transporte", "Carro", 4, "Estacionamento"),
    ("ZONA AZUL", "Transporte", "Carro", 5, "Estacionamento"),
    ("PEDÁGIO", "Transporte", "Carro", 5, "Pedágio"),
    ("SEM PARAR", "Transporte", "Carro", 5, "Pedágio"),
    ("CONECTCAR", "Transporte", "Carro", 5, "Pedágio"),

    # === Combustível ===
    ("POSTO", "Combustível", "Carro", 5, ""),
    ("SHELL", "Combustível", "Carro", 5, ""),
    ("IPIRANGA", "Combustível", "Carro", 5, ""),
    ("PETROBRAS", "Combustível", "Carro", 5, ""),
    ("BR MANIA", "Combustível", "Carro", 5, ""),

    # === Veículo (manutenção, peças, IPVA) ===
    ("PNEUS", "Manutenção", "Carro", 5, "Manutenção"),
    ("AUTOPECA", "Manutenção", "Carro", 5, "Peças"),
    ("AUTOPEÇA", "Manutenção", "Carro", 5, "Peças"),
    ("MECANICA", "Manutenção", "Carro", 5, "Manutenção"),
    ("MECÂNICA", "Manutenção", "Carro", 5, "Manutenção"),
    ("OFICINA", "Manutenção", "Carro", 4, "Manutenção"),
    ("AUDIOVIDEOCIA", "Manutenção", "Carro", 4, "Som automotivo"),
    ("IPVA", "Manutenção", "Carro", 5, "Imposto veículo"),
    ("LICENCIAMENTO", "Manutenção", "Carro", 5, ""),
    ("DPVAT", "Manutenção", "Carro", 5, "Seguro obrigatório"),
    ("PORTO SEGURO", "Manutenção", "Carro", 4, "Seguro auto"),

    # === Casa & contas fixas ===
    ("ENEL", "Energia", "Casa", 5, ""),
    ("LIGHT ", "Energia", "Casa", 5, ""),
    ("CEMIG", "Energia", "Casa", 5, ""),
    ("CPFL", "Energia", "Casa", 5, ""),
    ("EQUATORIAL", "Energia", "Casa", 5, ""),
    ("COPEL", "Energia", "Casa", 5, ""),
    ("ELETROPAULO", "Energia", "Casa", 5, ""),
    ("SABESP", "Água", "Casa", 5, ""),
    ("CEDAE", "Água", "Casa", 5, ""),
    ("COPASA", "Água", "Casa", 5, ""),
    ("SANEPAR", "Água", "Casa", 5, ""),
    ("EMBASA", "Água", "Casa", 5, ""),
    ("COMGAS", "Moradia", "Casa", 5, "Gás"),
    ("CONDOMINIO", "Moradia", "Casa", 5, ""),
    ("CONDOMÍNIO", "Moradia", "Casa", 5, ""),
    ("ALUGUEL", "Moradia", "Casa", 5, ""),
    ("MATERIAL DE CONSTRU", "Manutenção", "Casa", 4, "Reforma/construção"),
    ("CONSTRUSENDY", "Manutenção", "Casa", 4, "Reforma/construção"),
    ("IPTU", "Impostos & taxas", "Casa", 5, ""),

    # === Internet (residencial / fibra) ===
    ("INTERNET",               "Internet", "Casa", 5, ""),
    ("BANDA LARGA",            "Internet", "Casa", 5, ""),
    ("FIBRA",                  "Internet", "Casa", 5, ""),
    ("WIFI",                   "Internet", "Casa", 5, ""),
    ("BRISANET",               "Internet", "Casa", 5, ""),
    ("NETFIBRA",               "Internet", "Casa", 5, ""),
    ("OI FIBRA",               "Internet", "Casa", 5, ""),
    ("VIVO FIBRA",             "Internet", "Casa", 5, ""),
    ("CLARO HDTV",             "Internet", "Casa", 5, ""),
    ("LIVE TIM",               "Internet", "Casa", 5, ""),
    ("SKY ",                   "Internet", "Casa", 5, "TV por assinatura"),

    # === Telefone (celular / fixo) ===
    ("RECARGA DE CELULAR",     "Telefone", None, 6, "Recarga"),
    ("RECARGA CELULAR",        "Telefone", None, 6, "Recarga"),
    ("VIVO CELULAR",           "Telefone", None, 6, ""),
    ("CLARO MOVEL",            "Telefone", None, 6, ""),
    ("CLARO MÓVEL",            "Telefone", None, 6, ""),
    ("TIM CELULAR",            "Telefone", None, 6, ""),
    # Genéricos: por padrão vão pra Telefone (você corrige se for fibra)
    ("VIVO ",                  "Telefone", None, 3, ""),
    ("CLARO ",                 "Telefone", None, 3, ""),
    ("TIM ",                   "Telefone", None, 3, ""),
    ("OI ",                    "Telefone", None, 3, ""),

    # === Saúde ===
    ("DROGARIA", "Farmácia", "Saúde", 5, ""),
    ("DROGASIL", "Farmácia", "Saúde", 5, ""),
    ("PACHECO", "Farmácia", "Saúde", 5, ""),
    ("PAGUE MENOS", "Farmácia", "Saúde", 5, ""),
    ("RAIA ", "Farmácia", "Saúde", 5, ""),
    ("ULTRAFARMA", "Farmácia", "Saúde", 5, ""),
    ("PANVEL", "Farmácia", "Saúde", 5, ""),
    ("FARMACIA", "Farmácia", "Saúde", 5, ""),
    ("FARMÁCIA", "Farmácia", "Saúde", 5, ""),
    ("HOSPITAL", "Saúde", "Saúde", 5, ""),
    ("CLINICA", "Saúde", "Saúde", 5, ""),
    ("CLÍNICA", "Saúde", "Saúde", 5, ""),
    ("LABORATORIO", "Saúde", "Saúde", 5, ""),
    ("LABORATÓRIO", "Saúde", "Saúde", 5, ""),
    ("UNIMED", "Saúde", "Saúde", 5, ""),
    ("AMIL", "Saúde", "Saúde", 5, ""),
    ("HAPVIDA", "Saúde", "Saúde", 5, ""),

    # === Assinaturas / Streaming ===
    ("NETFLIX", "Assinaturas", "Lazer", 5, ""),
    ("SPOTIFY", "Assinaturas", "Lazer", 5, ""),
    ("AMAZON PRIME", "Assinaturas", "Lazer", 5, ""),
    ("PRIME VIDEO", "Assinaturas", "Lazer", 5, ""),
    ("DISNEY", "Assinaturas", "Lazer", 5, ""),
    ("HBO", "Assinaturas", "Lazer", 5, ""),
    ("DEEZER", "Assinaturas", "Lazer", 5, ""),
    ("YOUTUBE", "Assinaturas", "Lazer", 5, ""),
    ("APPLE.COM", "Assinaturas", None, 5, "Apple"),
    ("ITUNES", "Assinaturas", None, 5, "Apple"),
    ("MICROSOFT", "Assinaturas", None, 5, "Software"),
    ("ADOBE", "Assinaturas", None, 5, "Software"),

    # === Lazer ===
    ("CINEMARK", "Lazer", "Lazer", 5, "Cinema"),
    ("CINEPOLIS", "Lazer", "Lazer", 5, "Cinema"),
    ("KINOPLEX", "Lazer", "Lazer", 5, "Cinema"),
    ("INGRESSO.COM", "Lazer", "Lazer", 5, "Eventos"),
    ("SYMPLA", "Lazer", "Lazer", 5, "Eventos"),
    ("STEAM ", "Lazer", "Lazer", 5, "Games"),
    ("BLIZZARD", "Lazer", "Lazer", 5, "Games"),
    ("NUUVEM", "Lazer", "Lazer", 5, "Games"),
    ("PLAYSTATION", "Lazer", "Lazer", 5, "Games"),
    ("XBOX", "Lazer", "Lazer", 5, "Games"),
    ("NINTENDO", "Lazer", "Lazer", 5, "Games"),

    # === Compras ===
    ("AMAZON", "Compras", None, 3, "Online"),
    ("MERCADOLIVRE", "Compras", None, 3, "Online"),
    ("MERCADO LIVRE", "Compras", None, 3, "Online"),
    ("SHOPEE", "Compras", None, 4, "Online"),
    ("ALIEXPRESS", "Compras", None, 4, "Online"),
    ("MAGAZINE LUIZA", "Compras", None, 4, ""),
    ("MAGALU", "Compras", None, 4, ""),
    ("AMERICANAS", "Compras", None, 4, ""),
    ("KABUM", "Compras", None, 5, "Eletrônicos"),
    ("KA BUM", "Compras", None, 5, "Eletrônicos"),
    ("PICHAU", "Compras", None, 5, "Eletrônicos"),
    ("GOCASE", "Compras", None, 5, "Acessórios"),
    ("PRIDEMUSIC", "Compras", None, 5, "Instrumentos"),
    ("VINDI ", "Compras", None, 4, "Recorrência online"),

    # === Vestuário ===
    ("RENNER", "Vestuário", None, 5, ""),
    ("RIACHUELO", "Vestuário", None, 5, ""),
    ("C&A", "Vestuário", None, 5, ""),
    ("ZARA", "Vestuário", None, 5, ""),
    ("MARISA", "Vestuário", None, 5, ""),
    ("HERING", "Vestuário", None, 5, ""),
    ("NIKE", "Vestuário", None, 5, "Esportivo"),
    ("ADIDAS", "Vestuário", None, 5, "Esportivo"),
    ("CENTAURO", "Vestuário", None, 5, "Esportivo"),
    ("ICOMM", "Vestuário", None, 4, ""),
    ("OQVESTIR", "Vestuário", None, 4, ""),

    # === Educação ===
    ("UDEMY", "Educação", None, 5, "Cursos"),
    ("ALURA", "Educação", None, 5, "Cursos"),
    ("HOTMART", "Educação", None, 4, "Cursos"),
    ("FACULDADE", "Educação", None, 5, ""),
    ("UNIVERSIDADE", "Educação", None, 5, ""),
    ("LIVRARIA", "Educação", None, 5, ""),
    ("KINDLE", "Educação", None, 5, ""),

    # === Pet Care (banho, tosa, brinquedo) ===
    # Lojas de pet (PETZ, COBASI, PETLOVE) ficam sem regra automática:
    # quando você compra ração lá, marca como "Mercado" + atribuição Cachorros;
    # quando é banho/tosa, marca como "Pet Care".
    ("BANHO E TOSA", "Pet Care", "Cachorros", 6, ""),
    ("BANHO TOSA",   "Pet Care", "Cachorros", 6, ""),
    ("TOSA ",        "Pet Care", "Cachorros", 5, ""),
    ("PET HOTEL",    "Pet Care", "Cachorros", 5, "Hospedagem do pet"),
    ("ADESTRAMENTO", "Pet Care", "Cachorros", 5, ""),

    # === Veterinário (separado de Pet) ===
    ("VETERINARIO", "Veterinário", "Cachorros", 5, ""),
    ("VETERINÁRIO", "Veterinário", "Cachorros", 5, ""),
    ("VETERINARIA", "Veterinário", "Cachorros", 5, ""),
    ("VETERINÁRIA", "Veterinário", "Cachorros", 5, ""),
    ("CLINICA VET", "Veterinário", "Cachorros", 5, ""),

    # === Tarifas bancárias ===
    ("TARIFA", "Tarifas bancárias", None, 5, ""),
    ("ANUIDADE", "Tarifas bancárias", None, 5, ""),
    ("IOF", "Tarifas bancárias", None, 5, ""),

    # === Pagamento de fatura (extratos) — NÃO duplica com a fatura em si ===
    ("PAGAMENTO DE FATURA", "Pagamento de Fatura", None, 10, "Extrato — pgto fatura cartão"),
    ("PAGAMENTO FATURA",    "Pagamento de Fatura", None, 10, "Extrato — pgto fatura cartão"),
    ("PGTO FATURA",         "Pagamento de Fatura", None, 10, "Extrato — pgto fatura cartão"),
    ("BANCO IBI",           "Pagamento de Fatura", None, 10, "= Bradescard / Bradesco fatura"),
    ("BRADESCARD",          "Pagamento de Fatura", None, 10, "Pgto fatura Bradesco"),

    # === Investimentos (aplicações em renda fixa/variável) ===
    # Categoria especial: não conta em despesas, abate via módulo Investimentos.
    ("APLICACAO CDB",       "Investimentos", None, 8, "Aplicação CDB"),
    ("APLICAÇÃO CDB",       "Investimentos", None, 8, "Aplicação CDB"),
    ("APLICACAO LCI",       "Investimentos", None, 8, "Aplicação LCI"),
    ("APLICAÇÃO LCI",       "Investimentos", None, 8, "Aplicação LCI"),
    ("APLICACAO LCA",       "Investimentos", None, 8, "Aplicação LCA"),
    ("APLICAÇÃO LCA",       "Investimentos", None, 8, "Aplicação LCA"),
    ("APLICACAO TESOURO",   "Investimentos", None, 8, "Tesouro Direto"),
    ("TESOURO DIRETO",      "Investimentos", None, 8, "Tesouro Direto"),
    ("APLICACAO POUPANCA",  "Investimentos", None, 8, "Poupança"),
    ("DEPOSITO POUPANCA",   "Investimentos", None, 8, "Poupança"),
    ("XP INVEST",           "Investimentos", None, 7, "XP Investimentos"),
    ("RICO INVEST",         "Investimentos", None, 7, "Rico"),
    ("BTG PACTUAL DIG",     "Investimentos", None, 7, "BTG"),
    ("NUINVEST",            "Investimentos", None, 7, "NuInvest"),
    ("NU INVEST",           "Investimentos", None, 7, "NuInvest"),
    ("INTER INVEST",        "Investimentos", None, 7, "Inter Invest"),
    ("INTER DTVM",          "Investimentos", None, 7, "Inter Invest"),

    # === Receitas ===
    ("SALARIO", "Salário", None, 5, ""),
    ("SALÁRIO", "Salário", None, 5, ""),
    ("VENCIMENTO", "Salário", None, 5, ""),
    ("FOLHA PGTO", "Salário", None, 5, ""),
    ("PRO LABORE", "Pró-labore", None, 5, ""),
    ("PRÓ-LABORE", "Pró-labore", None, 5, ""),
    ("PROLABORE", "Pró-labore", None, 5, ""),
    ("RENDIMENTO POUPANCA", "Rendimentos", None, 5, "Poupança"),
    ("RENDIMENTO", "Rendimentos", None, 4, ""),
    ("DIVIDENDO", "Rendimentos", None, 5, ""),
]


FLAG_SEED_CONCLUIDO = "seed_concluido"


def seed(session, forcar: bool = False):
    """
    Insere os dados padrão (categorias, atribuições, regras, bancos, contas).

    Comportamento:
      - Roda APENAS na primeira inicialização do banco (idempotente sem efeito
        colateral). Marca `Configuracao(chave="seed_concluido", valor="true")`
        no fim da execução.
      - Inicializações subsequentes pulam tudo, respeitando todas as exclusões
        do usuário (categorias, atribuições, regras removidas ficam removidas).
      - Use `forcar=True` apenas em endpoint dedicado ("Resetar padrões")
        quando o usuário quer reaplicar tudo conscientemente.
    """
    if not HAS_SQLALCHEMY:
        raise RuntimeError("SQLAlchemy não instalado — instale com: pip install sqlalchemy")

    # Se seed já rodou e não foi forçado, pula tudo
    if not forcar:
        flag = session.query(Configuracao).filter(Configuracao.chave == FLAG_SEED_CONCLUIDO).first()
        if flag and flag.valor == "true":
            return

        # Migração automática: se o banco já tem transações, é usuário existente
        # (anterior a esta feature). Marca a flag e pula — assim respeitamos
        # categorias/atribuições/regras que ele já tinha excluído antes.
        tem_transacoes = session.query(Transacao).first() is not None
        if tem_transacoes:
            session.add(Configuracao(chave=FLAG_SEED_CONCLUIDO, valor="true"))
            session.flush()
            return

    # Bancos: só cria os padrão na primeira inicialização (tabela vazia).
    # Se o usuário já tem bancos, respeita o que ele deixou — não recria nada.
    if session.query(Banco).count() == 0:
        for nome, cor in BANCOS_PADRAO:
            session.add(Banco(nome=nome, cor=cor))
        session.flush()

    banco_map = {b.nome: b.id for b in session.query(Banco).all()}

    # Contas: só cria as padrão se NUNCA houve conta cadastrada (primeira inicialização).
    # Se o usuário já tem alguma conta (mesmo que tenha excluído outras depois), não recria
    # nada — respeita a configuração dele.
    primeira_vez = session.query(Conta).count() == 0
    if primeira_vez:
        for nome, tipo, banco, fech, venc, final, obs in CONTAS_PADRAO:
            session.add(Conta(
                nome=nome, tipo=tipo, banco=banco,
                banco_id=banco_map.get(banco) if banco else None,
                dia_fechamento=fech, dia_vencimento=venc,
                final=final, observacoes=obs,
            ))
        session.flush()

    # Categorias
    for nome, tipo, orc, icone, essencial in CATEGORIAS_PADRAO:
        if not session.query(Categoria).filter(Categoria.nome == nome).first():
            session.add(Categoria(nome=nome, tipo=tipo, orcamento_mensal=orc, icone=icone, essencial=essencial))
    session.flush()

    # Atribuições
    for nome, tipo, desc, cor in ATRIBUICOES_PADRAO:
        if not session.query(Atribuicao).filter(Atribuicao.nome == nome).first():
            session.add(Atribuicao(nome=nome, tipo=tipo, descricao=desc, cor=cor))
    session.flush()

    # Regras (resolve nomes para IDs)
    cat_map = {c.nome: c.id for c in session.query(Categoria).all()}
    atr_map = {a.nome: a.id for a in session.query(Atribuicao).all()}

    for kw, cat_nome, atr_nome, prio, com in REGRAS_PADRAO:
        existente = session.query(Regra).filter(Regra.palavra_chave == kw).first()
        if existente:
            continue
        session.add(Regra(
            palavra_chave=kw,
            categoria_id=cat_map.get(cat_nome),
            atribuicao_id=atr_map.get(atr_nome) if atr_nome else None,
            prioridade=prio,
            comentario=com,
        ))
    session.flush()

    # Marca seed como concluído (não roda mais nas próximas inicializações)
    flag = session.query(Configuracao).filter(Configuracao.chave == FLAG_SEED_CONCLUIDO).first()
    if flag:
        flag.valor = "true"
    else:
        session.add(Configuracao(chave=FLAG_SEED_CONCLUIDO, valor="true"))
    session.flush()
