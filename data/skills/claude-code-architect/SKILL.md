---
name: claude-code-architect
title: Claude System Architect
description: Engenharia de software de alta fidelidade: arquitetura limpa, separação de camadas (Clean Architecture), contratos tipados com Pydantic, resiliência assíncrona e desacoplamento de storage.
version: 1.1.0
author: Anthropic Claude / Community
category: architecture
tags: [architecture, clean-code, solid, rest, pydantic, asyncio]
allowed_roles: [architect, master, dev]
assigned_to: [*]
source: catalog
---

# Claude System Architect

DIRETRIZES DA SKILL CLAUDE SYSTEM ARCHITECT:
1. Separação rigorosa de responsabilidades: Models (Pydantic), Routers/Controllers (HTTP), Services/Business Logic e Storage/Data Access.
2. Proibido misturar lógica de banco de dados diretamente em endpoints de rota.
3. Tipagem estática rigorosa em todas as assinaturas de funções e retornos assíncronos (async/await).
4. Tratamento defensivo de exceções: capturar erros específicos, registrar logs com contexto e retornar status codes HTTP semanticamente corretos (200, 201, 400, 404, 422, 500).
5. Código auto-documentado com docstrings em Markdown e comentários explicativos nas decisões não-triviais.
