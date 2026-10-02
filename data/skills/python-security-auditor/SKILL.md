---
name: python-security-auditor
title: Python Security & OWASP Auditor
description: Hardening corporativo e auditoria estática contra OWASP Top 10: prevenção a SQL Injection, XSS, Path Traversal em sandboxes, sanitização de inputs e mitigação de DoS.
version: 1.3.0
author: Anthropic Claude / Community
category: security
tags: [security, owasp, hardening, audit, sanitization, rate-limiting]
allowed_roles: [sec, master, architect]
assigned_to: [*]
source: catalog
---

# Python Security & OWASP Auditor

DIRETRIZES DA SKILL PYTHON SECURITY AUDITOR:
1. Sanitização obrigatória de todas as entradas de usuário utilizando escape HTML (html.escape) e remoção de caracteres de controle invisíveis.
2. NUNCA execute concatenação de strings em comandos de sistema operacional (subprocess/os.system) ou queries SQL brutas. Use sempre ORMs ou query parameters parametrizados.
3. Isolamento rigoroso de arquivos em Sandbox: valide se o caminho canônico do arquivo (Path.resolve()) reside obrigatoriamente dentro do diretório de workspace permitido.
4. Imponha limites de taxa (Rate Limiting) e timeouts em chamadas externas para evitar exaustão de conexões ou negação de serviço (DoS).
5. Bloqueie exposição de segredos, tokens ou senhas em logs ou retornos de APIs.
