/**
 * AgentOffice 2D - UI Manager
 * Gerencia formulários CRUD de agentes com suporte a papéis hierárquicos,
 * janela de chat com streaming em tempo real e painel de atividades do escritório.
 */

class OfficeUI {
  constructor() {
    this.currentWorkspace = null;
    this.activeChatAgent = null;
    this.selectedDeskForCreate = null;
    this.editingAgentId = null;

    this.cacheElements();
    this.setupEvents();
    this.setupSocketListeners();
  }

  cacheElements() {
    // Modais
    this.agentModal = document.getElementById('agentModal');
    this.agentModalTitle = document.getElementById('agentModalTitle');
    this.agentForm = document.getElementById('agentForm');
    this.agentNameInput = document.getElementById('agentNameInput');
    this.agentTitleInput = document.getElementById('agentTitleInput');
    this.agentAvatarSelect = document.getElementById('agentAvatarSelect');
    this.agentRoleSelect = document.getElementById('agentRoleSelect');
    this.supervisorGroup = document.getElementById('supervisorGroup');
    this.agentSupervisorSelect = document.getElementById('agentSupervisorSelect');
    this.agentDeskSelect = document.getElementById('agentDeskSelect');
    this.agentPromptInput = document.getElementById('agentPromptInput');
    this.agentModelInput = document.getElementById('agentModelInput');
    this.deleteAgentBtn = document.getElementById('deleteAgentBtn');
    this.closeAgentModalBtn = document.getElementById('closeAgentModalBtn');

    // Chat Drawer / Modal
    this.chatDrawer = document.getElementById('chatDrawer');
    this.chatAgentName = document.getElementById('chatAgentName');
    this.chatAgentRole = document.getElementById('chatAgentRole');
    this.chatMessages = document.getElementById('chatMessages');
    this.chatInput = document.getElementById('chatInput');
    this.sendChatBtn = document.getElementById('sendChatBtn');
    this.closeChatBtn = document.getElementById('closeChatBtn');
    this.editCurrentAgentBtn = document.getElementById('editCurrentAgentBtn');

    // Activity Log
    this.activityFeed = document.getElementById('activityFeed');
    this.clearLogsBtn = document.getElementById('clearLogsBtn');

    // Subagent Mission Card & Dismissal
    this.subagentMissionCard = document.getElementById('subagentMissionCard');
    this.toggleMissionBtn = document.getElementById('toggleMissionBtn');
    this.missionBody = document.getElementById('missionBody');
    this.missionWhatTask = document.getElementById('missionWhatTask');
    this.missionWhatOutOfScope = document.getElementById('missionWhatOutOfScope');
    this.missionWhenTriggers = document.getElementById('missionWhenTriggers');
    this.missionHowInstructions = document.getElementById('missionHowInstructions');
    this.missionExitCondition = document.getElementById('missionExitCondition');
    this.missionAllowedTools = document.getElementById('missionAllowedTools');
    this.dismissAgentBtn = document.getElementById('dismissAgentBtn');
  }

  setupEvents() {
    // Fechar modais
    this.closeAgentModalBtn.addEventListener('click', () => this.closeAgentModal());
    this.closeChatBtn.addEventListener('click', () => this.closeChatDrawer());

    // Toggle Missão Cirúrgica do Subagente
    if (this.toggleMissionBtn) {
      this.toggleMissionBtn.addEventListener('click', () => {
        const isHidden = !this.missionBody.style.display || this.missionBody.style.display === 'none';
        this.missionBody.style.display = isHidden ? 'flex' : 'none';
        this.toggleMissionBtn.textContent = isHidden ? 'Ocultar ▲' : 'Detalhes ▼';
      });
    }

    // Bater Ponto e Dispensar Subagente
    if (this.dismissAgentBtn) {
      this.dismissAgentBtn.addEventListener('click', () => {
        if (this.activeChatAgent) {
          if (confirm(`Confirmar encerramento de contrato e liberar a mesa de ${this.activeChatAgent.name}?`)) {
            const agentId = this.activeChatAgent.id;
            this.closeChatDrawer();
            this.deleteAgent(agentId);
          }
        }
      });
    }

    // Mudança de papel hierárquico
    this.agentRoleSelect.addEventListener('change', () => {
      const isWorker = this.agentRoleSelect.value === 'worker';
      this.supervisorGroup.style.display = isWorker ? 'block' : 'none';
      if (isWorker) {
        this.populateSupervisorsDropdown();
      }
    });

    // Submissão do formulário de agente
    this.agentForm.addEventListener('submit', (e) => {
      e.preventDefault();
      this.saveAgent();
    });

    // Exclusão de agente
    this.deleteAgentBtn.addEventListener('click', () => {
      if (this.editingAgentId) {
        if (confirm("Tem certeza que deseja dispensar este agente do escritório?")) {
          this.deleteAgent(this.editingAgentId);
        }
      }
    });

    // Envio de chat
    this.sendChatBtn.addEventListener('click', () => this.sendMessage());
    this.chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });

    // Atalho para editar agente a partir do chat
    this.editCurrentAgentBtn.addEventListener('click', () => {
      if (this.activeChatAgent) {
        this.closeChatDrawer();
        this.openEditAgentModal(this.activeChatAgent);
      }
    });

    // Limpar logs
    if (this.clearLogsBtn) {
      this.clearLogsBtn.addEventListener('click', () => {
        this.activityFeed.innerHTML = '';
        this.logActivity('Logs limpos.', 'info');
      });
    }
  }

  setupSocketListeners() {
    const socket = window.officeSocket;

    socket.on('workspace.updated', (data) => {
      this.currentWorkspace = data.workspace;
      if (window.officeEngine) {
        window.officeEngine.setWorkspace(data.workspace);
      }
    });

    socket.on('agent.status', (data) => {
      if (window.officeEngine) {
        window.officeEngine.updateAgentStatus(data.id, data.state);
      }
      const agent = this.findAgent(data.id);
      if (agent) {
        this.logActivity(`${agent.name} mudou para o estado: ${data.state.toUpperCase()}`, 'status');
      }
    });

    socket.on('agent.move', (data) => {
      if (window.officeEngine) {
        window.officeEngine.moveAgent(data.id, data.target_x, data.target_y, data.action, data.speed);
      }
    });

    socket.on('agent.spawned', (data) => {
      const a = data.agent || data;
      this.logActivity(`✨ Supervisor contratou '${a.name}' (${a.title})`, 'notice');
      if (this.currentWorkspace) {
        if (!this.currentWorkspace.agents) this.currentWorkspace.agents = [];
        const idx = this.currentWorkspace.agents.findIndex(x => x.id === a.id);
        if (idx >= 0) {
          this.currentWorkspace.agents[idx] = a;
        } else {
          this.currentWorkspace.agents.push(a);
        }
        const d = (this.currentWorkspace.desks || []).find(x => x.id === a.desk_id);
        if (d) d.agent_id = a.id;
      }
    });

    socket.on('agent.despawned', (data) => {
      const agentId = data.agent_id || data.id;
      const deskId = data.desk_id;
      this.logActivity(`🚪 Subagente concluiu a missão e liberou a mesa.`, 'info');
      if (this.currentWorkspace) {
        this.currentWorkspace.agents = (this.currentWorkspace.agents || []).filter(a => a.id !== agentId);
        const d = (this.currentWorkspace.desks || []).find(x => x.id === deskId || x.agent_id === agentId);
        if (d) d.agent_id = null;
      }
      if (this.activeChatAgent && this.activeChatAgent.id === agentId) {
        this.closeChatDrawer();
      }
    });

    socket.on('fs.activity', (data) => {
      const act = data.action === 'created_file' ? 'criou arquivo' :
                  data.action === 'created_dir' ? 'criou pasta' :
                  data.action === 'read_file' ? 'leu arquivo' : data.action;
      this.logActivity(`📁 [FS] ${data.agent_id ? data.agent_id + ' ' : ''}${act}: ${data.path}`, 'status');
    });

    socket.on('chat.system_notice', (data) => {
      this.logActivity(data.message, 'notice');
      if (this.activeChatAgent) {
        this.appendChatMessage('system', data.message);
      }
    });

    socket.on('chat.delta', (data) => {
      if (this.activeChatAgent) {
        this.appendChatDelta(data.delta);
      }
    });

    socket.on('chat.completed', (data) => {
      this.finalizeChatMessage();
      this.sendChatBtn.disabled = false;
      this.chatInput.disabled = false;
      this.chatInput.focus();
    });

    socket.on('chat.error', (data) => {
      this.logActivity(`Erro: ${data.error}`, 'error');
      if (this.activeChatAgent) {
        this.appendChatMessage('error', `Erro: ${data.error}`);
      }
      this.sendChatBtn.disabled = false;
      this.chatInput.disabled = false;
    });
  }

  findAgent(agentId) {
    if (!this.currentWorkspace) return null;
    return (this.currentWorkspace.agents || []).find(a => a.id === agentId);
  }

  // --- CRUD DE AGENTES ---

  openCreateAgentModal(desk) {
    this.selectedDeskForCreate = desk;
    this.editingAgentId = null;
    this.agentModalTitle.textContent = `Contratar Agente para ${desk.name}`;
    this.deleteAgentBtn.style.display = 'none';

    // Resetar campos com sugestão padrão inteligente
    this.agentNameInput.value = '';
    this.agentTitleInput.value = '';
    this.agentRoleSelect.value = 'solo';
    this.supervisorGroup.style.display = 'none';
    this.populateDesksDropdown(desk.id);
    this.populateSupervisorsDropdown();

    // Sugerir prompt padrão
    this.agentPromptInput.value = "Você é um especialista focado e analítico, pronto para colaborar com a equipe.";
    this.agentModelInput.value = '';

    this.agentModal.classList.add('active');
    this.agentNameInput.focus();
  }

  openEditAgentModal(agent) {
    this.editingAgentId = agent.id;
    this.selectedDeskForCreate = null;
    this.agentModalTitle.textContent = `Editar Agente: ${agent.name}`;
    this.deleteAgentBtn.style.display = 'inline-flex';

    this.agentNameInput.value = agent.name;
    this.agentTitleInput.value = agent.title;
    this.agentAvatarSelect.value = agent.avatar_id || 'avatar_1';
    this.agentRoleSelect.value = agent.role_type;
    this.supervisorGroup.style.display = agent.role_type === 'worker' ? 'block' : 'none';

    this.populateDesksDropdown(agent.desk_id);
    this.populateSupervisorsDropdown(agent.supervisor_id, agent.id);

    this.agentPromptInput.value = agent.system_prompt;
    this.agentModelInput.value = agent.model_name || '';

    this.agentModal.classList.add('active');
  }

  closeAgentModal() {
    this.agentModal.classList.remove('active');
  }

  populateDesksDropdown(selectedDeskId) {
    this.agentDeskSelect.innerHTML = '';
    if (!this.currentWorkspace) return;

    this.currentWorkspace.desks.forEach(d => {
      const isCurrent = d.id === selectedDeskId;
      const isFree = !d.agent_id || isCurrent;
      if (isFree) {
        const opt = document.createElement('option');
        opt.value = d.id;
        opt.textContent = `${d.name} ${isCurrent ? '(Atual)' : ''}`;
        if (isCurrent) opt.selected = true;
        this.agentDeskSelect.appendChild(opt);
      }
    });
  }

  populateSupervisorsDropdown(selectedSupId = null, excludeAgentId = null) {
    this.agentSupervisorSelect.innerHTML = '<option value="">-- Selecione o Supervisor --</option>';
    if (!this.currentWorkspace) return;

    const supervisors = (this.currentWorkspace.agents || []).filter(
      a => a.role_type === 'supervisor' && a.id !== excludeAgentId
    );

    supervisors.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.id;
      opt.textContent = `👑 ${s.name} (${s.title})`;
      if (s.id === selectedSupId) opt.selected = true;
      this.agentSupervisorSelect.appendChild(opt);
    });
  }

  async saveAgent() {
    const payload = {
      name: this.agentNameInput.value.trim(),
      title: this.agentTitleInput.value.trim() || 'Especialista',
      avatar_id: this.agentAvatarSelect.value,
      role_type: this.agentRoleSelect.value,
      supervisor_id: this.agentRoleSelect.value === 'worker' ? this.agentSupervisorSelect.value : null,
      desk_id: this.agentDeskSelect.value,
      system_prompt: this.agentPromptInput.value.trim(),
      model_name: this.agentModelInput.value.trim()
    };

    if (!payload.name) {
      alert("Por favor, preencha o nome do agente.");
      return;
    }

    try {
      let res;
      if (this.editingAgentId) {
        res = await fetch(`/api/agents/${this.editingAgentId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } else {
        res = await fetch('/api/agents', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Erro ao salvar agente");
      }

      this.closeAgentModal();
    } catch (e) {
      alert(e.message);
    }
  }

  async deleteAgent(agentId) {
    try {
      const res = await fetch(`/api/agents/${agentId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error("Erro ao excluir agente");
      this.closeAgentModal();
    } catch (e) {
      alert(e.message);
    }
  }

  // --- JANELA DE CHAT ---

  async openChatDrawer(agent) {
    this.activeChatAgent = agent;

    let roleIcon = '✦';
    let roleText = 'Solo';
    if (agent.role_type === 'supervisor') {
      roleIcon = '👑';
      roleText = 'Supervisor / Tech Lead';
    } else if (agent.role_type === 'worker') {
      roleIcon = '⚙️';
      roleText = 'Worker';
    }

    this.chatAgentName.textContent = `${roleIcon} ${agent.name}`;
    this.chatAgentRole.textContent = `${agent.title} • ${roleText}`;

    // Painel de Missão Cirúrgica Delegada
    if (agent.mission && this.subagentMissionCard) {
      this.subagentMissionCard.style.display = 'block';
      this.missionWhatTask.textContent = agent.mission.what_exact_task || '(Não especificado)';
      this.missionWhatOutOfScope.textContent = agent.mission.what_out_of_scope || '(Nenhuma restrição)';
      this.missionWhenTriggers.textContent = agent.mission.when_triggers || '(Imediato)';
      this.missionHowInstructions.textContent = agent.mission.how_instructions || '(Livre)';
      this.missionExitCondition.textContent = agent.mission.exit_condition || '(Sob demanda)';

      this.missionAllowedTools.innerHTML = '';
      const tools = agent.mission.allowed_tools || [];
      tools.forEach(t => {
        const span = document.createElement('span');
        span.className = 'tool-tag';
        span.textContent = t;
        this.missionAllowedTools.appendChild(span);
      });

      if (this.dismissAgentBtn) {
        this.dismissAgentBtn.style.display = 'inline-flex';
      }
    } else {
      if (this.subagentMissionCard) this.subagentMissionCard.style.display = 'none';
      if (this.dismissAgentBtn) {
        this.dismissAgentBtn.style.display = agent.is_temporary ? 'inline-flex' : 'none';
      }
    }

    this.chatMessages.innerHTML = '';
    this.chatDrawer.classList.add('active');

    // Carregar histórico
    try {
      const res = await fetch(`/api/agents/${agent.id}/conversations`);
      if (res.ok) {
        const history = await res.json();
        history.forEach(m => {
          this.appendChatMessage(m.role, m.text);
        });
      }
    } catch (e) {
      console.warn("Não foi possível carregar histórico:", e);
    }

    this.chatInput.focus();
  }

  closeChatDrawer() {
    this.chatDrawer.classList.remove('active');
    if (this.subagentMissionCard) this.subagentMissionCard.style.display = 'none';
    if (this.missionBody) this.missionBody.style.display = 'none';
    if (this.toggleMissionBtn) this.toggleMissionBtn.textContent = 'Detalhes ▼';
    this.activeChatAgent = null;
  }

  async sendMessage() {
    const text = this.chatInput.value.trim();
    if (!text || !this.activeChatAgent) return;

    this.appendChatMessage('user', text);
    this.chatInput.value = '';
    this.sendChatBtn.disabled = true;

    // Criar placeholder da resposta do assistente
    this.currentAssistantMessageElem = document.createElement('div');
    this.currentAssistantMessageElem.className = 'chat-bubble assistant streaming';
    this.currentAssistantMessageElem.innerHTML = '<span class="typing-indicator">●●●</span>';
    this.chatMessages.appendChild(this.currentAssistantMessageElem);
    this.chatMessages.scrollTop = this.chatMessages.scrollHeight;

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: this.activeChatAgent.id,
          message: text
        })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Erro ao despachar mensagem");
      }
    } catch (e) {
      this.currentAssistantMessageElem.innerHTML = `<span style="color: var(--accent-rose);">Erro: ${e.message}</span>`;
      this.sendChatBtn.disabled = false;
    }
  }

  appendChatDelta(delta) {
    if (!this.currentAssistantMessageElem) return;

    // Se ainda tiver o indicador de digitação, limpa
    if (this.currentAssistantMessageElem.querySelector('.typing-indicator')) {
      this.currentAssistantMessageElem.innerHTML = '';
      this.currentAssistantMessageElem.dataset.raw = '';
    }

    const current = this.currentAssistantMessageElem.dataset.raw || '';
    const updated = current + delta;
    this.currentAssistantMessageElem.dataset.raw = updated;

    // Renderizar preservando quebras de linha
    this.currentAssistantMessageElem.textContent = updated;
    this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
  }

  finalizeChatMessage() {
    if (this.currentAssistantMessageElem) {
      this.currentAssistantMessageElem.classList.remove('streaming');
      this.currentAssistantMessageElem = null;
    }
  }

  appendChatMessage(role, text) {
    const bubble = document.createElement('div');
    bubble.className = `chat-bubble ${role}`;

    if (role === 'system') {
      bubble.innerHTML = `<small>🔔 ${text}</small>`;
    } else {
      bubble.textContent = text;
    }

    this.chatMessages.appendChild(bubble);
    this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
  }

  // --- PAINEL DE ATIVIDADES DO ESCRITÓRIO ---

  logActivity(message, type = 'info') {
    if (!this.activityFeed) return;

    const time = new Date().toLocaleTimeString('pt-BR');
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.innerHTML = `<span class="log-time">[${time}]</span> <span class="log-text">${message}</span>`;

    this.activityFeed.appendChild(entry);
    this.activityFeed.scrollTop = this.activityFeed.scrollHeight;

    // Limitar histórico a 100 itens
    if (this.activityFeed.children.length > 100) {
      this.activityFeed.removeChild(this.activityFeed.firstChild);
    }
  }
}

// Interação global disparada por proximidade ([E]) ou clique na mesa
window.handleDeskInteraction = function(desk, agent) {
  if (agent) {
    window.officeUI.openChatDrawer(agent);
  } else {
    window.officeUI.openCreateAgentModal(desk);
  }
};
