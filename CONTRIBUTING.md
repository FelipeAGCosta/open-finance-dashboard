# Contribuindo

Obrigado pelo interesse! Issues com bugs, ideias e perfis de banco novos são muito bem-vindos.

## Ambiente

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
npm --prefix frontend ci
findash demo                                        # confira que tudo sobe com dados sintéticos
```

## Antes de abrir um PR

```bash
pytest
ruff check backend tests && ruff format --check backend tests
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
```

A CI roda exatamente esses comandos.

## Rodando só um teste

No backend, rode um arquivo ou filtre pelo nome do teste:

```bash
pytest tests/test_plan.py
pytest -k nome
```

No frontend, rode um arquivo específico:

```bash
npm --prefix frontend test -- src/lib/format.test.ts
```

## Regras da casa

- **Nunca** coloque dados reais em testes, fixtures, issues ou screenshots: nomes, valores, ids da Pluggy,
  extratos. Invente. As imagens do README saem do `findash demo`.
- Dinheiro é sempre `int` em centavos; datas no banco são UTC sem fuso.
- Mudança no esquema do banco = nova migração Alembic em `backend/findash/db/migrations/versions/`
  (o teste `test_migrations_match_models` confere que o esquema bate com os modelos).
- Comentários explicam o *porquê*, não o *o quê*.
- Banco novo? Comece por [docs/institution-profiles.md](docs/institution-profiles.md).
