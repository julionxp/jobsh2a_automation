# H-2A Jobs Automation

Automação para coletar ordens de trabalho agrícolas H-2A do SeasonalJobs, pontuar oportunidades, salvar no PostgreSQL e preparar candidaturas por email.

## Fonte de dados

A coleta usa o feed oficial **790/790A** do Department of Labor. Ele disponibiliza ordens de trabalho H-2A enviadas ou atualizadas nos últimos 20 dias e é atualizado diariamente. A automação baixa o ZIP diário (com fallback para o dia anterior), extrai o JSON e normaliza os registros.

Uma ordem H-2A publicada não garante, por si só, que o empregador esteja aceitando candidatos do exterior ou oferecendo apoio individual de visto. Confira as instruções de recrutamento da vaga antes de se candidatar.

## Configuração

1. Crie o ambiente virtual e instale:
   ```bash
   python -m venv .venv
   # Windows: .venv\\Scripts\\activate
   # Linux/macOS: source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Copie `.env.example` para `.env` e configure o PostgreSQL e as credenciais necessárias.
3. Coloque seus currículos e cartas em `assets/resumes/` e `assets/cover_letters/` (arquivos pessoais não são versionados).
4. Execute em modo seguro:
   ```bash
   python main.py --headless
   ```

Por padrão, nenhum email é enviado. Para autorizar envios reais, use explicitamente:
```bash
python main.py --headless --send
```

Opcionalmente, filtre o feed por palavras:
```bash
python main.py --headless --search "farmworker,harvest,livestock"
```

Sem `--search`, são coletadas todas as ordens H-2A do feed. Campos antigos com prefixo H-2B permanecem no banco por compatibilidade; novos registros são identificados como H-2A.
