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
    this.agentTierSelect = document.getElementById('agentTierSelect');
    this.agentSquadSelect = document.getElementById('agentSquadSelect');
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

    // Etapa 7: Sala da Diretoria (Sudo) & Hierarquia Modal
    this.openSudoModalBtn = document.getElementById('openSudoModalBtn');
    this.closeSudoModalBtn = document.getElementById('closeSudoModalBtn');
    this.sudoModal = document.getElementById('sudoModal');
    this.sudoMacroGoalInput = document.getElementById('sudoMacroGoalInput');
    this.dispatchSudoGoalBtn = document.getElementById('dispatchSudoGoalBtn');
    this.sudoExampleBtn1 = document.getElementById('sudoExampleBtn1');
    this.sudoExampleBtn2 = document.getElementById('sudoExampleBtn2');
    this.sudoProgressBox = document.getElementById('sudoProgressBox');
    this.sudoProgressTitle = document.getElementById('sudoProgressTitle');
    this.sudoDeliveryContainer = document.getElementById('sudoDeliveryContainer');
    this.sudoDeliveryContent = document.getElementById('sudoDeliveryContent');

    this.openHierarchyBtn = document.getElementById('openHierarchyBtn');
    this.closeHierarchyBtn = document.getElementById('closeHierarchyBtn');
    this.hierarchyModal = document.getElementById('hierarchyModal');
    this.tabOrganogramBtn = document.getElementById('tabOrganogramBtn');
    this.tabTicketsBtn = document.getElementById('tabTicketsBtn');
    this.tabContentOrganogram = document.getElementById('tabContentOrganogram');
    this.tabContentTickets = document.getElementById('tabContentTickets');
    this.organogramTree = document.getElementById('organogramTree');
    this.ticketsListContainer = document.getElementById('ticketsListContainer');
    this.refreshTicketsBtn = document.getElementById('refreshTicketsBtn');
    this.tabTicketsCount = document.getElementById('tabTicketsCount');
    this.ticketsActiveBadge = document.getElementById('ticketsActiveBadge');
  }

  setupEvents() {
    // Fechar modais
    this.closeAgentModalBtn.addEventListener('click', () => this.closeAgentModal());
    this.closeChatBtn.addEventListener('click', () => this.closeChatDrawer());

    // Modal da Diretoria (Sudo)
    if (this.openSudoModalBtn) {
      this.openSudoModalBtn.addEventListener('click', () => this.openSudoModal());
    }
    if (this.closeSudoModalBtn) {
      this.closeSudoModalBtn.addEventListener('click', () => this.closeSudoModal());
    }
    if (this.sudoExampleBtn1) {
      this.sudoExampleBtn1.addEventListener('click', () => {
        this.sudoMacroGoalInput.value = "Desenvolva uma API simples de usuários com banco SQLite e faça uma análise de vulnerabilidades de segurança das rotas criadas";
      });
    }
    if (this.sudoExampleBtn2) {
      this.sudoExampleBtn2.addEventListener('click', () => {
        this.sudoMacroGoalInput.value = "Crie uma camada de repositório ORM para produtos e gere a documentação técnica da arquitetura";
      });
    }
    if (this.dispatchSudoGoalBtn) {
      this.dispatchSudoGoalBtn.addEventListener('click', () => this.dispatchSudoMacroGoal());
    }

    // Modal do Organograma & Tickets
    if (this.openHierarchyBtn) {
      this.openHierarchyBtn.addEventListener('click', () => this.openHierarchyModal());
    }
    if (this.closeHierarchyBtn) {
      this.closeHierarchyBtn.addEventListener('click', () => this.closeHierarchyModal());
    }
    if (this.tabOrganogramBtn) {
      this.tabOrganogramBtn.addEventListener('click', () => this.switchHierarchyTab('organogram'));
    }
    if (this.tabTicketsBtn) {
      this.tabTicketsBtn.addEventListener('click', () => this.switchHierarchyTab('tickets'));
    }
    if (this.refreshTicketsBtn) {
      this.refreshTicketsBtn.addEventListener('click', () => this.loadActiveTickets());
    }

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
        const agentToEdit = this.activeChatAgent;
        this.closeChatDrawer();
        this.openEditAgentModal(agentToEdit);
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
      if (this.currentAssistantMessageElem) {
        if (this.currentAssistantMessageElem.querySelector('.typing-indicator')) {
          this.currentAssistantMessageElem.innerHTML = '';
        }
        if (!this.currentAssistantMessageElem.textContent.trim() && data.message) {
          this.currentAssistantMessageElem.textContent = data.message;
        }
      }
      this.finalizeChatMessage();
      this.sendChatBtn.disabled = false;
      this.chatInput.disabled = false;
      this.chatInput.focus();
    });

    // Eventos da Arquitetura Multinível (Etapa 7: Sudo Agent & Inter-Squad)
    socket.on('squad.dispatched', (data) => {
      this.logActivity(`👑 [Sudo Agent] Épico '${data.epic_title}' despachado para squad '${data.squad_name || data.squad_id}'!`, 'notice');
      this.updateSudoStep(2, `Épico despachado para ${data.squad_name || data.squad_id}...`);
    });

    socket.on('squad.cross_request', (data) => {
      const ticket = data.ticket_data || data;
      this.logActivity(`🤝 [Inter-Squad] Ticket aberto: ${ticket.from_squad_id} ➔ ${ticket.to_squad_id}`, 'status');
      this.updateSudoStep(3, `Cooperação Inter-Squad: ${ticket.from_squad_id} ➔ ${ticket.to_squad_id}...`);
      this.loadActiveTickets();
    });

    socket.on('squad.ticket_resolved', (data) => {
      const ticket = data.ticket_data || data;
      this.logActivity(`✅ [Inter-Squad] Ticket resolvido e entregue com sucesso!`, 'status');
      this.updateSudoStep(3, `Ticket resolvido pelo squad de destino!`);
      this.loadActiveTickets();
    });

    socket.on('sudo.final_delivery', (data) => {
      this.logActivity(`🏆 [Sudo Agent] Parecer Executivo consolidado!`, 'notice');
      this.handleSudoDelivery(data);
      if (this.currentAssistantMessageElem) {
        if (this.currentAssistantMessageElem.querySelector('.typing-indicator')) {
          this.currentAssistantMessageElem.innerHTML = '';
        }
        if (!this.currentAssistantMessageElem.textContent.trim() && data.final_summary) {
          this.currentAssistantMessageElem.textContent = data.final_summary;
        }
        this.finalizeChatMessage();
      }
      this.sendChatBtn.disabled = false;
      this.chatInput.disabled = false;
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
    if (this.agentTierSelect) {
      this.agentTierSelect.value = 'worker';
    }
    if (this.agentSquadSelect) {
      if (desk.room_id === 'room_dev') this.agentSquadSelect.value = 'squad-core-engineering';
      else if (desk.room_id === 'room_sec') this.agentSquadSelect.value = 'squad-security';
      else if (desk.room_id === 'room_doc') this.agentSquadSelect.value = 'squad-documentation';
      else this.agentSquadSelect.value = '';
    }
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
    if (!agent) return;
    this.editingAgentId = agent.id;
    this.selectedDeskForCreate = null;
    this.agentModalTitle.textContent = `Editar Agente: ${agent.name}`;
    
    // Proteger Sudo Agent contra dispensa/exclusão acidental
    const isSudo = agent.tier === 'sudo' || agent.id === 'agent-sudo';
    this.deleteAgentBtn.style.display = isSudo ? 'none' : 'inline-flex';

    this.agentNameInput.value = agent.name || '';
    this.agentTitleInput.value = agent.title || '';
    this.agentAvatarSelect.value = agent.avatar_id || 'avatar_1';
    this.agentRoleSelect.value = agent.role_type || 'solo';
    if (this.agentTierSelect) {
      this.agentTierSelect.value = agent.tier || 'worker';
    }
    if (this.agentSquadSelect) {
      this.agentSquadSelect.value = agent.squad_id || '';
    }
    this.supervisorGroup.style.display = agent.role_type === 'worker' ? 'block' : 'none';

    this.populateDesksDropdown(agent.desk_id);
    this.populateSupervisorsDropdown(agent.supervisor_id, agent.id);

    this.agentPromptInput.value = agent.system_prompt || '';
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
      tier: this.agentTierSelect ? this.agentTierSelect.value : undefined,
      avatar_id: this.agentAvatarSelect.value,
      role_type: this.agentRoleSelect.value,
      supervisor_id: this.agentRoleSelect.value === 'worker' ? this.agentSupervisorSelect.value : null,
      squad_id: this.agentSquadSelect && this.agentSquadSelect.value ? this.agentSquadSelect.value : null,
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
    if (!this.currentAssistantMessageElem) {
      this.currentAssistantMessageElem = document.createElement('div');
      this.currentAssistantMessageElem.className = 'chat-bubble assistant streaming';
      this.chatMessages.appendChild(this.currentAssistantMessageElem);
    }

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
      if (this.currentAssistantMessageElem.querySelector('.typing-indicator')) {
        this.currentAssistantMessageElem.innerHTML = '';
      }
      this.currentAssistantMessageElem = null;
    }
    if (this.sendChatBtn) this.sendChatBtn.disabled = false;
    if (this.chatInput) this.chatInput.disabled = false;
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

  // --- ETAPA 7: SALA DA DIRETORIA (SUDO AGENT) & GOVERNANÇA ---

  openSudoModal() {
    if (window.officeModals) {
      window.officeModals.showModal('sudoModal');
    } else if (this.sudoModal) {
      this.sudoModal.classList.add('active');
    }
  }

  closeSudoModal() {
    if (window.officeModals) {
      window.officeModals.closeModal('sudoModal');
    } else if (this.sudoModal) {
      this.sudoModal.classList.remove('active');
    }
  }

  updateSudoStep(stepNum, statusText = "") {
    if (!this.sudoProgressBox) return;
    this.sudoProgressBox.style.display = 'block';
    if (statusText && this.sudoProgressTitle) {
      this.sudoProgressTitle.textContent = statusText;
    }

    for (let s = 1; s <= 4; s++) {
      const stepEl = document.getElementById(`step-${s}`);
      if (!stepEl) continue;
      if (s < stepNum) {
        stepEl.className = 'sudo-step done';
      } else if (s === stepNum) {
        stepEl.className = 'sudo-step active';
      } else {
        stepEl.className = 'sudo-step';
      }
    }
  }

  async dispatchSudoMacroGoal() {
    const promptText = (this.sudoMacroGoalInput.value || '').trim();
    if (!promptText) {
      if (window.officeModals) window.officeModals.showToast("Informe a meta macro para o Sudo Agent.", "warning");
      return;
    }

    this.dispatchSudoGoalBtn.disabled = true;
    this.dispatchSudoGoalBtn.textContent = '⏳ Orquestrando...';
    this.sudoDeliveryContainer.style.display = 'none';

    this.updateSudoStep(1, "Sudo Agent analisando meta e decompondo épicos...");

    try {
      const res = await fetch('/api/sudo/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: promptText })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Erro no despacho executivo");
      }

      const data = await res.json();
      this.handleSudoDelivery(data);
    } catch (e) {
      if (window.officeModals) {
        window.officeModals.showToast(`Falha no despacho Sudo: ${e.message}`, "error");
      } else {
        alert(e.message);
      }
    } finally {
      this.dispatchSudoGoalBtn.disabled = false;
      this.dispatchSudoGoalBtn.innerHTML = '<span>🚀</span> Despachar Meta aos Squads';
    }
  }

  handleSudoDelivery(data) {
    this.updateSudoStep(4, "Parecer Executivo final consolidado!");
    const step4 = document.getElementById('step-4');
    if (step4) step4.className = 'sudo-step done';

    if (this.sudoDeliveryContainer && this.sudoDeliveryContent) {
      this.sudoDeliveryContainer.style.display = 'block';
      const summaryText = data.final_executive_summary || data.final_summary || data.message || "Meta concluída com sucesso.";
      this.sudoDeliveryContent.textContent = summaryText;
    }

    if (window.officeModals) {
      window.officeModals.showToast("🏆 Sudo Agent concluiu e consolidou a meta macro!", "success");
    }
  }

  // --- ETAPA 7: ORGANOGRAMA & TICKETS INTER-SQUAD ---

  openHierarchyModal() {
    if (window.officeModals) {
      window.officeModals.showModal('hierarchyModal');
    } else if (this.hierarchyModal) {
      this.hierarchyModal.classList.add('active');
    }
    this.renderOrganogram();
    this.loadActiveTickets();
  }

  closeHierarchyModal() {
    if (window.officeModals) {
      window.officeModals.closeModal('hierarchyModal');
    } else if (this.hierarchyModal) {
      this.hierarchyModal.classList.remove('active');
    }
  }

  switchHierarchyTab(tab) {
    if (tab === 'organogram') {
      this.tabOrganogramBtn.classList.add('active');
      this.tabTicketsBtn.classList.remove('active');
      this.tabContentOrganogram.style.display = 'block';
      this.tabContentTickets.style.display = 'none';
      this.renderOrganogram();
    } else {
      this.tabOrganogramBtn.classList.remove('active');
      this.tabTicketsBtn.classList.add('active');
      this.tabContentOrganogram.style.display = 'none';
      this.tabContentTickets.style.display = 'block';
      this.loadActiveTickets();
    }
  }

  renderOrganogram() {
    if (!this.organogramTree) return;

    const agents = (this.currentWorkspace && this.currentWorkspace.agents) || [];

    // 1. Identificar Sudo Agent
    const sudoAgent = agents.find(a => a.tier === 'sudo' || a.id === 'agent-sudo') || {
      name: "Sudo Agent",
      title: "Diretor Geral / Orquestrador Supremo",
      tier: "sudo",
      room_id: "room_sudo"
    };

    // 2. Mapear squads
    const squads = [
      {
        id: 'squad-core-engineering',
        name: 'Squad Engenharia (Dev Room)',
        icon: '⚙️',
        room_id: 'room_dev',
        color: '#10b981'
      },
      {
        id: 'squad-security',
        name: 'Squad Segurança (Sec Room)',
        icon: '🛡️',
        room_id: 'room_sec',
        color: '#a855f7'
      },
      {
        id: 'squad-documentation',
        name: 'Squad Documentação (Doc Room)',
        icon: '📝',
        room_id: 'room_doc',
        color: '#38bdf8'
      }
    ];

    let html = `
      <div class="organogram-tier-sudo">
        <div class="organogram-card sudo">
          <span class="organogram-card-badge">👑 Nível 1: Diretoria Executiva</span>
          <div class="organogram-card-name">👑 ${sudoAgent.name}</div>
          <div class="organogram-card-title">${sudoAgent.title || 'Diretor Geral e Orquestrador Supremo'}</div>
          <div style="font-size: 10px; color: #fbbf24; margin-top: 4px;">Sala Executiva • Decomposição Estratégica & Despacho</div>
          ${sudoAgent.id ? `<button class="btn-action edit-organogram-btn" data-agent-id="${sudoAgent.id}" style="font-size: 10px; padding: 2px 8px; margin-top: 6px; background: rgba(251, 191, 36, 0.2); border-color: #fbbf24; color: #fde68a;">✏️ Configurar Diretor</button>` : ''}
        </div>
        <div style="width: 2px; height: 20px; background: rgba(245, 158, 11, 0.4); margin: 4px auto;"></div>
      </div>

      <div class="organogram-squads-row">
    `;

    squads.forEach(sq => {
      const squadAgents = agents.filter(a => a.squad_id === sq.id || a.room_id === sq.room_id);
      const leader = squadAgents.find(a => a.tier === 'squad_leader') || squadAgents[0] || null;
      const subordinates = squadAgents.filter(a => a !== leader);

      html += `
        <div class="squad-column" style="border-top: 3px solid ${sq.color};">
          <div class="squad-column-header" style="color: ${sq.color};">
            <span>${sq.icon}</span> ${sq.name}
          </div>

          <!-- Líder do Squad -->
          <div class="organogram-card leader" style="border-color: ${sq.color};">
            <span class="organogram-card-badge" style="background: rgba(255,255,255,0.1); color: ${sq.color};">⭐ Nível 2: Líder Departamental</span>
            <div class="organogram-card-name">${leader ? leader.name : 'Vaga Aberta'}</div>
            <div class="organogram-card-title">${leader ? leader.title : 'Aguardando Alocação'}</div>
            ${leader ? `<button class="btn-action edit-organogram-btn" data-agent-id="${leader.id}" style="font-size: 10px; padding: 2px 6px; margin-top: 6px; border-color: ${sq.color};">✏️ Editar Líder</button>` : ''}
          </div>

          <!-- Subordinados / Especialistas -->
          <div class="squad-members-list">
            <div style="font-size: 9px; color: var(--text-dim); text-transform: uppercase; font-family: var(--font-pixel);">
              Especialistas (${subordinates.length})
            </div>
      `;

      if (subordinates.length === 0) {
        html += `<div style="font-size: 10px; color: var(--text-muted); font-style: italic;">Nenhum especialista alocado.</div>`;
      } else {
        subordinates.forEach(sub => {
          const isSubagent = sub.tier === 'subagent' || sub.is_temporary;
          html += `
            <div class="member-chip ${isSubagent ? 'subagent' : ''}">
              <span>${isSubagent ? '⚡' : '⚙️'} ${sub.name}</span>
              <span style="font-size: 9px; color: var(--text-muted);">${sub.title || 'Dev'}</span>
              <button class="btn-action edit-organogram-btn" data-agent-id="${sub.id}" style="font-size: 9px; padding: 1px 4px; margin-left: auto;" title="Editar Agente">✏️</button>
            </div>
          `;
        });
      }

      html += `
          </div>
        </div>
      `;
    });

    html += `</div>`;
    this.organogramTree.innerHTML = html;

    // Vincular cliques nos botões de edição do organograma
    this.organogramTree.querySelectorAll('.edit-organogram-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const aId = btn.getAttribute('data-agent-id');
        const ag = this.findAgent(aId);
        if (ag) {
          this.closeHierarchyModal();
          this.openEditAgentModal(ag);
        }
      });
    });
  }

  async loadActiveTickets() {
    try {
      const res = await fetch('/api/tickets');
      if (res.ok) {
        const tickets = await res.json();
        this.renderTickets(tickets);
      }
    } catch (e) {
      console.warn('[UI] Falha ao carregar tickets inter-squad:', e);
    }
  }

  renderTickets(tickets = []) {
    if (this.tabTicketsCount) {
      this.tabTicketsCount.textContent = tickets.length;
    }
    if (this.ticketsActiveBadge) {
      const pendingCount = tickets.filter(t => t.status === 'pending' || t.status === 'in_progress').length;
      this.ticketsActiveBadge.textContent = pendingCount;
      this.ticketsActiveBadge.style.display = pendingCount > 0 ? 'inline-block' : 'none';
    }

    if (!this.ticketsListContainer) return;

    if (tickets.length === 0) {
      this.ticketsListContainer.innerHTML = `
        <div style="text-align: center; padding: 24px; color: var(--text-muted); font-size: 12px;">
          🤝 Nenhum ticket inter-squad aberto no momento. Os líderes criam tickets quando precisam de assistência técnica lateral!
        </div>
      `;
      return;
    }

    let html = '';
    tickets.forEach(t => {
      const isDelivered = t.status === 'delivered';
      html += `
        <div class="ticket-card" style="border-left: 3px solid ${isDelivered ? '#10b981' : '#f59e0b'};">
          <div class="ticket-header">
            <div class="ticket-route">
              <span>🤝</span> ${t.from_squad_id} ➔ ${t.to_squad_id}
            </div>
            <span class="ticket-status-pill ${t.status}">${t.status.toUpperCase()}</span>
          </div>
          <div class="ticket-req-text">
            <strong>Requisito Técnico:</strong> ${t.exact_requirement}
          </div>
          <div style="font-size: 10px; color: var(--text-dim); margin-bottom: 6px;">
            <strong>Motivo fora de escopo:</strong> ${t.reason_out_of_scope}
          </div>
      `;

      if (t.result_artifact) {
        html += `
          <div class="ticket-artifact-preview">
            ${t.result_artifact}
          </div>
        `;
      }

      html += `</div>`;
    });

    this.ticketsListContainer.innerHTML = html;
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
