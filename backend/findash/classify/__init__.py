"""Classificação derivada das transações.

Nada aqui altera o dado bruto: a classificação é recalculada do zero a partir das tabelas da
sincronização, das regras (config/ e data/regras_pessoais.yaml) e das decisões do usuário
(classification_overrides e status de recurring_rules).
"""
