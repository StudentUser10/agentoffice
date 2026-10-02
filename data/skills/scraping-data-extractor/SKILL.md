---
name: scraping-data-extractor
title: Data Extraction & Web Scraping Specialist
description: Extração estruturada de dados da web: requisições HTTP seguras, parsing de HTML/JSON, rotação de headers (User-Agent), extração via Regex/Seletores e gravação em CSV/JSON no sandbox.
version: 1.0.0
author: Anthropic Claude / Community
category: code
tags: [scraper, data, extraction, parser, httpx, json]
allowed_roles: [dev, master]
assigned_to: [*]
source: catalog
---

# Data Extraction & Web Scraping Specialist

DIRETRIZES DA SKILL DATA EXTRACTION & SCRAPING:
1. Utilize headers HTTP realistas e respeite o robots.txt e limites de requisições por segundo.
2. Valide e sanitize os dados extraídos antes de persistir em disco.
3. Salve os resultados em JSON estruturado ou CSV bem formatado dentro do diretório sandbox autorizado.
4. Isole o tratamento de erros para links quebrados ou payloads malformados sem derrubar o pipeline.
