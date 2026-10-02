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
    // Setorização por Departamentos (Salas)
    this.rooms = {
      room_sudo: {
        id: 'room_sudo',
        name: 'SALA DA DIRETORIA (SUDO)',
        icon: '👑',
        themeColor: '#f59e0b',
        bgColor: '#141728',
        bounds: { x: 24, y: 48, w: 372, h: 170 },
        door: { x: 200, y: 218, w: 50 },
        insideWaypoint: { x: 200, y: 175 },
        hallwayWaypoint: { x: 200, y: 257 }
      },
      room_sec: {
        id: 'room_sec',
        name: 'SQUAD SEGURANÇA (SEC)',
        icon: '🛡️',
        themeColor: '#a855f7',
        bgColor: '#18142b',
        bounds: { x: 404, y: 48, w: 372, h: 170 },
        door: { x: 600, y: 218, w: 50 },
        insideWaypoint: { x: 600, y: 175 },
        hallwayWaypoint: { x: 600, y: 257 }
      },
      room_dev: {
        id: 'room_dev',
        name: 'SQUAD ENGENHARIA (DEV)',
        icon: '⚙️',
        themeColor: '#10b981',
        bgColor: '#101a1d',
        bounds: { x: 24, y: 298, w: 372, h: 206 },
        door: { x: 200, y: 292, w: 50 },
        insideWaypoint: { x: 200, y: 335 },
        hallwayWaypoint: { x: 200, y: 257 }
      },
      room_doc: {
        id: 'room_doc',
        name: 'SQUAD DOCUMENTAÇÃO & QA',
        icon: '📝',
        themeColor: '#38bdf8',
        bgColor: '#111726',
        bounds: { x: 404, y: 298, w: 372, h: 206 },
        door: { x: 600, y: 292, w: 50 },
        insideWaypoint: { x: 600, y: 335 },
        hallwayWaypoint: { x: 600, y: 257 }
      }
    };

    // Obstáculos fixos do mapa (Paredes externas e divisórias de salas com portas)
    this.obstacles = [
      // Paredes Externas
      { x: 0, y: 0, w: 800, h: 48 },
      { x: 0, y: 504, w: 800, h: 16 },
      { x: 0, y: 0, w: 24, h: 520 },
      { x: 776, y: 0, w: 24, h: 520 },

      // Divisória Central Vertical (Norte e Sul)
      { x: 396, y: 48, w: 8, h: 170 },
      { x: 396, y: 298, w: 8, h: 206 },

      // Paredes Norte do Corredor (Portas abertas em 175..225 e 575..625)
      { x: 24, y: 218, w: 151, h: 6 },
      { x: 225, y: 218, w: 171, h: 6 },
      { x: 404, y: 218, w: 171, h: 6 },
      { x: 625, y: 218, w: 151, h: 6 },

      // Paredes Sul do Corredor (Portas abertas em 175..225 e 575..625)
      { x: 24, y: 292, w: 151, h: 6 },
      { x: 225, y: 292, w: 171, h: 6 },
      { x: 404, y: 292, w: 171, h: 6 },
      { x: 625, y: 292, w: 151, h: 6 }
    ];

    // Objetos interativos do mapa (Whiteboard, Rack e Bebedouro no corredor central)
    this.interactiveObjects = [
      {
        id: 'whiteboard',
        name: 'Quadro Branco (Kanban)',
        x: 746, y: 232, w: 26, h: 52,
        checkX: 725, checkY: 257,
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
        x: 28, y: 232, w: 32, h: 52,
        checkX: 75, checkY: 257,
        label: '[E] Diagnóstico do Sistema (Rack)',
        action: () => {
          if (typeof window.openDiagnosticsModal === 'function') {
            window.openDiagnosticsModal();
          } else if (window.officeModals) {
            window.officeModals.showModal('diagnosticsModal');
          }
        }
      },
      {
        id: 'coffee_cooler',
        name: 'Bebedouro & Café Central',
        x: 382, y: 232, w: 34, h: 52,
        checkX: 382, checkY: 257,
        label: '[E] Fazer Pausa para o Café ☕',
        action: () => {
          this.triggerRetroNotice('☕ Você tomou um café quentinho no corredor central!', 2.5);
        }
      }
    ];

    // Inicializar partículas de vapor de café no corredor
    for (let i = 0; i < 15; i++) {
      this.steamParticles.push({
        x: 396 + Math.random() * 8,
        y: 245 + Math.random() * 10,
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

      // 2. Clique no Rack de Servidores (Diagnóstico no Corredor)
      if (clickX >= 20 && clickX <= 68 && clickY >= 210 && clickY <= 290) {
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
        bubbleTimer: existing ? existing.bubbleTimer : 0,
        waypointQueue: existing && existing.waypointQueue ? existing.waypointQueue : [],
        onWaypointComplete: existing && existing.onWaypointComplete ? existing.onWaypointComplete : null
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

  // --- NAVEGAÇÃO ENTRE SALAS & WAYPOINTS ---

  getAreaForPoint(x, y) {
    if (y < 220) {
      return x < 400 ? 'room_sudo' : 'room_sec';
    } else if (y > 290) {
      return x < 400 ? 'room_dev' : 'room_doc';
    } else {
      return 'hallway';
    }
  }

  calculatePathBetweenPoints(fromX, fromY, toX, toY) {
    const fromArea = this.getAreaForPoint(fromX, fromY);
    const toArea = this.getAreaForPoint(toX, toY);

    if (fromArea === toArea) {
      return [{ x: toX, y: toY }];
    }

    const waypoints = [];

    // 1. Sair da sala de origem para o corredor
    if (fromArea !== 'hallway' && this.rooms[fromArea]) {
      const room = this.rooms[fromArea];
      waypoints.push({ ...room.insideWaypoint });
      waypoints.push({ ...room.hallwayWaypoint });
    }

    // 2. Se cruzar oeste (x<=400) para leste (x>400) ou vice-versa no corredor
    const fromWest = fromX <= 400;
    const toWest = toX <= 400;
    if (fromWest !== toWest) {
      waypoints.push({ x: 400, y: 257 });
    }

    // 3. Entrar na sala de destino a partir do corredor
    if (toArea !== 'hallway' && this.rooms[toArea]) {
      const room = this.rooms[toArea];
      waypoints.push({ ...room.hallwayWaypoint });
      waypoints.push({ ...room.insideWaypoint });
    }

    // 4. Ponto final de destino
    waypoints.push({ x: toX, y: toY });
    return waypoints;
  }

  queueAgentWaypoints(agentId, waypoints, speed = 2.8, onComplete = null) {
    const agent = this.agents.get(agentId);
    if (!agent || !waypoints || waypoints.length === 0) {
      if (onComplete) onComplete();
      return;
    }

    agent.waypointQueue = [...waypoints];
    agent.walkSpeed = speed;
    agent.state = 'walking';
    agent.onWaypointComplete = onComplete;

    const first = agent.waypointQueue.shift();
    agent.targetX = first.x;
    agent.targetY = first.y;
  }

  handleCrossRoomMove(data) {
    const { agent_id, from_room_id, to_room_id, target_desk_id, ticket_id, service_label } = data;
    const agent = this.agents.get(agent_id);
    if (!agent) return;

    // Posição de origem (mesa do agente)
    const homeDesk = this.desks.find(d => d.id === agent.desk_id) || { seat_x: agent.x, seat_y: agent.y };
    const homeX = homeDesk.seat_x;
    const homeY = homeDesk.seat_y;

    // Ponto de destino na sala de destino (em frente à mesa do líder ou centro da sala)
    const targetDesk = this.desks.find(d => d.id === target_desk_id || (d.room_id === to_room_id));
    let targetX = 600, targetY = 150;
    if (targetDesk) {
      targetX = targetDesk.front_x || (targetDesk.x + targetDesk.width / 2);
      targetY = targetDesk.front_y || (targetDesk.y + targetDesk.height + 15);
    } else if (this.rooms[to_room_id]) {
      targetX = this.rooms[to_room_id].insideWaypoint.x;
      targetY = this.rooms[to_room_id].insideWaypoint.y;
    }

    // Calcular caminho de ida
    const forwardPath = this.calculatePathBetweenPoints(agent.x, agent.y, targetX, targetY);

    this.triggerRetroNotice(`🚶 ${agent.name} transitando entre salas: '${service_label || 'Demanda Inter-Squad'}'...`, 3.5);
    agent.speechBubble = "📁 Levando demanda...";
    agent.bubbleTimer = 4.5;

    this.queueAgentWaypoints(agent_id, forwardPath, 2.8, () => {
      // Chegou na frente da mesa do líder parceiro
      agent.speechBubble = "🤝 Inter-Squad Ticket";
      agent.bubbleTimer = 4.0;
      agent.state = 'working';

      // Disparar efeito visual na sala parceira
      this.triggerSpawnEffect(targetX, targetY);

      // Aguardar diálogo antes de retornar à mesa de origem
      setTimeout(() => {
        if (!this.agents.get(agent_id)) return;
        agent.speechBubble = "✅ Alinhado! Retornando...";
        agent.bubbleTimer = 2.5;

        // Caminho de volta
        const returnPath = this.calculatePathBetweenPoints(agent.x, agent.y, homeX, homeY);
        this.queueAgentWaypoints(agent_id, returnPath, 2.8, () => {
          agent.state = 'idle';
          agent.speechBubble = "💻 Posto reassumido";
          agent.bubbleTimer = 2.0;
        });
      }, 2500);
    });
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

    // 3. Atualizar NPCs (Interpolação de movimento e fila de Waypoints)
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

          // Se tem mais nós na fila de waypoints
          if (agent.waypointQueue && agent.waypointQueue.length > 0) {
            const nextNode = agent.waypointQueue.shift();
            agent.targetX = nextNode.x;
            agent.targetY = nextNode.y;
          } else {
            if (agent.state === 'walking') {
              agent.state = 'idle';
            }
            if (typeof agent.onWaypointComplete === 'function') {
              const cb = agent.onWaypointComplete;
              agent.onWaypointComplete = null;
              cb();
            }
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
    // 1. Fundo base
    ctx.fillStyle = '#111422';
    ctx.fillRect(0, 0, this.width, this.height);

    // 2. Cores temáticas de fundo de cada sala/departamento
    if (this.rooms) {
      Object.values(this.rooms).forEach(room => {
        ctx.fillStyle = room.bgColor || '#151928';
        ctx.fillRect(room.bounds.x, room.bounds.y, room.bounds.w, room.bounds.h);
      });
    }

    // 3. Padrão de ladrilhos pixel art sutil
    const tileSize = 32;
    for (let x = 24; x < this.width - 24; x += tileSize) {
      for (let y = 48; y < this.height - 16; y += tileSize) {
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.025)';
        ctx.lineWidth = 1;
        ctx.strokeRect(x, y, tileSize, tileSize);
      }
    }

    // 4. Tapete executivo de luxo na Sala da Diretoria (Executive Suite)
    ctx.fillStyle = 'rgba(180, 83, 9, 0.14)';
    ctx.fillRect(50, 65, 320, 138);
    ctx.strokeStyle = 'rgba(245, 158, 11, 0.5)';
    ctx.lineWidth = 2;
    ctx.strokeRect(50, 65, 320, 138);
    // Borda interna dourada do tapete
    ctx.strokeStyle = 'rgba(245, 158, 11, 0.2)';
    ctx.lineWidth = 1;
    ctx.strokeRect(56, 71, 308, 126);

    // 5. Passadeira / Tapete corredor central
    ctx.fillStyle = 'rgba(14, 165, 233, 0.07)';
    ctx.fillRect(24, 230, 752, 56);
    ctx.strokeStyle = 'rgba(56, 189, 248, 0.25)';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(24, 230, 752, 56);

    // 6. Soleiras/Tapetes de entrada nas 4 portas das salas
    const doorMats = [
      { x: 175, y: 214, w: 50, h: 14, color: '#f59e0b' }, // Porta Sudo
      { x: 575, y: 214, w: 50, h: 14, color: '#a855f7' }, // Porta Sec
      { x: 175, y: 288, w: 50, h: 14, color: '#10b981' }, // Porta Dev
      { x: 575, y: 288, w: 50, h: 14, color: '#38bdf8' }  // Porta Doc
    ];
    doorMats.forEach(dm => {
      ctx.fillStyle = 'rgba(15, 23, 42, 0.8)';
      ctx.fillRect(dm.x, dm.y, dm.w, dm.h);
      ctx.strokeStyle = dm.color;
      ctx.lineWidth = 1;
      ctx.strokeRect(dm.x, dm.y, dm.w, dm.h);
    });
  }

  renderArchitecture(ctx) {
    // 1. Parede Norte Principal (com profundidade e iluminação)
    ctx.fillStyle = '#202538';
    ctx.fillRect(0, 0, this.width, 42);
    ctx.fillStyle = '#2a314a';
    ctx.fillRect(0, 42, this.width, 6); // rodapé iluminado

    // 2. Molduras decorativas na parede norte
    ctx.fillStyle = '#475569';
    ctx.fillRect(50, 12, 36, 24);
    ctx.fillStyle = '#f59e0b';
    ctx.fillRect(56, 18, 24, 12); // Quadro executivo

    ctx.fillStyle = '#475569';
    ctx.fillRect(714, 12, 36, 24);
    ctx.fillStyle = '#a855f7';
    ctx.fillRect(720, 18, 24, 12); // Certificado ISO Sec

    // 3. Paredes Externas (Leste, Oeste e Sul)
    ctx.fillStyle = '#181b2a';
    ctx.fillRect(0, 0, 24, this.height);
    ctx.fillRect(this.width - 24, 0, 24, this.height);
    ctx.fillRect(0, this.height - 16, this.width, 16);

    // 4. Divisórias de Paredes e Portas dos Departamentos
    this.obstacles.forEach(obs => {
      // Pular paredes externas já desenhadas
      if (obs.x === 0 || obs.w === 800 || obs.x === 776) return;

      // Paredes divisórias internas com cor solida e topo destacado
      ctx.fillStyle = '#22283d';
      ctx.fillRect(obs.x, obs.y, obs.w, obs.h);
      ctx.strokeStyle = '#384263';
      ctx.lineWidth = 1;
      ctx.strokeRect(obs.x, obs.y, obs.w, obs.h);
    });

    // 5. Batentes de Porta das Salas (Pilares luminosos)
    const doorPosts = [
      { x: 173, y: 216 }, { x: 225, y: 216 }, // Porta Sudo
      { x: 573, y: 216 }, { x: 625, y: 216 }, // Porta Sec
      { x: 173, y: 290 }, { x: 225, y: 290 }, // Porta Dev
      { x: 573, y: 290 }, { x: 625, y: 290 }  // Porta Doc
    ];
    doorPosts.forEach(dp => {
      ctx.fillStyle = '#64748b';
      ctx.fillRect(dp.x, dp.y, 4, 8);
      ctx.fillStyle = '#38bdf8';
      ctx.fillRect(dp.x + 1, dp.y + 1, 2, 6);
    });

    // 6. Placas Neon dos Departamentos (Letreiros Luminosos)
    const departmentPlaques = [
      { text: "👑 SALA DA DIRETORIA (SUDO)", x: 200, y: 36, color: "#f59e0b", bg: "rgba(245, 158, 11, 0.15)" },
      { text: "🛡️ SQUAD SEGURANÇA (SEC)", x: 600, y: 36, color: "#c084fc", bg: "rgba(168, 85, 247, 0.15)" },
      { text: "⚙️ SQUAD ENGENHARIA (DEV)", x: 200, y: 308, color: "#34d399", bg: "rgba(16, 185, 129, 0.15)" },
      { text: "📝 SQUAD DOCUMENTAÇÃO & QA", x: 600, y: 308, color: "#38bdf8", bg: "rgba(56, 189, 248, 0.15)" }
    ];

    departmentPlaques.forEach(pl => {
      ctx.font = "bold 9px 'Courier New', monospace";
      ctx.textAlign = 'center';
      const textW = ctx.measureText(pl.text).width;

      ctx.fillStyle = 'rgba(15, 23, 42, 0.9)';
      ctx.fillRect(pl.x - textW / 2 - 8, pl.y - 10, textW + 16, 14);
      ctx.fillStyle = pl.bg;
      ctx.fillRect(pl.x - textW / 2 - 8, pl.y - 10, textW + 16, 14);
      ctx.strokeStyle = pl.color;
      ctx.lineWidth = 1;
      ctx.strokeRect(pl.x - textW / 2 - 8, pl.y - 10, textW + 16, 14);

      ctx.fillStyle = pl.color;
      ctx.fillText(pl.text, pl.x, pl.y);
    });

    // 7. Rack de Servidores IT (Corredor Central: X=26, Y=232, W=32, h=52)
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(26, 232, 32, 52);
    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(26, 232, 32, 52);

    // Gavetas de Servidores com LEDs piscantes
    const now = performance.now();
    for (let u = 0; u < 3; u++) {
      const slotY = 236 + u * 15;
      ctx.fillStyle = '#1e293b';
      ctx.fillRect(28, slotY, 28, 12);
      ctx.strokeStyle = '#0284c7';
      ctx.lineWidth = 0.5;
      ctx.strokeRect(28, slotY, 28, 12);

      // LEDs
      const led1On = ((now + u * 180) % 900) < 550;
      const led2On = ((now + u * 250) % 700) < 350;
      ctx.fillStyle = led1On ? '#10b981' : '#064e3b';
      ctx.fillRect(44, slotY + 4, 3, 3);
      ctx.fillStyle = led2On ? '#38bdf8' : '#0369a1';
      ctx.fillRect(49, slotY + 4, 3, 3);
    }

    ctx.font = "bold 8px 'Courier New', monospace";
    ctx.fillStyle = '#38bdf8';
    ctx.textAlign = 'center';
    ctx.fillText("🖥️ RACK", 42, 226);

    // 8. Bebedouro & Café (Corredor Central: X=382, Y=232, W=34, H=52)
    ctx.fillStyle = '#334155';
    ctx.fillRect(382, 232, 34, 52);
    ctx.fillStyle = '#0284c7';
    ctx.fillRect(388, 236, 22, 18); // galão d'água azul
    ctx.fillStyle = '#ef4444';
    ctx.fillRect(393, 258, 5, 5); // torneira quente
    ctx.fillStyle = '#3b82f6';
    ctx.fillRect(401, 258, 5, 5); // torneira fria

    // Vapor de café flutuante
    this.steamParticles.forEach(p => {
      ctx.fillStyle = `rgba(255, 255, 255, ${p.alpha})`;
      ctx.fillRect(p.x, p.y, p.size, p.size);
    });

    // 9. Quadro Branco Kanban (Corredor Central: X=746, Y=232, W=26, H=52)
    ctx.fillStyle = '#475569';
    ctx.fillRect(744, 230, 28, 56);
    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(746, 232, 24, 52);

    // Post-its pixel art no Kanban
    ctx.fillStyle = '#fef08a';
    ctx.fillRect(748, 236, 8, 7);
    ctx.fillStyle = '#fed7aa';
    ctx.fillRect(748, 246, 8, 7);
    ctx.fillStyle = '#bae6fd';
    ctx.fillRect(759, 236, 8, 7);
    ctx.fillStyle = '#bbf7d0';
    ctx.fillRect(759, 246, 8, 7);

    ctx.font = "bold 8px 'Courier New', monospace";
    ctx.fillStyle = '#38bdf8';
    ctx.textAlign = 'center';
    ctx.fillText("📋 KANBAN", 758, 226);
  }

  renderDesk(ctx, desk) {
    const isOccupied = !!desk.agent_id;
    const isTargeted = this.nearestTarget && this.nearestTarget.desk && this.nearestTarget.desk.id === desk.id;
    const isSudoDesk = desk.id === 'desk-sudo' || desk.room_id === 'room_sudo';

    // 1. Sombra da mesa
    ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
    ctx.fillRect(desk.x + 3, desk.y + desk.height - 2, desk.width, 8);

    // 2. Tampo da mesa (Mogno executivo para Sudo, padrão para outras)
    let deskBg = isTargeted ? '#3b4363' : '#282d44';
    let deskBorder = isTargeted ? '#38bdf8' : '#3e4668';

    if (isSudoDesk) {
      deskBg = isTargeted ? '#4d261e' : '#351913';
      deskBorder = isTargeted ? '#f59e0b' : '#92400e';
    }

    ctx.fillStyle = deskBg;
    ctx.fillRect(desk.x, desk.y, desk.width, desk.height);
    ctx.strokeStyle = deskBorder;
    ctx.lineWidth = isSudoDesk ? 2.5 : 2;
    ctx.strokeRect(desk.x, desk.y, desk.width, desk.height);

    // Detalhe de couro na mesa executiva da Diretoria
    if (isSudoDesk) {
      ctx.fillStyle = '#1c1917';
      ctx.fillRect(desk.x + 12, desk.y + 6, desk.width - 24, desk.height - 12);
      ctx.strokeStyle = '#d97706';
      ctx.lineWidth = 1;
      ctx.strokeRect(desk.x + 12, desk.y + 6, desk.width - 24, desk.height - 12);
    }

    // 3. Cadeira vazia se não tiver agente sentado
    if (!isOccupied) {
      ctx.fillStyle = isSudoDesk ? '#78350f' : '#475569';
      ctx.fillRect(desk.seat_x - 10, desk.seat_y - 10, 20, 18);
      ctx.fillStyle = isSudoDesk ? '#451a03' : '#1e293b';
      ctx.fillRect(desk.seat_x - 8, desk.seat_y - 8, 16, 14);
    }

    // 4. Monitor do computador (duplo para Diretoria, temático por sala)
    const monitorX = desk.x + desk.width / 2 - 14;
    const monitorY = desk.y + 7;
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(monitorX, monitorY, 28, 18);

    // Cor da tela conforme sala/departamento
    let screenGlow = '#06b6d4';
    if (desk.room_id === 'room_sudo') screenGlow = '#f59e0b';
    else if (desk.room_id === 'room_sec') screenGlow = '#c084fc';
    else if (desk.room_id === 'room_dev') screenGlow = '#10b981';
    else if (desk.room_id === 'room_doc') screenGlow = '#38bdf8';

    ctx.fillStyle = isOccupied ? screenGlow : '#1e293b';
    ctx.fillRect(monitorX + 2, monitorY + 2, 24, 14);

    // Linhas de dados animadas na tela
    if (isOccupied) {
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(monitorX + 4, monitorY + 5, 12, 1);
      ctx.fillRect(monitorX + 4, monitorY + 8, 18, 1);
      ctx.fillRect(monitorX + 4, monitorY + 11, 8, 1);
    }

    // 5. Teclado
    ctx.fillStyle = '#64748b';
    ctx.fillRect(monitorX + 2, monitorY + 22, 24, 6);

    // 6. Caneca de café (dourada para diretoria)
    ctx.fillStyle = isSudoDesk ? '#f59e0b' : '#38bdf8';
    ctx.fillRect(desk.x + 8, desk.y + 12, 6, 7);

    // 7. Plaqueta / Nome da Mesa
    ctx.font = "9px 'Courier New', monospace";
    ctx.fillStyle = isTargeted ? '#38bdf8' : (isSudoDesk ? '#f59e0b' : '#94a3b8');
    ctx.textAlign = 'center';
    const label = isSudoDesk ? '👑 Mesa da Diretoria' : (desk.name || 'Mesa');
    ctx.fillText(label, desk.x + desk.width / 2, desk.y + desk.height + 12);
  }

  renderNPC(ctx, agent) {
    const x = agent.x;
    const y = agent.y;

    // Sombra do NPC
    ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
    ctx.beginPath();
    ctx.ellipse(x, y + 10, 11, 5, 0, 0, Math.PI * 2);
    ctx.fill();

    // Identificação de Hierarquia / Tier
    const isSudo = agent.tier === 'sudo' || agent.id === 'agent-sudo' || agent.role_type === 'sudo';
    const isLeader = agent.tier === 'squad_leader' || agent.role_type === 'supervisor';
    const isSubagent = agent.tier === 'subagent' || agent.is_temporary;

    let roleColor = '#38bdf8';
    let roleBadge = '⚙️';
    let roleTitle = agent.title || 'Especialista';

    if (isSudo) {
      roleColor = '#f59e0b'; // Ouro executivo
      roleBadge = '👑';
    } else if (isLeader) {
      roleColor = '#a855f7'; // Roxo liderança
      roleBadge = '⭐';
    } else if (isSubagent) {
      roleColor = '#06b6d4'; // Ciano subagente
      roleBadge = '⚡';
    }

    // Aura especial do Sudo Agent (Gold Halo permanente e pulsante)
    if (isSudo) {
      const auraPulse = 0.4 + Math.sin(performance.now() / 250) * 0.25;
      ctx.strokeStyle = `rgba(245, 158, 11, ${auraPulse})`;
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.arc(x, y - 6, 20, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Corpo do NPC
    ctx.fillStyle = isSudo ? '#0f172a' : roleColor;
    ctx.fillRect(x - 7, y - 4, 14, 14);

    // Gravata executiva no Sudo Agent
    if (isSudo) {
      ctx.fillStyle = '#ef4444'; // Gravata vermelha executiva
      ctx.fillRect(x - 1, y - 2, 2, 8);
    }

    // Cabeça do NPC
    ctx.fillStyle = '#fed7aa'; // Tom de pele
    ctx.fillRect(x - 6, y - 16, 12, 12);

    // Cabelo
    ctx.fillStyle = isSudo ? '#1c1917' : (isLeader ? '#451a03' : '#1e1b4b');
    ctx.fillRect(x - 7, y - 18, 14, 5);

    // Olhos
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(x - 4, y - 11, 2, 2);
    ctx.fillRect(x + 2, y - 11, 2, 2);

    // Estados Visuais (Pensando, Trabalhando, Diálogo Inter-Squad, etc.)
    if (agent.state === 'thinking') {
      ctx.strokeStyle = 'rgba(245, 158, 11, 0.8)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x, y - 6, 18, 0, Math.PI * 2);
      ctx.stroke();

      ctx.fillStyle = '#ffffff';
      ctx.fillRect(x + 10, y - 30, 24, 14);
      ctx.fillStyle = '#0f172a';
      ctx.font = "bold 9px sans-serif";
      ctx.fillText("💭...", x + 13, y - 20);
    } else if (agent.state === 'working') {
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
    }

    // Balão de Diálogo e Relatórios / Tickets
    if (agent.speechBubble) {
      const bubbleText = agent.speechBubble;
      ctx.font = "bold 9px 'Courier New', monospace";
      const textWidth = ctx.measureText(bubbleText).width;

      ctx.fillStyle = 'rgba(15, 23, 42, 0.95)';
      ctx.strokeStyle = isSudo ? '#f59e0b' : (bubbleText.includes('🤝') ? '#10b981' : '#38bdf8');
      ctx.lineWidth = 1.5;
      ctx.fillRect(x - textWidth / 2 - 6, y - 38, textWidth + 12, 18);
      ctx.strokeRect(x - textWidth / 2 - 6, y - 38, textWidth + 12, 18);

      ctx.fillStyle = '#ffffff';
      ctx.textAlign = 'center';
      ctx.fillText(bubbleText, x, y - 26);
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
    ctx.fillStyle = isSudo ? '#f59e0b' : '#ffffff';
    ctx.fillText(`${roleBadge} ${agent.name}`, x, y - 20);

    ctx.font = "8px sans-serif";
    ctx.fillStyle = roleColor;
    ctx.fillText(roleTitle, x, y - 12);
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

    // Eventos da Arquitetura Multinível (Etapa 7: Sudo Agent & Inter-Squad)
    window.officeSocket.on('squad.dispatched', (data) => {
      this.triggerRetroNotice(`👑 Sudo despachou: "${data.epic_title}" para ${data.squad_name || data.squad_id}!`, 4.0);
      const sudoAgent = Array.from(this.agents.values()).find(a => a.tier === 'sudo' || a.id === data.sudo_agent_id);
      if (sudoAgent) {
        sudoAgent.speechBubble = "👑 Épico Despachado!";
        sudoAgent.bubbleTimer = 3.0;
        sudoAgent.state = 'working';
      }
      if (data.leader_id) {
        const leader = this.agents.get(data.leader_id);
        if (leader) {
          leader.speechBubble = `⚡ Épico recebido: ${data.epic_title}`;
          leader.bubbleTimer = 3.5;
          leader.state = 'working';
        }
      }
    });

    window.officeSocket.on('agent.cross_room_move', (data) => {
      this.handleCrossRoomMove(data);
    });

    window.officeSocket.on('squad.cross_request', (data) => {
      const ticket = data.ticket_data || data;
      this.triggerRetroNotice(`🤝 Ticket Inter-Squad aberto: ${ticket.from_squad_id} ➔ ${ticket.to_squad_id}!`, 4.0);
      if (data.to_leader_id) {
        const toLeader = this.agents.get(data.to_leader_id);
        if (toLeader) {
          toLeader.speechBubble = "🛡️ Analisando Ticket...";
          toLeader.bubbleTimer = 3.5;
          toLeader.state = 'reviewing';
        }
      }
    });

    window.officeSocket.on('squad.ticket_resolved', (data) => {
      const ticket = data.ticket_data || data;
      this.triggerRetroNotice(`✅ Ticket Inter-Squad resolvido e entregue com sucesso!`, 3.5);
      const reqLeader = Array.from(this.agents.values()).find(a => a.id === ticket.requesting_leader_id);
      if (reqLeader) {
        reqLeader.speechBubble = "✅ Parecer Técnico Recebido!";
        reqLeader.bubbleTimer = 3.0;
      }
    });

    window.officeSocket.on('sudo.final_delivery', (data) => {
      this.triggerRetroNotice(`🏆 Diretoria: Meta Macro consolidada e entregue com sucesso!`, 5.0);
      const sudoAgent = Array.from(this.agents.values()).find(a => a.tier === 'sudo' || a.id === data.sudo_agent_id);
      if (sudoAgent) {
        sudoAgent.speechBubble = "🏆 Meta Macro Concluída!";
        sudoAgent.bubbleTimer = 4.5;
        this.triggerSpawnEffect(sudoAgent.x, sudoAgent.y);
      }
      if (window.officeUI && typeof window.officeUI.handleSudoDelivery === 'function') {
        window.officeUI.handleSudoDelivery(data);
      }
    });
  }
}

