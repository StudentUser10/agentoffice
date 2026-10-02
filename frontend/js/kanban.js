/**
 * AgentOffice 2D - Kanban Task Board Component (Etapa 4)
 * Gerencia o quadro Kanban em 6 colunas, sincronização via WebSocket em tempo real,
 * modal de detalhes de tarefa com visualização de diff, aprovação/rejeição e criação de tarefas.
 */

class OfficeKanban {
  constructor() {
    this.tasks = [];
    this.workflows = [];
    this.squads = [];
    this.selectedTaskId = null;
    this.filterQuery = '';

    this.columnDefs = [
      { id: 'QUEUED', label: 'Fila', icon: '⏳', color: '#94a3b8' },
      { id: 'IN_PROGRESS', label: 'Em andamento', icon: '⚙️', color: '#06b6d4' },
      { id: 'QUALITY_GATE', label: 'Revisão (QA)', icon: '🔍', color: '#8b5cf6' },
      { id: 'WAITING_APPROVAL', label: 'Aprovação Pendente', icon: '⚠️', color: '#f59e0b' },
      { id: 'COMPLETED', label: 'Concluído', icon: '✅', color: '#10b981' },
      { id: 'FAILED', label: 'Falhou', icon: '❌', color: '#f43f5e' }
    ];

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => this.init());
    } else {
      this.init();
    }
  }

  init() {
    this.cacheElements();
    this.setupEventListeners();
    this.setupWebSocketListeners();
    this.loadInitialData();
  }

  cacheElements() {
    // Botão de acesso rápido no cabeçalho
    this.openKanbanBtn = document.getElementById('openKanbanBtn');
    this.kanbanBadge = document.getElementById('kanbanActiveBadge');

    // Modal do Quadro Kanban
    this.kanbanModal = document.getElementById('kanbanModal');
    this.closeKanbanBtn = document.getElementById('closeKanbanBtn');
    this.kanbanSearchInput = document.getElementById('kanbanSearchInput');
    this.openCreateTaskBtn = document.getElementById('openCreateTaskBtn');
    this.refreshKanbanBtn = document.getElementById('refreshKanbanBtn');
    this.kanbanBoardContainer = document.getElementById('kanbanBoardContainer');

    // Modal de Criação de Tarefa
    this.taskCreateModal = document.getElementById('taskCreateModal');
    this.closeTaskCreateBtn = document.getElementById('closeTaskCreateBtn');
    this.taskCreateForm = document.getElementById('taskCreateForm');
    this.taskTitleInput = document.getElementById('taskTitleInput');
    this.taskObjectiveInput = document.getElementById('taskObjectiveInput');
    this.taskWorkflowSelect = document.getElementById('taskWorkflowSelect');
    this.taskSquadSelect = document.getElementById('taskSquadSelect');

    // Modal de Detalhes da Tarefa
    this.taskDetailModal = document.getElementById('taskDetailModal');
    this.closeTaskDetailBtn = document.getElementById('closeTaskDetailBtn');
    this.taskDetailContent = document.getElementById('taskDetailContent');
  }

  setupEventListeners() {
    // Abrir/Fechar Kanban
    if (this.openKanbanBtn) {
      this.openKanbanBtn.addEventListener('click', () => this.openKanban());
    }
    if (this.closeKanbanBtn) {
      this.closeKanbanBtn.addEventListener('click', () => window.officeModals.closeModal('kanbanModal'));
    }

    // Busca e Filtro
    if (this.kanbanSearchInput) {
      this.kanbanSearchInput.addEventListener('input', (e) => {
        this.filterQuery = e.target.value.toLowerCase().trim();
        this.renderBoard();
      });
    }

    // Atualização manual
    if (this.refreshKanbanBtn) {
      this.refreshKanbanBtn.addEventListener('click', () => this.loadTasks(true));
    }

    // Criar Tarefa Modal
    if (this.openCreateTaskBtn) {
      this.openCreateTaskBtn.addEventListener('click', () => this.openCreateTaskModal());
    }
    if (this.closeTaskCreateBtn) {
      this.closeTaskCreateBtn.addEventListener('click', () => window.officeModals.closeModal('taskCreateModal'));
    }
    if (this.taskCreateForm) {
      this.taskCreateForm.addEventListener('submit', (e) => {
        e.preventDefault();
        this.handleCreateTaskSubmit();
      });
    }

    // Fechar Detalhes
    if (this.closeTaskDetailBtn) {
      this.closeTaskDetailBtn.addEventListener('click', () => window.officeModals.closeModal('taskDetailModal'));
    }
  }

  setupWebSocketListeners() {
    const sock = window.officeSocket;
    if (!sock) return;

    // Resincronização ao reconectar conforme Seção 7
    sock.on('connection.reconnected', () => {
      console.log('[Kanban] Reconectado. Recarregando estado atualizado via API...');
      this.loadTasks(false);
      window.officeModals.showToast('Reconectado ao servidor do escritório. Tarefas sincronizadas.', 'success');
    });

    // Sincronização em lote se enviada pelo servidor
    sock.on('tasks.sync', (data) => {
      if (data.tasks) {
        this.tasks = data.tasks;
        this.renderBoard();
        this.updateHeaderBadge();
      }
    });

    // Criação de tarefa
    sock.on('task.created', (data) => {
      this.loadTasks(false);
      window.officeModals.showToast(`Nova tarefa enfileirada: ${data.task_id || ''}`, 'info');
    });

    // Atualização de tarefa
    sock.on('task.updated', (data) => {
      const task = data.task || (data.payload && data.payload.task);
      if (task) {
        this.upsertTask(task);
      } else {
        this.loadTasks(false);
      }
    });

    // Handoff entre agentes (com animação visual no Canvas 2D)
    sock.on('task.handoff', (data) => {
      const payload = data.payload || {};
      const agentName = payload.agent_name || 'Agente';
      const stepName = payload.step_name || 'Nova Etapa';
      window.officeModals.showToast(`Passagem de bastão: [${stepName}] delegada para ${agentName}`, 'info');

      if (window.officeEngine && payload.agent_id) {
        window.officeEngine.triggerHandoff(payload.from_agent_id || payload.agent_id, payload.agent_id, stepName);
      }
      this.loadTasks(false);
    });

    // Solicitação de aprovação pendente (Alerta visual no Canvas e Toast)
    sock.on('task.approval_requested', (data) => {
      const payload = data.payload || {};
      window.officeModals.showToast(`⚠️ Aprovação requerida: ${payload.summary || 'Proposta de alteração'}`, 'warning', 6000);

      const task = this.tasks.find(t => t.id === data.task_id);
      if (task && task.assigned_agent_id && window.officeEngine) {
        window.officeEngine.updateAgentStatus(task.assigned_agent_id, 'waiting_approval');
      }
      this.loadTasks(false);
    });

    // Aprovação concedida
    sock.on('task.approved', (data) => {
      window.officeModals.showToast('✅ Proposta de alteração aprovada pelo usuário.', 'success');
      this.loadTasks(false);
    });

    // Proposta rejeitada
    sock.on('task.rejected', (data) => {
      window.officeModals.showToast('❌ Proposta de alteração recusada.', 'warning');
      this.loadTasks(false);
    });

    // Evento de Quality Gate (com animação visual de QA no Canvas)
    sock.on('task.quality_gate_event', (data) => {
      const payload = data.payload || {};
      const task = this.tasks.find(t => t.id === data.task_id);
      if (task && task.assigned_agent_id && window.officeEngine) {
        window.officeEngine.updateAgentStatus(task.assigned_agent_id, 'reviewing');
      }
      if (payload.result === 'rejected') {
        window.officeModals.showToast(`Revisão de QA reprovada (${payload.revision_count}/${payload.max_revisions}). Devolvendo para refação.`, 'warning');
      } else {
        window.officeModals.showToast('Quality Gate aprovado por QA!', 'success');
      }
      this.loadTasks(false);
    });

    // Tarefa Concluída
    sock.on('task.completed', (data) => {
      window.officeModals.showToast('🎉 Tarefa concluída com sucesso!', 'success');
      this.loadTasks(false);
    });

    // Tarefa Falhou
    sock.on('task.failed', (data) => {
      const payload = data.payload || {};
      window.officeModals.showToast(`Tarefa falhou: ${payload.error || 'Erro na execução'}`, 'error');
      this.loadTasks(false);
    });
  }

  async loadInitialData() {
    await Promise.all([
      this.loadWorkflows(),
      this.loadSquads(),
      this.loadTasks(false)
    ]);
  }

  async loadWorkflows() {
    try {
      const res = await fetch('/api/workflows');
      if (res.ok) {
        this.workflows = await res.json();
        this.populateWorkflowSelect();
      }
    } catch (e) {
      console.warn('Erro ao carregar workflows:', e);
    }
  }

  async loadSquads() {
    try {
      const res = await fetch('/api/squads');
      if (res.ok) {
        this.squads = await res.json();
        this.populateSquadSelect();
      }
    } catch (e) {
      console.warn('Erro ao carregar squads:', e);
    }
  }

  async loadTasks(notify = false) {
    try {
      const res = await fetch('/api/tasks');
      if (res.ok) {
        this.tasks = await res.json();
        this.renderBoard();
        this.updateHeaderBadge();
        if (this.selectedTaskId) {
          // Atualiza o modal de detalhes se estiver aberto
          const updated = this.tasks.find(t => t.id === this.selectedTaskId);
          if (updated && document.getElementById('taskDetailModal')?.classList.contains('active')) {
            this.renderTaskDetailContent(updated);
          }
        }
        if (notify) {
          window.officeModals.showToast('Quadro de tarefas atualizado.', 'info', 2000);
        }
      }
    } catch (e) {
      console.error('Erro ao buscar tarefas:', e);
    }
  }

  upsertTask(updatedTask) {
    const idx = this.tasks.findIndex(t => t.id === updatedTask.id);
    if (idx >= 0) {
      this.tasks[idx] = updatedTask;
    } else {
      this.tasks.push(updatedTask);
    }
    this.renderBoard();
    this.updateHeaderBadge();

    if (this.selectedTaskId === updatedTask.id) {
      this.renderTaskDetailContent(updatedTask);
    }
  }

  populateWorkflowSelect() {
    if (!this.taskWorkflowSelect) return;
    this.taskWorkflowSelect.innerHTML = '';
    this.workflows.forEach(wf => {
      const opt = document.createElement('option');
      opt.value = wf.id;
      opt.textContent = `${wf.name} (${wf.steps.length} etapas)`;
      this.taskWorkflowSelect.appendChild(opt);
    });
  }

  populateSquadSelect() {
    if (!this.taskSquadSelect) return;
    this.taskSquadSelect.innerHTML = '<option value="">-- Nenhum Squad (Agentes Avulsos) --</option>';
    this.squads.forEach(sq => {
      const opt = document.createElement('option');
      opt.value = sq.id;
      opt.textContent = `${sq.name} (${sq.agent_ids.length} agentes)`;
      this.taskSquadSelect.appendChild(opt);
    });
  }

  openKanban() {
    window.officeModals.showModal('kanbanModal');
    this.loadTasks(false);
  }

  openCreateTaskModal() {
    if (this.taskTitleInput) this.taskTitleInput.value = '';
    if (this.taskObjectiveInput) this.taskObjectiveInput.value = '';
    window.officeModals.showModal('taskCreateModal');
  }

  async handleCreateTaskSubmit() {
    const title = this.taskTitleInput.value.trim();
    const objective = this.taskObjectiveInput.value.trim();
    const workflowId = this.taskWorkflowSelect.value;
    const squadId = this.taskSquadSelect.value || null;

    if (!title || !objective || !workflowId) {
      window.officeModals.showToast('Preencha todos os campos obrigatórios.', 'warning');
      return;
    }

    try {
      const res = await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          objective,
          workflow_id: workflowId,
          squad_id: squadId
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Erro ao criar tarefa');
      }

      const newTask = await res.json();
      window.officeModals.closeModal('taskCreateModal');
      window.officeModals.showToast(`Tarefa "${newTask.title}" adicionada à Fila com sucesso!`, 'success');
      this.loadTasks(false);
    } catch (err) {
      window.officeModals.showToast(err.message, 'error');
    }
  }

  renderBoard() {
    if (!this.kanbanBoardContainer) return;
    this.kanbanBoardContainer.innerHTML = '';

    const filtered = this.tasks.filter(task => {
      if (!this.filterQuery) return true;
      const q = this.filterQuery;
      return (
        task.title.toLowerCase().includes(q) ||
        task.objective.toLowerCase().includes(q) ||
        task.id.toLowerCase().includes(q) ||
        (task.assigned_agent_id && task.assigned_agent_id.toLowerCase().includes(q))
      );
    });

    this.columnDefs.forEach(col => {
      const colTasks = filtered.filter(t => t.state === col.id);

      const colEl = document.createElement('div');
      colEl.className = `kanban-column column-${col.id.toLowerCase()}`;
      colEl.innerHTML = `
        <div class="column-header">
          <div class="column-title-group">
            <span class="column-icon">${col.icon}</span>
            <span class="column-name">${col.label}</span>
          </div>
          <span class="column-count" id="count-${col.id}">${colTasks.length}</span>
        </div>
        <div class="column-cards-list" id="cards-${col.id}"></div>
      `;

      const listEl = colEl.querySelector(`#cards-${col.id}`);

      if (colTasks.length === 0) {
        listEl.innerHTML = `
          <div class="kanban-empty-state">
            <div class="empty-icon">📭</div>
            <div class="empty-text">Nenhuma tarefa</div>
          </div>
        `;
      } else {
        colTasks.forEach(task => {
          const cardEl = this.createTaskCard(task);
          listEl.appendChild(cardEl);
        });
      }

      this.kanbanBoardContainer.appendChild(colEl);
    });
  }

  createTaskCard(task) {
    const card = document.createElement('div');
    card.className = `kanban-card card-state-${task.state.toLowerCase()}`;
    if (task.state === 'WAITING_APPROVAL') {
      card.classList.add('pulse-approval');
    }

    const wf = this.workflows.find(w => w.id === task.workflow_id);
    const wfName = wf ? wf.name : task.workflow_id;
    const currentStepName = (wf && wf.steps[task.current_step_index])
      ? wf.steps[task.current_step_index].name
      : `Etapa ${task.current_step_index + 1}`;

    let statusPillText = task.state;
    if (task.state === 'WAITING_APPROVAL') statusPillText = '⚠️ Aprovação Pendente';
    else if (task.state === 'QUALITY_GATE') statusPillText = '🔍 Em Revisão';
    else if (task.state === 'IN_PROGRESS') statusPillText = '⚙️ Executando';
    else if (task.state === 'QUEUED') statusPillText = '⏳ Na Fila';
    else if (task.state === 'COMPLETED') statusPillText = '✅ Concluído';
    else if (task.state === 'FAILED') statusPillText = '❌ Falhou';

    card.innerHTML = `
      <div class="card-header">
        <span class="card-wf-tag" title="Workflow">${wfName}</span>
        <span class="card-id-tag">${task.id}</span>
      </div>
      <div class="card-title">${this.escapeHtml(task.title)}</div>
      <div class="card-step-info">
        <span>📍 ${this.escapeHtml(currentStepName)}</span>
        ${task.revision_count > 0 ? `<span class="badge-revision" title="Contador de refações">🔄 ${task.revision_count}</span>` : ''}
      </div>
      <div class="card-footer">
        <div class="card-assigned">
          <span class="assigned-dot"></span>
          <span class="assigned-name">${task.assigned_agent_id ? this.formatAgentName(task.assigned_agent_id) : 'Não atribuído'}</span>
        </div>
        <span class="card-status-badge badge-${task.state.toLowerCase()}">${statusPillText}</span>
      </div>
    `;

    card.addEventListener('click', () => this.openTaskDetail(task.id));
    return card;
  }

  formatAgentName(agentId) {
    if (window.officeUI && window.officeUI.currentWorkspace) {
      const agent = window.officeUI.currentWorkspace.agents.find(a => a.id === agentId);
      if (agent) return agent.name;
    }
    return agentId;
  }

  async openTaskDetail(taskId) {
    this.selectedTaskId = taskId;
    const task = this.tasks.find(t => t.id === taskId);
    if (!task) return;

    window.officeModals.showModal('taskDetailModal');
    this.renderTaskDetailContent(task);

    // Busca versão mais recente da API
    try {
      const res = await fetch(`/api/tasks/${taskId}`);
      if (res.ok) {
        const fresh = await res.json();
        this.upsertTask(fresh);
        this.renderTaskDetailContent(fresh);
      }
    } catch (e) {}
  }

  renderTaskDetailContent(task) {
    if (!this.taskDetailContent) return;
    const wf = this.workflows.find(w => w.id === task.workflow_id);
    const wfSteps = wf ? wf.steps : [];

    const pendingApproval = (task.approvals || []).find(a => a.status === 'pending');

    let html = `
      <div class="detail-header-panel">
        <div>
          <div class="detail-id-badge">${task.id} • Workflow: ${wf ? wf.name : task.workflow_id}</div>
          <h2 class="detail-title">${this.escapeHtml(task.title)}</h2>
        </div>
        <div class="detail-actions-top">
          ${task.state === 'QUEUED' ? `<button class="btn-primary" id="btnStartTask" type="button">▶️ Iniciar Execução</button>` : ''}
          ${task.state === 'FAILED' ? `<button class="btn-primary" id="btnRetryTask" type="button">🔄 Tentar Novamente</button>` : ''}
          ${['IN_PROGRESS', 'QUALITY_GATE'].includes(task.state) ? `<button class="btn-danger" id="btnCancelTask" type="button">⏹️ Cancelar Tarefa</button>` : ''}
        </div>
      </div>

      <div class="detail-section">
        <div class="detail-section-title">🎯 Objetivo da Tarefa</div>
        <div class="detail-objective-box">${this.escapeHtml(task.objective)}</div>
      </div>

      <div class="detail-section">
        <div class="detail-section-title">📋 Etapas do Workflow</div>
        <div class="steps-stepper">
          ${wfSteps.map((step, idx) => {
            let stepStatusClass = 'step-pending';
            if (idx < task.current_step_index) stepStatusClass = 'step-done';
            else if (idx === task.current_step_index) {
              stepStatusClass = task.state === 'COMPLETED' ? 'step-done' : 'step-current';
            }
            return `
              <div class="stepper-item ${stepStatusClass}">
                <div class="stepper-circle">${idx < task.current_step_index || task.state === 'COMPLETED' ? '✓' : idx + 1}</div>
                <div class="stepper-label">
                  <strong>${this.escapeHtml(step.name)}</strong>
                  <small>${step.action_type.toUpperCase()} • ${step.required_role}</small>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;

    // Painel de Aprovação Humana Pendente (Seção Crítica de Decisão)
    if (pendingApproval) {
      html += `
        <div class="approval-card-banner">
          <div class="approval-banner-header">
            <div class="approval-banner-icon">⚠️</div>
            <div>
              <div class="approval-banner-title">Aprovação Humana Requerida</div>
              <div class="approval-banner-subtitle">${this.escapeHtml(pendingApproval.summary)}</div>
            </div>
          </div>

          ${pendingApproval.affected_file ? `
            <div class="approval-file-tag">
              📁 Arquivo Alvo Proposto: <code>${this.escapeHtml(pendingApproval.affected_file)}</code>
            </div>
          ` : ''}

          ${pendingApproval.proposed_diff ? `
            <div class="diff-container">
              <div class="diff-header">Visualização da Proposta (Diff Unificado)</div>
              <pre class="diff-viewer">${this.formatDiffLines(pendingApproval.proposed_diff)}</pre>
            </div>
          ` : ''}

          <div class="approval-controls">
            <input type="text" class="form-input" id="approvalNotesInput" placeholder="Justificativa ou instruções adicionais (opcional)...">
            <div class="approval-btn-group">
              <button class="btn-success" id="btnApproveProposal" type="button">
                ✅ Aprovar e Aplicar Alteração
              </button>
              <button class="btn-danger" id="btnRejectProposal" type="button">
                ❌ Recusar Proposta
              </button>
            </div>
          </div>
        </div>
      `;
    }

    // Histórico de Decisões e Entregas
    if (task.decisions && task.decisions.length > 0) {
      html += `
        <div class="detail-section">
          <div class="detail-section-title">💡 Resumo de Trabalho & Decisões</div>
          <ul class="decisions-list">
            ${task.decisions.map(d => `<li>${this.escapeHtml(d)}</li>`).join('')}
          </ul>
        </div>
      `;
    }

    // Histórico Cronológico de Eventos (Event Log)
    if (task.events && task.events.length > 0) {
      html += `
        <div class="detail-section">
          <div class="detail-section-title">⏱️ Histórico de Eventos da Tarefa</div>
          <div class="events-timeline">
            ${[...task.events].reverse().map(ev => `
              <div class="timeline-row">
                <span class="timeline-time">${new Date(ev.timestamp * 1000).toLocaleTimeString()}</span>
                <span class="timeline-badge">${ev.event_type}</span>
                <span class="timeline-msg">${this.escapeHtml(ev.message)}</span>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }

    // Seção de Relatório Final Markdown (Tarefas Concluídas)
    if (task.state === 'COMPLETED') {
      html += `
        <div class="detail-section">
          <div class="detail-section-title">📄 Relatório Final de Execução (Workspace Markdown)</div>
          <div class="report-box-container">
            <div class="report-box-toolbar">
              <span class="report-box-filename">relatorio_tarefa_${task.id}.md</span>
              <div class="report-btn-group">
                <button class="btn-sm btn-primary" id="btnLoadReportText" type="button">🔄 Atualizar Relatório</button>
                <button class="btn-sm btn-secondary" id="btnDownloadReport" type="button">⬇️ Baixar (.md)</button>
              </div>
            </div>
            <pre class="report-markdown-preview" id="reportPreviewContent">Carregando relatório consolidado do workspace...</pre>
          </div>
        </div>
      `;
    }

    this.taskDetailContent.innerHTML = html;

    // Vincular visualização e download do relatório Markdown
    if (task.state === 'COMPLETED') {
      const previewEl = document.getElementById('reportPreviewContent');
      const btnLoadReport = document.getElementById('btnLoadReportText');
      const btnDownload = document.getElementById('btnDownloadReport');

      const fetchReport = async () => {
        try {
          const res = await fetch(`/api/tasks/${task.id}/report`);
          if (res.ok) {
            const data = await res.json();
            if (previewEl) previewEl.textContent = data.content || 'Relatório sem conteúdo.';
            return data.content;
          }
        } catch (e) {
          if (previewEl) previewEl.textContent = 'Erro ao carregar relatório do workspace.';
        }
        return null;
      };

      fetchReport();

      if (btnLoadReport) {
        btnLoadReport.addEventListener('click', () => fetchReport());
      }
      if (btnDownload) {
        btnDownload.addEventListener('click', async () => {
          const content = await fetchReport();
          if (content) {
            const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `relatorio_tarefa_${task.id}.md`;
            a.click();
            URL.revokeObjectURL(url);
          }
        });
      }
    }

    // Vincular botões de ação nos detalhes
    const btnStart = document.getElementById('btnStartTask');
    if (btnStart) btnStart.addEventListener('click', () => this.startTask(task.id));

    const btnRetry = document.getElementById('btnRetryTask');
    if (btnRetry) btnRetry.addEventListener('click', () => this.retryTask(task.id));

    const btnCancel = document.getElementById('btnCancelTask');
    if (btnCancel) btnCancel.addEventListener('click', () => this.cancelTask(task.id));

    if (pendingApproval) {
      const btnApprove = document.getElementById('btnApproveProposal');
      const btnReject = document.getElementById('btnRejectProposal');
      const notesInput = document.getElementById('approvalNotesInput');

      if (btnApprove) {
        btnApprove.addEventListener('click', () => {
          this.decideApproval(task.id, pendingApproval.id, true, notesInput ? notesInput.value.trim() : '');
        });
      }
      if (btnReject) {
        btnReject.addEventListener('click', () => {
          const action = confirm("Deseja devolver a etapa para refação? Pressione [OK] para refazer ou [Cancelar] para finalizar como falha.") ? "retry" : "fail";
          this.decideApproval(task.id, pendingApproval.id, false, notesInput ? notesInput.value.trim() : '', action);
        });
      }
    }
  }

  formatDiffLines(rawDiff) {
    if (!rawDiff) return '';
    return rawDiff.split('\n').map(line => {
      if (line.startsWith('+') && !line.startsWith('+++')) {
        return `<span class="diff-add">${this.escapeHtml(line)}</span>`;
      } else if (line.startsWith('-') && !line.startsWith('---')) {
        return `<span class="diff-del">${this.escapeHtml(line)}</span>`;
      } else if (line.startsWith('@@') || line.startsWith('---') || line.startsWith('+++')) {
        return `<span class="diff-meta">${this.escapeHtml(line)}</span>`;
      }
      return `<span class="diff-ctx">${this.escapeHtml(line)}</span>`;
    }).join('\n');
  }

  async startTask(taskId) {
    try {
      const res = await fetch(`/api/tasks/${taskId}/start`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Não foi possível iniciar a tarefa');
      }
      window.officeModals.showToast('Tarefa iniciada! Acompanhe o progresso em tempo real.', 'info');
      this.loadTasks(false);
    } catch (e) {
      window.officeModals.showToast(e.message, 'error');
    }
  }

  async cancelTask(taskId) {
    if (!confirm("Deseja realmente cancelar a execução desta tarefa?")) return;
    try {
      const res = await fetch(`/api/tasks/${taskId}/cancel`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Não foi possível cancelar');
      }
      window.officeModals.showToast('Tarefa cancelada com sucesso.', 'warning');
      this.loadTasks(false);
    } catch (e) {
      window.officeModals.showToast(e.message, 'error');
    }
  }

  async retryTask(taskId) {
    try {
      const res = await fetch(`/api/tasks/${taskId}/retry`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Não foi possível reiniciar');
      }
      window.officeModals.showToast('Tarefa colocada de volta na fila.', 'info');
      this.loadTasks(false);
    } catch (e) {
      window.officeModals.showToast(e.message, 'error');
    }
  }

  async decideApproval(taskId, approvalId, approved, notes, action = null) {
    const endpoint = approved
      ? `/api/tasks/${taskId}/approvals/${approvalId}/approve`
      : `/api/tasks/${taskId}/approvals/${approvalId}/reject`;

    try {
      const payload = { notes };
      if (!approved && action) payload.action = action;

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Falha ao processar decisão');
      }

      const updated = await res.json();
      this.upsertTask(updated);

      if (approved) {
        window.officeModals.showToast('Alteração aprovada com sucesso! O workflow continuará.', 'success');
      } else {
        window.officeModals.showToast('Proposta de alteração recusada.', 'warning');
      }
    } catch (e) {
      window.officeModals.showToast(e.message, 'error');
    }
  }

  updateHeaderBadge() {
    if (!this.kanbanBadge) return;
    const activeTasks = this.tasks.filter(t => !['COMPLETED', 'CANCELLED'].includes(t.state));
    const pendingApprovalCount = this.tasks.filter(t => t.state === 'WAITING_APPROVAL').length;

    if (activeTasks.length > 0) {
      this.kanbanBadge.style.display = 'inline-flex';
      this.kanbanBadge.textContent = activeTasks.length;
      if (pendingApprovalCount > 0) {
        this.kanbanBadge.classList.add('badge-alert-pulse');
        this.kanbanBadge.title = `${pendingApprovalCount} aprovação(ões) pendente(s)!`;
      } else {
        this.kanbanBadge.classList.remove('badge-alert-pulse');
        this.kanbanBadge.title = `${activeTasks.length} tarefas ativas`;
      }
    } else {
      this.kanbanBadge.style.display = 'none';
    }
  }

  escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
}

// Instância global singleton
window.officeKanban = new OfficeKanban();
