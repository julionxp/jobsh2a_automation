# Jobs H-2B Automation

Automação para buscar vagas sazonais no SeasonalJobs, classificar oportunidades, salvar os dados no PostgreSQL e preparar candidaturas por email.

## Configuração local

1. Crie seu ambiente virtual e instale as dependências:

   ```bash
   python -m venv .venv
   # Windows: .venv\Scripts\activate
   # Linux/macOS: source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Copie `.env.example` para `.env` e ajuste as variáveis para seu ambiente.
3. Adicione seus currículos e cartas em `assets/resumes/` e `assets/cover_letters/`. Esses PDFs são pessoais e ficam fora do Git.
4. Configure os arquivos OAuth do Gmail localmente nos caminhos definidos no `.env`.
5. Inicie o PostgreSQL e execute a automação.

## Execução segura

Por padrão, a automação apenas lista as candidaturas pendentes; ela não envia emails.

```bash
python main.py --headless
```

Para autorizar o envio real após a coleta:

```bash
python main.py --headless --send
```

Também é possível testar o módulo de envio separadamente:

```bash
python -m automation.send_pending_emails
python -m automation.send_pending_emails --send
```

**Atenção:** revise destinatários e conteúdo antes de usar `--send`. A menção a H-2B em uma vaga não garante que o empregador aceite candidatos que ainda estão fora dos Estados Unidos.

## Arquivos locais ignorados pelo Git

- `.env` e tokens/credenciais OAuth;
- PDFs de currículo e carta de apresentação;
- logs, ambientes virtuais e arquivos do editor.

Use `.env.example` como referência, nunca coloque valores reais de credenciais nele.
