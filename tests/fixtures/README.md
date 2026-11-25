# Fixtures sintéticas

Todos os dados desta pasta são **inventados**: nomes, valores, ids e números de conta não
correspondem a nenhuma pessoa ou conta real. Nunca copie aqui JSON baixado da Pluggy
(`data/raw/` existe só localmente e fica fora do Git).

Cenário: item MeuPluggy com uma conta corrente e um cartão, sincronizado em dois dias.

- `day1/`: 2026-01-10. O cartão tem duas compras PENDING (`p1`, `p2`).
- `day2/`: 2026-01-11. `p1` foi confirmada com outro id (`c5`, mesmo valor e descrição);
  `p2` sumiu sem substituta (cancelada). O preço da cota de `FICT11` mudou.
