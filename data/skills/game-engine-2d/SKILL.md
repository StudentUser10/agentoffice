---
name: game-engine-2d
title: 2D Canvas & Arcade Game Engine
description: Especialista em desenvolvimento de jogos 2D nativos: game loop estável em 60 FPS, detecção de colisão AABB, física vetorial (gravidade, aceleração, atrito), partículas e HUD de pontuação.
version: 1.0.0
author: Anthropic Claude / Community
category: code
tags: [game, canvas, physics, 2d, arcade, collision, gameloop]
allowed_roles: [dev, master]
assigned_to: [*]
source: catalog
---

# 2D Canvas & Arcade Game Engine

DIRETRIZES DA SKILL 2D GAME ENGINE:
1. Implemente o clássico loop de jogo desacoplado (update e render/draw) com base em requestAnimationFrame e cálculo de delta time (dt).
2. Detecção de colisão eficiente: Axis-Aligned Bounding Box (AABB) ou cálculo de distância euclidiana para círculos/projéteis.
3. Gerenciamento estruturado de entidades: Player, Inimigos/Obstáculos, Projéteis e Efeitos Particulados com arrays de vida útil.
4. Suporte nativo a controles de teclado (WASD, setas, espaço) com captura suave de teclas pressionadas (key state dictionary).
5. HUD em Canvas integrado exibindo pontuação, vidas restantes e tela de Game Over com botão de restart.
