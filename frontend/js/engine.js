/**
 * AgentOffice 2D - Canvas 2D Engine
 * Motor de física, renderização pixel art, controle do jogador (WASD), colisão AABB,
 * e máquina de estados visuais para NPCs (Supervisor / Workers).
 */

class OfficeEngine {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext('2d');

    // Dimensões lógicas do escritório
    this.width = 800;
    this.height = 520;
    this.canvas.width = this.width;
    this.canvas.height = this.height;

    // Desabilitar suavização para garantir pixel art nítido
    this.ctx.imageSmoothingEnabled = false;

    // Estado do Jogador
    this.player = {
      x: 400,
      y: 250,
      width: 22,
      height: 26,
      speed: 155, // pixels por segundo
      vx: 0,
      vy: 0,
      facing: 'down',
      walkCycle: 0,
      isMoving: false,
      color: '#38bdf8'
    };

    // Teclas pressionadas
    this.keys = {
      up: false,
      down: false,
      left: false,
      right: false
    };

    // Entidades do mundo
    this.desks = [];
    this.agents = new Map(); // id -> agent object
    this.obstacles = [];

    // Interação
    this.nearestTarget = null;
    this.interactionDistance = 52;

    // Loop de animação
    this.lastTime = performance.now();
    this.steamParticles = [];
    this.spawnParticles = [];
    this.retroNotice = null;
    this.initWorld();
    this.setupInput();
    this.setupWebSocketListeners();
  }

  initWorld() {
    // Definir obstáculos fixos (paredes externas e móveis centrais)
    // Paredes e móveis: [x, y, w, h]
    this.obstacles = [
      // Parede superior (com profundidade 3D)
      { x: 0, y: 0, w: 800, h: 48 },
      // Parede inferior
      { x: 0, y: 504, w: 800, h: 16 },
      // Parede esquerda
      { x: 0, y: 0, w: 24, h: 520 },
      // Parede direita
      { x: 776, y: 0, w: 24, h: 520 },
      // Rack de Servidores (canto superior esquerdo)
      { x: 24, y: 110, w: 36, h: 74, name: "Rack de Servidores" },
      // Bebedouro & Máquina de Café (canto esquerdo central)
      { x: 24, y: 220, w: 40, h: 60, name: "Bebedouro & Café" },
      // Quadro de Tarefas / Whiteboard Kanban (canto direito central)
      { x: 746, y: 210, w: 30, h: 74, name: "Quadro Branco" }
    ];

    // Objetos interativos do mapa (Whiteboard e Rack de Servidores)
    this.interactiveObjects = [
      {
        id: 'whiteboard',
        name: 'Quadro Branco (Kanban)',
        x: 746, y: 210, w: 30, h: 74,
        checkX: 730, checkY: 247,
        label: '[E] Abrir Quadro Kanban (Tarefas)',
        action: () => {
          if (window.officeModals) {
            window.officeModals.showModal('kanbanModal');
          }
        }
      },
      {
        id: 'server_rack',
        name: 'Rack de Servidores (Diagnóstico)',
        x: 24, y: 110, w: 36, h: 74,
        checkX: 75, checkY: 147,
        label: '[E] Diagnóstico do Sistema (Rack)',
        action: () => {
          if (typeof window.openDiagnosticsModal === 'function') {
            window.openDiagnosticsModal();
          } else if (window.officeModals) {
            window.officeModals.showModal('diagnosticsModal');
          }
        }
      }
    ];

    // Inicializar partículas de vapor de café
    for (let i = 0; i < 15; i++) {
      this.steamParticles.push({
        x: 40 + Math.random() * 8,
        y: 235 + Math.random() * 15,
        vy: -0.4 - Math.random() * 0.3,
        alpha: Math.random(),
        size: 1 + Math.random() * 2
      });
    }
  }

  setupInput() {
    window.addEventListener('keydown', (e) => {
      // Ignorar teclas se foco estiver em campos de texto
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
        return;
      }

      if (e.code === 'KeyW' || e.code === 'ArrowUp') this.keys.up = true;
      if (e.code === 'KeyS' || e.code === 'ArrowDown') this.keys.down = true;
      if (e.code === 'KeyA' || e.code === 'ArrowLeft') this.keys.left = true;
      if (e.code === 'KeyD' || e.code === 'ArrowRight') this.keys.right = true;

      if (e.code === 'KeyE') {
        this.triggerInteraction();
      }
    });

    window.addEventListener('keyup', (e) => {
      if (e.code === 'KeyW' || e.code === 'ArrowUp') this.keys.up = false;
      if (e.code === 'KeyS' || e.code === 'ArrowDown') this.keys.down = false;
      if (e.code === 'KeyA' || e.code === 'ArrowLeft') this.keys.left = false;
      if (e.code === 'KeyD' || e.code === 'ArrowRight') this.keys.right = false;
    });

    // Clique do mouse direto em objetos do mapa ou mesas
    this.canvas.addEventListener('click', (e) => {
      const rect = this.canvas.getBoundingClientRect();
      const scaleX = this.canvas.width / rect.width;
      const scaleY = this.canvas.height / rect.height;
      const clickX = (e.clientX - rect.left) * scaleX;
      const clickY = (e.clientY - rect.top) * scaleY;

      // 1. Clique no Quadro Branco (Kanban)
      if (clickX >= 735 && clickX <= 780 && clickY >= 200 && clickY <= 290) {
        if (window.officeModals) {
          window.officeModals.showModal('kanbanModal');
        }
        return;
      }

      // 2. Clique no Rack de Servidores (Diagnóstico)
      if (clickX >= 20 && clickX <= 68 && clickY >= 105 && clickY <= 190) {
        if (typeof window.openDiagnosticsModal === 'function') {
          window.openDiagnosticsModal();
        } else if (window.officeModals) {
          window.officeModals.showModal('diagnosticsModal');
        }
        return;
      }

      // 3. Clique nas Mesas
      for (const desk of this.desks) {
        if (
          clickX >= desk.x - 10 &&
          clickX <= desk.x + desk.width + 10 &&
          clickY >= desk.y - 20 &&
          clickY <= desk.y + desk.height + 15
        ) {
          const agent = this.agents.get(desk.agent_id);
          window.handleDeskInteraction(desk, agent);
          return;
        }
      }
    });
  }

  setWorkspace(workspace) {
    this.desks = workspace.desks || [];

    // Atualizar agentes
    const incomingAgents = new Map();
    (workspace.agents || []).forEach(a => {
      const existing = this.agents.get(a.id);
      const desk = this.desks.find(d => d.id === a.desk_id);
      const defaultX = desk ? desk.seat_x : 400;
      const defaultY = desk ? desk.seat_y : 260;

      incomingAgents.set(a.id, {
        ...a,
        x: existing ? existing.x : defaultX,
        y: existing ? existing.y : defaultY,
        targetX: existing ? existing.targetX : defaultX,
        targetY: existing ? existing.targetY : defaultY,
        walkSpeed: existing ? existing.walkSpeed : 2.5,
        speechBubble: existing ? existing.speechBubble : null,
        bubbleTimer: existing ? existing.bubbleTimer : 0
      });
    });

    this.agents = incomingAgents;
  }

  updateAgentStatus(agentId, newState) {
    const agent = this.agents.get(agentId);
    if (agent) {
      agent.state = newState;
      if (newState === 'reporting') {
        agent.speechBubble = "📄 Relatório entregue!";
        agent.bubbleTimer = 2.0;
      }
    }
  }

  moveAgent(agentId, targetX, targetY, action = "walk", speed = 2.5) {
    const agent = this.agents.get(agentId);
    if (agent) {
      agent.targetX = targetX;
      agent.targetY = targetY;
      agent.walkSpeed = speed;
      agent.state = "walking";
    }
  }

  start() {
    const loop = (currentTime) => {
      const dt = Math.min((currentTime - this.lastTime) / 1000, 0.1);
      this.lastTime = currentTime;

      try {
        this.update(dt);
        this.render();
      } catch (err) {
        console.error('[OfficeEngine] Erro no loop de renderização:', err);
      }

      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  update(dt) {
    // 1. Atualizar velocidade do Jogador
    let dx = 0;
    let dy = 0;
    if (this.keys.up) dy -= 1;
    if (this.keys.down) dy += 1;
    if (this.keys.left) dx -= 1;
    if (this.keys.right) dx += 1;

    // Normalizar vetor diagonal
    if (dx !== 0 && dy !== 0) {
      dx *= 0.7071;
      dy *= 0.7071;
    }

    if (dx !== 0 || dy !== 0) {
      this.player.isMoving = true;
      this.player.walkCycle += dt * 8;
      if (Math.abs(dx) > Math.abs(dy)) {
        this.player.facing = dx > 0 ? 'right' : 'left';
      } else {
        this.player.facing = dy > 0 ? 'down' : 'up';
      }
    } else {
      this.player.isMoving = false;
      this.player.walkCycle = 0;
    }

    // 2. Movimento com resolução AABB separada em X e Y
    const moveDistX = dx * this.player.speed * dt;
    const moveDistY = dy * this.player.speed * dt;

    // Auto-recuperação (unstuck): se o jogador estiver em colisão por qualquer motivo, move para área livre central
    if (this.checkCollision(this.player.x, this.player.y)) {
      this.player.x = 400;
      this.player.y = 250;
    }

    const newX = this.player.x + moveDistX;
    if (!this.checkCollision(newX, this.player.y)) {
      this.player.x = newX;
    }

    const newY = this.player.y + moveDistY;
    if (!this.checkCollision(this.player.x, newY)) {
      this.player.y = newY;
    }

    // 3. Atualizar NPCs (Interpolação de movimento)
    this.agents.forEach(agent => {
      if (agent.targetX !== undefined && agent.targetY !== undefined) {
        const diffX = agent.targetX - agent.x;
        const diffY = agent.targetY - agent.y;
        const dist = Math.hypot(diffX, diffY);

        if (dist > 3) {
          const step = agent.walkSpeed * 70 * dt;
          agent.x += (diffX / dist) * Math.min(step, dist);
          agent.y += (diffY / dist) * Math.min(step, dist);
        } else {
          agent.x = agent.targetX;
          agent.y = agent.targetY;
          if (agent.state === 'walking') {
            agent.state = 'idle';
          }
        }
      }

      // Temporizador de balão
      if (agent.bubbleTimer > 0) {
        agent.bubbleTimer -= dt;
        if (agent.bubbleTimer <= 0) {
          agent.speechBubble = null;
        }
      }

      // Temporizador do ícone flutuante de atividade de arquivo (1.2s)
      if (agent.floatingIcon && agent.floatingIcon.timer > 0) {
        agent.floatingIcon.timer -= dt;
        if (agent.floatingIcon.timer <= 0) {
          agent.floatingIcon = null;
        }
      }
    });

    // 4. Atualizar partículas de vapor do café
    this.steamParticles.forEach(p => {
      p.y += p.vy;
      p.alpha -= 0.012;
      if (p.alpha <= 0) {
        p.x = 38 + Math.random() * 12;
        p.y = 240;
        p.alpha = 0.8;
      }
    });

    // 5. Atualizar partículas retrô de spawn / despawn
    for (let i = this.spawnParticles.length - 1; i >= 0; i--) {
      const p = this.spawnParticles[i];
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.alpha -= dt * 1.3;
      p.size = Math.max(0.5, p.size - dt * 1.5);
      if (p.alpha <= 0) {
        this.spawnParticles.splice(i, 1);
      }
    }

    // 6. Atualizar notificação retrô do rodapé
    if (this.retroNotice && this.retroNotice.timer > 0) {
      this.retroNotice.timer -= dt;
      if (this.retroNotice.timer <= 0) {
        this.retroNotice = null;
      }
    }

    // 7. Detectar proximidade
    this.checkProximity();
  }

  checkCollision(x, y) {
    // Usar apenas a base/pés do personagem para colisão (profundidade 2.5D natural)
    // Isso evita bloqueios indesejados da cabeça/ombros e permite movimentação fluida
    const feetW = 14;
    const feetH = 8;
    const pLeft = x - feetW / 2;
    const pRight = x + feetW / 2;
    const pTop = (y + 11) - feetH / 2;
    const pBottom = (y + 11) + feetH / 2;

    // Obstáculos fixos do mapa
    for (const obs of this.obstacles) {
      if (
        pRight > obs.x &&
        pLeft < obs.x + obs.w &&
        pBottom > obs.y &&
        pTop < obs.y + obs.h
      ) {
        return true;
      }
    }

    // Mesas de escritório
    for (const desk of this.desks) {
      const dLeft = desk.x;
      const dRight = desk.x + desk.width;
      const dTop = desk.y;
      const dBottom = desk.y + desk.height;

      if (
        pRight > dLeft &&
        pLeft < dRight &&
        pBottom > dTop &&
        pTop < dBottom
      ) {
        return true;
      }
    }

    return false;
  }

  checkProximity() {
    let closest = null;
    let minDist = this.interactionDistance;

    // 1. Verificar objetos interativos do mapa (Quadro Branco e Rack de Servidores)
    for (const obj of (this.interactiveObjects || [])) {
      const dist = Math.hypot(this.player.x - obj.checkX, this.player.y - obj.checkY);
      if (dist < minDist) {
        minDist = dist;
        closest = {
          type: 'object',
          object: obj,
          hudX: obj.checkX,
          hudY: obj.checkY - 24,
          label: obj.label,
          dist
        };
      }
    }

    // 2. Verificar mesas dos agentes
    for (const desk of this.desks) {
      const checkX = desk.front_x || (desk.x + desk.width / 2);
      const checkY = desk.front_y || (desk.y + desk.height + 15);
      const dist = Math.hypot(this.player.x - checkX, this.player.y - checkY);

      if (dist < minDist) {
        minDist = dist;
        const agent = this.agents.get(desk.agent_id);
        const label = agent ? `[E] Falar com ${agent.name}` : `[E] Contratar Agente`;
        closest = {
          type: 'desk',
          desk,
          agent,
          hudX: desk.x + desk.width / 2,
          hudY: desk.y - 14,
          label,
          dist
        };
      }
    }

    this.nearestTarget = closest;
  }

  triggerInteraction() {
    if (this.nearestTarget) {
      if (this.nearestTarget.type === 'object' && this.nearestTarget.object.action) {
        this.nearestTarget.object.action();
      } else if (this.nearestTarget.type === 'desk') {
        window.handleDeskInteraction(this.nearestTarget.desk, this.nearestTarget.agent);
      }
    }
  }

  // --- RENDERIZAÇÃO COMPLETA NO CANVAS ---

  render() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);

    // 1. Piso do Escritório
    this.renderFloor(ctx);

    // 2. Paredes e Móveis Decorativos
    this.renderArchitecture(ctx);

    // 3. Mesas e Cadeiras
    this.desks.forEach(desk => this.renderDesk(ctx, desk));

    // 4. NPCs (Agentes de IA)
    this.agents.forEach(agent => this.renderNPC(ctx, agent));

    // 5. Partículas de Spawn Retrô
    if (this.spawnParticles.length > 0) {
      ctx.save();
      this.spawnParticles.forEach(p => {
        ctx.fillStyle = p.color;
        ctx.globalAlpha = Math.max(0, Math.min(1, p.alpha));
        ctx.fillRect(p.x - p.size / 2, p.y - p.size / 2, p.size, p.size);
      });
      ctx.restore();
    }

    // 6. Jogador
    this.renderPlayer(ctx);

    // 7. HUD de Proximidade flutuante
    if (this.nearestTarget) {
      this.renderInteractionHUD(ctx, this.nearestTarget);
    }

    // 8. Notificação Retrô no Rodapé do Escritório
    if (this.retroNotice && this.retroNotice.timer > 0) {
      const alpha = Math.min(1, this.retroNotice.timer / 0.3);
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.fillStyle = 'rgba(15, 23, 42, 0.95)';
      ctx.fillRect(24, 484, 752, 22);
      ctx.strokeStyle = '#06b6d4';
      ctx.lineWidth = 1;
      ctx.strokeRect(24, 484, 752, 22);
      ctx.font = "bold 9px 'Courier New', monospace";
      ctx.fillStyle = '#38bdf8';
      ctx.textAlign = 'left';
      ctx.fillText(`⚡ ${this.retroNotice.text}`, 34, 498);
      ctx.restore();
    }
  }

  renderFloor(ctx) {
    // Fundo base
    ctx.fillStyle = '#111422';
    ctx.fillRect(0, 0, this.width, this.height);

    // Padrão de ladrilhos pixel art
    const tileSize = 32;
    for (let x = 24; x < this.width - 24; x += tileSize) {
      for (let y = 48; y < this.height - 16; y += tileSize) {
        const isAlt = ((x / tileSize) + (y / tileSize)) % 2 === 0;
        ctx.fillStyle = isAlt ? '#151928' : '#191e30';
        ctx.fillRect(x, y, tileSize, tileSize);

        // Grid sutil
        ctx.strokeStyle = '#101320';
        ctx.lineWidth = 1;
        ctx.strokeRect(x, y, tileSize, tileSize);
      }
    }

    // Tapete central do corredor
    ctx.fillStyle = 'rgba(56, 189, 248, 0.04)';
    ctx.fillRect(230, 180, 340, 160);
    ctx.strokeStyle = 'rgba(56, 189, 248, 0.12)';
    ctx.lineWidth = 2;
    ctx.strokeRect(230, 180, 340, 160);
  }

  renderArchitecture(ctx) {
    // Parede Norte (Profundidade com rodapé)
    ctx.fillStyle = '#202538';
    ctx.fillRect(0, 0, this.width, 42);
    ctx.fillStyle = '#2a314a';
    ctx.fillRect(0, 42, this.width, 6); // rodapé iluminado

    // Molduras e decorações na parede norte
    ctx.fillStyle = '#475569';
    ctx.fillRect(180, 12, 40, 24); // Certificado 1
    ctx.fillStyle = '#f59e0b';
    ctx.fillRect(188, 18, 24, 12);

    ctx.fillStyle = '#475569';
    ctx.fillRect(480, 12, 50, 24); // Certificado 2
    ctx.fillStyle = '#10b981';
    ctx.fillRect(488, 18, 34, 12);

    // Letreiro neon "AGENTOFFICE" no topo
    ctx.font = "bold 10px 'Courier New', monospace";
    ctx.fillStyle = '#38bdf8';
    ctx.fillText("⚡ AGENTOFFICE LAB ⚡", 330, 26);

    // Paredes laterais e sul
    ctx.fillStyle = '#181b2a';
    ctx.fillRect(0, 0, 24, this.height);
    ctx.fillRect(this.width - 24, 0, 24, this.height);
    ctx.fillRect(0, this.height - 16, this.width, 16);

    // Rack de Servidores IT (Parede Esquerda: X=24, Y=110, W=36, H=74)
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(24, 110, 36, 74);
    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(24, 110, 36, 74);

    // Gavetas de Servidores (4 unidades de rack com LEDs piscantes)
    const now = performance.now();
    for (let u = 0; u < 4; u++) {
      const slotY = 114 + u * 17;
      ctx.fillStyle = '#1e293b';
      ctx.fillRect(26, slotY, 32, 14);
      ctx.strokeStyle = '#0284c7';
      ctx.lineWidth = 0.5;
      ctx.strokeRect(26, slotY, 32, 14);

      // Grades de ventilação
      ctx.fillStyle = '#0b0f19';
      ctx.fillRect(28, slotY + 3, 14, 8);

      // LEDs piscantes (verde status, ciano tráfego de rede, âmbar atividade)
      const led1On = ((now + u * 180) % 900) < 550;
      const led2On = ((now + u * 250) % 700) < 350;
      const led3On = ((now + u * 320) % 1200) < 400;

      ctx.fillStyle = led1On ? '#10b981' : '#064e3b';
      ctx.fillRect(44, slotY + 4, 3, 3);
      ctx.fillStyle = led2On ? '#38bdf8' : '#0369a1';
      ctx.fillRect(49, slotY + 4, 3, 3);
      ctx.fillStyle = led3On ? '#f59e0b' : '#78350f';
      ctx.fillRect(46, slotY + 8, 4, 2);
    }

    // Identificador Neon do Rack
    ctx.font = "bold 8px 'Courier New', monospace";
    ctx.fillStyle = '#38bdf8';
    ctx.textAlign = 'center';
    ctx.fillText("🖥️ RACK", 42, 105);

    // Bebedouro & Máquina de Café (Parede Esquerda: X=24, Y=220)
    ctx.fillStyle = '#334155';
    ctx.fillRect(24, 220, 36, 56);
    ctx.fillStyle = '#0284c7';
    ctx.fillRect(30, 226, 24, 20); // galão d'água azul
    ctx.fillStyle = '#ef4444';
    ctx.fillRect(36, 252, 6, 6); // torneira quente
    ctx.fillStyle = '#3b82f6';
    ctx.fillRect(44, 252, 6, 6); // torneira fria

    // Vapor de café
    this.steamParticles.forEach(p => {
      ctx.fillStyle = `rgba(255, 255, 255, ${p.alpha})`;
      ctx.fillRect(p.x, p.y, p.size, p.size);
    });

    // Quadro Branco Kanban (Parede Direita: X=746, Y=210, W=30, H=74)
    // Moldura de alumínio
    ctx.fillStyle = '#475569';
    ctx.fillRect(744, 208, 32, 78);
    // Superfície magnética branca
    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(746, 210, 28, 74);
    // Linha divisória de colunas
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(760, 210);
    ctx.lineTo(760, 284);
    ctx.stroke();

    // Post-its coloridos pixel art (Amarelo, Laranja, Azul, Verde, Rosa)
    ctx.fillStyle = '#fef08a';
    ctx.fillRect(748, 214, 10, 8);
    ctx.fillStyle = '#fed7aa';
    ctx.fillRect(748, 226, 10, 8);
    ctx.fillStyle = '#bae6fd';
    ctx.fillRect(762, 214, 10, 8);
    ctx.fillStyle = '#bbf7d0';
    ctx.fillRect(762, 226, 10, 8);
    ctx.fillStyle = '#fbcfe8';
    ctx.fillRect(748, 240, 10, 8);
    ctx.fillStyle = '#e2e8f0';
    ctx.fillRect(762, 240, 10, 8);

    // Canetão magnético na bandeja inferior
    ctx.fillStyle = '#334155';
    ctx.fillRect(746, 284, 28, 3);
    ctx.fillStyle = '#ef4444';
    ctx.fillRect(750, 283, 8, 2);
    ctx.fillStyle = '#2563eb';
    ctx.fillRect(760, 283, 8, 2);

    // Identificador Neon do Kanban
    ctx.font = "bold 8px 'Courier New', monospace";
    ctx.fillStyle = '#38bdf8';
    ctx.textAlign = 'center';
    ctx.fillText("📋 KANBAN", 760, 204);
  }

  renderDesk(ctx, desk) {
    const isOccupied = !!desk.agent_id;
    const isTargeted = this.nearestTarget && this.nearestTarget.desk && this.nearestTarget.desk.id === desk.id;

    // Sombra da mesa
    ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
    ctx.fillRect(desk.x + 3, desk.y + desk.height - 2, desk.width, 8);

    // Tampo da mesa (estilo madeira/ardósia pixel)
    ctx.fillStyle = isTargeted ? '#3b4363' : '#282d44';
    ctx.fillRect(desk.x, desk.y, desk.width, desk.height);

    // Borda da mesa
    ctx.strokeStyle = isTargeted ? '#38bdf8' : '#3e4668';
    ctx.lineWidth = 2;
    ctx.strokeRect(desk.x, desk.y, desk.width, desk.height);

    // Cadeira vazia se não tiver agente sentado
    if (!isOccupied) {
      ctx.fillStyle = '#475569';
      ctx.fillRect(desk.seat_x - 10, desk.seat_y - 10, 20, 18);
      ctx.fillStyle = '#1e293b';
      ctx.fillRect(desk.seat_x - 8, desk.seat_y - 8, 16, 14);
    }

    // Monitor do computador
    const monitorX = desk.x + desk.width / 2 - 14;
    const monitorY = desk.y + 8;
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(monitorX, monitorY, 28, 18);

    // Tela do PC acesa
    ctx.fillStyle = isOccupied ? '#06b6d4' : '#1e293b';
    ctx.fillRect(monitorX + 2, monitorY + 2, 24, 14);

    // Linhas de código animadas na tela do PC
    if (isOccupied) {
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(monitorX + 4, monitorY + 5, 12, 1);
      ctx.fillRect(monitorX + 4, monitorY + 8, 18, 1);
      ctx.fillRect(monitorX + 4, monitorY + 11, 8, 1);
    }

    // Teclado
    ctx.fillStyle = '#64748b';
    ctx.fillRect(monitorX + 2, monitorY + 22, 24, 6);

    // Caneca de café
    ctx.fillStyle = '#f59e0b';
    ctx.fillRect(desk.x + 12, desk.y + 14, 6, 7);

    // Identificador da mesa
    ctx.font = "9px 'Courier New', monospace";
    ctx.fillStyle = isTargeted ? '#38bdf8' : '#94a3b8';
    ctx.textAlign = 'center';
    ctx.fillText(desk.name.split(' ')[0] + ' ' + (desk.name.split(' ')[1] || ''), desk.x + desk.width / 2, desk.y + desk.height + 12);
  }

  renderNPC(ctx, agent) {
    const x = agent.x;
    const y = agent.y;

    // Sombra do NPC
    ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
    ctx.beginPath();
    ctx.ellipse(x, y + 10, 11, 5, 0, 0, Math.PI * 2);
    ctx.fill();

    // Cor baseada no papel
    let roleColor = '#38bdf8';
    let roleBadge = '✦';
    if (agent.role_type === 'supervisor') {
      roleColor = '#f59e0b'; // Dourado
      roleBadge = '👑';
    } else if (agent.role_type === 'worker') {
      roleColor = '#10b981'; // Esmeralda
      roleBadge = '⚙️';
    }

    // Corpo do NPC
    ctx.fillStyle = roleColor;
    ctx.fillRect(x - 7, y - 4, 14, 14);

    // Cabeça do NPC
    ctx.fillStyle = '#fed7aa'; // Tom de pele
    ctx.fillRect(x - 6, y - 16, 12, 12);

    // Cabelo
    ctx.fillStyle = agent.role_type === 'supervisor' ? '#451a03' : '#1e1b4b';
    ctx.fillRect(x - 7, y - 18, 14, 5);

    // Olhos
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(x - 4, y - 11, 2, 2);
    ctx.fillRect(x + 2, y - 11, 2, 2);

    // Indicador de Estado Visual (Aura / Balão de Pensamento / QA / Aprovação / Handoff)
    if (agent.state === 'thinking') {
      // Aura dourada pulsante
      ctx.strokeStyle = 'rgba(245, 158, 11, 0.8)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x, y - 6, 18, 0, Math.PI * 2);
      ctx.stroke();

      // Balão de pensamento
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(x + 10, y - 30, 24, 14);
      ctx.fillStyle = '#0f172a';
      ctx.font = "bold 9px sans-serif";
      ctx.fillText("💭...", x + 13, y - 20);
    } else if (agent.state === 'working') {
      // Efeito de digitação rápida
      ctx.fillStyle = '#10b981';
      ctx.font = "10px sans-serif";
      ctx.fillText("⚡", x + 10, y - 20);
    } else if (agent.state === 'reviewing') {
      // Aura roxa de revisão QA
      ctx.strokeStyle = 'rgba(139, 92, 246, 0.9)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x, y - 6, 18, 0, Math.PI * 2);
      ctx.stroke();

      ctx.fillStyle = '#ffffff';
      ctx.fillRect(x + 10, y - 30, 24, 14);
      ctx.fillStyle = '#0f172a';
      ctx.font = "bold 9px sans-serif";
      ctx.fillText("🔍QA", x + 12, y - 20);
    } else if (agent.state === 'waiting_approval') {
      // Alerta âmbar pulsante de aprovação pendente
      const pulseAlpha = 0.5 + Math.sin(performance.now() / 180) * 0.4;
      ctx.strokeStyle = `rgba(245, 158, 11, ${pulseAlpha})`;
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.arc(x, y - 6, 20, 0, Math.PI * 2);
      ctx.stroke();

      ctx.fillStyle = '#f59e0b';
      ctx.font = "bold 12px sans-serif";
      ctx.fillText("⚠️", x + 10, y - 20);
    } else if (agent.state === 'handoff') {
      // Agente carregando pasta
      ctx.fillStyle = '#f59e0b';
      ctx.fillRect(x + 6, y, 8, 6);
      ctx.strokeStyle = '#78350f';
      ctx.lineWidth = 1;
      ctx.strokeRect(x + 6, y, 8, 6);
    } else if (agent.state === 'reporting' || agent.speechBubble) {
      // Balão de relatório entregue
      const bubbleText = agent.speechBubble || "📄 Relatório!";
      ctx.font = "bold 9px sans-serif";
      const textWidth = ctx.measureText(bubbleText).width;

      ctx.fillStyle = '#ffffff';
      ctx.strokeStyle = '#0f172a';
      ctx.lineWidth = 1;
      ctx.fillRect(x - textWidth / 2 - 4, y - 36, textWidth + 8, 16);
      ctx.strokeRect(x - textWidth / 2 - 4, y - 36, textWidth + 8, 16);

      ctx.fillStyle = '#0f172a';
      ctx.textAlign = 'center';
      ctx.fillText(bubbleText, x, y - 24);
    }

    // Ícone flutuante de atividade de arquivo (fs.activity - 1.2s com animação)
    if (agent.floatingIcon && agent.floatingIcon.timer > 0) {
      const fi = agent.floatingIcon;
      const progress = 1 - (fi.timer / fi.maxTimer);
      const bounce = Math.sin(progress * Math.PI) * 12;
      const iconY = y - 48 - bounce;
      const alpha = fi.timer < 0.3 ? fi.timer / 0.3 : 1.0;

      ctx.save();
      ctx.globalAlpha = Math.max(0, Math.min(1, alpha));

      ctx.font = "16px sans-serif";
      ctx.textAlign = 'center';
      ctx.fillText(fi.icon, x, iconY);

      if (fi.label) {
        ctx.font = "bold 8px 'Courier New', monospace";
        const badgeWidth = ctx.measureText(fi.label).width + 8;
        ctx.fillStyle = 'rgba(15, 23, 42, 0.9)';
        ctx.fillRect(x - badgeWidth / 2, iconY + 3, badgeWidth, 12);
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 1;
        ctx.strokeRect(x - badgeWidth / 2, iconY + 3, badgeWidth, 12);
        ctx.fillStyle = '#38bdf8';
        ctx.fillText(fi.label, x, iconY + 12);
      }
      ctx.restore();
    }

    // Nome e Cargo do Agente acima do avatar
    ctx.font = "bold 9px 'Courier New', monospace";
    ctx.textAlign = 'center';
    ctx.fillStyle = '#ffffff';
    ctx.fillText(`${roleBadge} ${agent.name}`, x, y - 22);

    ctx.font = "8px sans-serif";
    ctx.fillStyle = roleColor;
    ctx.fillText(agent.title, x, y - 14);
  }

  renderPlayer(ctx) {
    const p = this.player;

    // Sombra do jogador
    ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
    ctx.beginPath();
    ctx.ellipse(p.x, p.y + 11, 10, 5, 0, 0, Math.PI * 2);
    ctx.fill();

    // Bobbing de caminhada
    const bob = p.isMoving ? Math.sin(p.walkCycle) * 2 : 0;

    // Corpo (Camisa azul do jogador)
    ctx.fillStyle = '#2563eb';
    ctx.fillRect(p.x - 7, p.y - 4 + bob, 14, 14);

    // Calças
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(p.x - 6, p.y + 10 + bob, 5, 6);
    ctx.fillRect(p.x + 1, p.y + 10 + bob, 5, 6);

    // Cabeça
    ctx.fillStyle = '#ffedd5';
    ctx.fillRect(p.x - 6, p.y - 16 + bob, 12, 12);

    // Cabelo castanho
    ctx.fillStyle = '#78350f';
    ctx.fillRect(p.x - 7, p.y - 18 + bob, 14, 5);

    // Direção dos olhos
    ctx.fillStyle = '#0f172a';
    if (p.facing === 'down') {
      ctx.fillRect(p.x - 4, p.y - 11 + bob, 2, 2);
      ctx.fillRect(p.x + 2, p.y - 11 + bob, 2, 2);
    } else if (p.facing === 'up') {
      // Olhando para cima (traseira do cabelo visível)
      ctx.fillStyle = '#78350f';
      ctx.fillRect(p.x - 6, p.y - 15 + bob, 12, 6);
    } else if (p.facing === 'left') {
      ctx.fillRect(p.x - 5, p.y - 11 + bob, 2, 2);
    } else if (p.facing === 'right') {
      ctx.fillRect(p.x + 3, p.y - 11 + bob, 2, 2);
    }

    // Indicador "VOCÊ" acima do player
    ctx.font = "bold 9px 'Courier New', monospace";
    ctx.fillStyle = '#38bdf8';
    ctx.textAlign = 'center';
    ctx.fillText("▼ VOCÊ", p.x, p.y - 22 + bob);
  }

  renderInteractionHUD(ctx, target) {
    const hudX = target.hudX !== undefined ? target.hudX : (target.desk ? target.desk.x + target.desk.width / 2 : this.player.x);
    const hudY = target.hudY !== undefined ? target.hudY : (target.desk ? target.desk.y - 14 : this.player.y - 20);
    const label = target.label || (target.agent ? `[E] Falar com ${target.agent.name}` : `[E] Contratar Agente`);

    ctx.font = "bold 10px 'Courier New', monospace";
    ctx.textAlign = 'center';
    const textWidth = ctx.measureText(label).width;

    // Fundo do balão de interação
    ctx.fillStyle = 'rgba(15, 23, 42, 0.95)';
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 1.5;
    ctx.fillRect(hudX - textWidth / 2 - 8, hudY - 14, textWidth + 16, 20);
    ctx.strokeRect(hudX - textWidth / 2 - 8, hudY - 14, textWidth + 16, 20);

    // Texto
    ctx.fillStyle = '#38bdf8';
    ctx.fillText(label, hudX, hudY);
  }

  triggerHandoff(fromAgentId, toAgentId, taskTitle = "") {
    const fromAgent = this.agents.get(fromAgentId);
    const toAgent = this.agents.get(toAgentId);
    if (!fromAgent || !toAgent) return;

    const origX = fromAgent.x;
    const origY = fromAgent.y;

    const targetDesk = this.desks.find(d => d.agent_id === toAgentId);
    const targetX = targetDesk ? (targetDesk.front_x || targetDesk.x) : toAgent.x;
    const targetY = targetDesk ? (targetDesk.front_y || targetDesk.y + 20) : toAgent.y;

    fromAgent.state = 'handoff';
    fromAgent.speechBubble = "📁 Passando tarefa...";
    fromAgent.bubbleTimer = 3.5;
    this.moveAgent(fromAgentId, targetX, targetY, "walk", 3.0);

    setTimeout(() => {
      if (this.agents.get(fromAgentId)) {
        fromAgent.speechBubble = "✅ Tarefa entregue!";
        fromAgent.bubbleTimer = 2.0;
        this.moveAgent(fromAgentId, origX, origY, "walk", 3.0);
      }
    }, 2200);
  }

  triggerSpawnEffect(x, y) {
    const colors = ['#38bdf8', '#10b981', '#f59e0b', '#c084fc', '#ffffff', '#ec4899'];
    for (let i = 0; i < 28; i++) {
      const angle = Math.random() * Math.PI * 2;
      const speed = 25 + Math.random() * 85;
      this.spawnParticles.push({
        x: x,
        y: y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - 15,
        alpha: 1.0,
        size: 2 + Math.random() * 3,
        color: colors[Math.floor(Math.random() * colors.length)]
      });
    }
  }

  triggerRetroNotice(text, duration = 2.5) {
    this.retroNotice = {
      text,
      timer: duration,
      maxTimer: duration
    };
  }

  triggerFsActivity(agentId, action, path) {
    const agent = this.agents.get(agentId);
    const isDir = (action || '').includes('dir');
    const icon = isDir ? '📁' : '💾';
    const fileName = (path || '').split('/').pop().split('\\').pop() || 'arquivo';

    if (agent) {
      agent.floatingIcon = {
        icon: icon,
        label: `${action === 'read_file' ? 'Leu' : 'Gravou'} ${fileName}`,
        timer: 1.2,
        maxTimer: 1.2
      };
    }

    const actionDesc = action === 'created_file' ? 'Gravou arquivo' :
                       action === 'created_dir' ? 'Criou pasta' :
                       action === 'read_file' ? 'Leu arquivo' : action;
    this.triggerRetroNotice(`${icon} ${actionDesc}: ${path}`, 2.5);
  }

  setupWebSocketListeners() {
    if (!window.officeSocket) return;

    window.officeSocket.on('agent.spawned', (data) => {
      const agentData = data.agent || data;
      const desk = this.desks.find(d => d.id === agentData.desk_id);
      const posX = desk ? desk.seat_x : (agentData.seat_x || 400);
      const posY = desk ? desk.seat_y : (agentData.seat_y || 260);

      if (desk) {
        desk.agent_id = agentData.id;
      }

      this.agents.set(agentData.id, {
        ...agentData,
        x: posX,
        y: posY,
        targetX: posX,
        targetY: posY,
        walkSpeed: 2.5,
        speechBubble: "⚡ Pronto para a missão!",
        bubbleTimer: 3.0,
        floatingIcon: null
      });

      this.triggerSpawnEffect(posX, posY);
      this.triggerRetroNotice(`🎉 Subagente '${agentData.name}' (${agentData.title}) alocado na ${desk ? desk.name : 'mesa'}!`, 3.5);
    });

    window.officeSocket.on('agent.despawned', (data) => {
      const agentId = data.agent_id || data.id;
      const deskId = data.desk_id;
      const agent = this.agents.get(agentId);
      const desk = deskId ? this.desks.find(d => d.id === deskId) : (agent ? this.desks.find(d => d.agent_id === agentId) : null);

      if (agent) {
        this.triggerSpawnEffect(agent.x, agent.y);
        this.agents.delete(agentId);
      }
      if (desk) {
        desk.agent_id = null;
      }

      this.triggerRetroNotice(`👋 Agente concluiu a missão e liberou a mesa.`, 2.5);
    });

    window.officeSocket.on('fs.activity', (data) => {
      this.triggerFsActivity(data.agent_id, data.action, data.path);
    });
  }
}

