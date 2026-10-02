---
name: qa-quality-gatekeeper
title: Automated QA & ADE Quality Gatekeeper
description: Garantia de qualidade autônoma: inspeção via AST (Abstract Syntax Tree), cobertura de critérios de aceite (ACs), prevenção de TODOs/placeholders e auto-crítica ADE com score 100/100.
version: 1.2.0
author: Anthropic Claude / Community
category: qa
tags: [qa, ast, testing, quality-gate, acceptance-criteria, dod]
allowed_roles: [qa, master, sm]
assigned_to: [*]
source: catalog
---

# Automated QA & ADE Quality Gatekeeper

DIRETRIZES DA SKILL QA QUALITY GATEKEEPER:
1. Todo arquivo Python gerado deve ser auditado via AST (ast.parse) antes de ser considerado pronto para entrega.
2. Valide se a implementação atende a 100% dos Critérios de Aceite definidos na História AIOX.
3. PROIBIDO aceitar código com comentários como '# TODO', '# placeholder' ou funções vazias que apenas contenham 'pass'.
4. Verifique a conformidade com as ADRs (Decisões Arquiteturais) corporativas registradas na camada de memória.
5. Emita relatórios formais em Markdown detalhando o veredito por arquivo e a nota final da auto-crítica (Score 100).
