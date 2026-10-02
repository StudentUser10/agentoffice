/**
 * AgentOffice 2D - System Diagnostics Panel Component (Etapa 5)
 * Gerencia o painel de integridade do sistema: LLM Local / Ollama,
 * permissões de escrita do Workspace, integridade dos arquivos JSON e recursos.
 */

class OfficeDiagnostics {
  constructor() {
    this.diagData = null;
    this.isRunning = false;

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
  }

  cacheElements() {
    this.modal = document.getElementById('diagnosticsModal');
    this.closeBtn = document.getElementById('closeDiagnosticsBtn');
    this.openBtn = document.getElementById('openDiagnosticsBtn');
    this.runBtn = document.getElementById('runDiagnosticsBtn');

    this.overallDot = document.getElementById('diagStatusDot');
    this.overallText = document.getElementById('diagStatusText');
    this.timestampEl = document.getElementById('diagTimestamp');
    this.itemsContainer = document.getElementById('diagItemsContainer');
    this.systemInfoContainer = document.getElementById('diagSystemInfo');
  }

  setupEventListeners() {
    if (this.openBtn) {
      this.openBtn.addEventListener('click', () => this.openModal());
    }
    if (this.closeBtn) {
      this.closeBtn.addEventListener('click', () => {
        if (window.officeModals) {
          window.officeModals.closeModal('diagnosticsModal');
        }
      });
    }
    if (this.runBtn) {
      this.runBtn.addEventListener('click', () => this.runDiagnostics());
    }
  }

  setupWebSocketListeners() {
    const sock = window.officeSocket;
    if (!sock) return;

    sock.on('system.diagnostic_result', (data) => {
      const payload = data.payload || data;
      this.renderDiagnostics(payload);
    });
  }

  openModal() {
    if (window.officeModals) {
      window.officeModals.showModal('diagnosticsModal');
    }
    this.loadDiagnostics(false);
  }

  async loadDiagnostics(triggerRun = false) {
    if (this.isRunning) return;

    if (triggerRun) {
      this.isRunning = true;
      if (this.runBtn) {
        this.runBtn.disabled = true;
        this.runBtn.innerHTML = '<span>⏳</span> Executando...';
      }
    }

    try {
      const url = triggerRun ? '/api/system/diagnostics/run' : '/api/system/diagnostics';
      const method = triggerRun ? 'POST' : 'GET';
      const res = await fetch(url, { method });

      if (res.ok) {
        const data = await res.json();
        this.renderDiagnostics(data);
        if (triggerRun && window.officeModals) {
          window.officeModals.showToast('Diagnóstico do sistema concluído.', 'success');
        }
      } else {
        if (window.officeModals) {
          window.officeModals.showToast('Erro ao carregar diagnóstico do sistema.', 'error');
        }
      }
    } catch (err) {
      console.error('[Diagnostics] Erro na requisição:', err);
      if (window.officeModals) {
        window.officeModals.showToast('Falha na comunicação de diagnóstico.', 'error');
      }
    } finally {
      this.isRunning = false;
      if (this.runBtn) {
        this.runBtn.disabled = false;
        this.runBtn.innerHTML = '<span>🔄</span> Executar Diagnóstico Agora';
      }
    }
  }

  runDiagnostics() {
    this.loadDiagnostics(true);
  }

  renderDiagnostics(data) {
    if (!data) return;
    this.diagData = data;

    // 1. Status Geral Consolidado
    const status = data.overall_status || 'warning';
    const statusMap = {
      healthy: { text: 'Sistema Saudável & Operacional', color: '#10b981', dotClass: 'dot-online' },
      warning: { text: 'Atenção Necessária', color: '#f59e0b', dotClass: 'dot-busy' },
      error: { text: 'Falha ou Inconsistência Detectada', color: '#f43f5e', dotClass: 'dot-offline' }
    };
    const info = statusMap[status] || statusMap.warning;

    if (this.overallText) {
      this.overallText.textContent = info.text;
      this.overallText.style.color = info.color;
    }
    if (this.overallDot) {
      this.overallDot.className = `status-dot ${info.dotClass}`;
    }

    // Timestamp
    if (this.timestampEl) {
      const dateStr = data.timestamp ? new Date(data.timestamp * 1000).toLocaleTimeString() : new Date().toLocaleTimeString();
      this.timestampEl.textContent = `Última verificação: ${dateStr}`;
    }

    // 2. Itens de Diagnóstico
    if (this.itemsContainer) {
      this.itemsContainer.innerHTML = '';

      (data.items || []).forEach(item => {
        const itemCard = document.createElement('div');
        itemCard.className = `diag-card diag-status-${item.status}`;

        const iconMap = {
          'Provedor LLM & IA Local': '🖥️',
          'Autenticação & Chaves': '🔑',
          'Workspace Sandbox & I/O': '📁',
          'Persistência & Integridade JSON': '💾'
        };
        const icon = iconMap[item.name] || '⚙️';

        const badgeClass = item.status === 'healthy' ? 'badge-completed' : (item.status === 'warning' ? 'badge-waiting' : 'badge-failed');
        const badgeText = item.status === 'healthy' ? 'OK' : (item.status === 'warning' ? 'ATENÇÃO' : 'ERRO');

        let latencyHtml = '';
        if (item.latency_ms !== null && item.latency_ms !== undefined && item.latency_ms > 0) {
          latencyHtml = `<span class="diag-latency">${item.latency_ms} ms</span>`;
        }

        let detailsHtml = '';
        if (item.details && Object.keys(item.details).length > 0) {
          const detailEntries = Object.entries(item.details)
            .filter(([k]) => !['api_keys', 'secret', 'key'].includes(k.toLowerCase()))
            .map(([k, v]) => `<code>${k}: ${Array.isArray(v) ? v.join(', ') : JSON.stringify(v)}</code>`)
            .join(' • ');
          if (detailEntries) {
            detailsHtml = `<div class="diag-details-row">${detailEntries}</div>`;
          }
        }

        itemCard.innerHTML = `
          <div class="diag-card-header">
            <div class="diag-card-title">
              <span class="diag-icon">${icon}</span>
              <strong>${item.name}</strong>
            </div>
            <div class="diag-badges">
              ${latencyHtml}
              <span class="kanban-badge ${badgeClass}">${badgeText}</span>
            </div>
          </div>
          <div class="diag-card-message">${item.message}</div>
          ${detailsHtml}
        `;

        this.itemsContainer.appendChild(itemCard);
      });
    }

    // 3. Informações do Ambiente e Servidor
    if (this.systemInfoContainer && data.system_info) {
      const s = data.system_info;
      this.systemInfoContainer.innerHTML = `
        <div class="sys-info-pill"><span>💻 SO:</span> ${s.os || 'Local'} (${s.os_release || ''})</div>
        <div class="sys-info-pill"><span>🐍 Python:</span> ${s.python_version || '3.x'}</div>
        <div class="sys-info-pill"><span>⚙️ PID:</span> ${s.process_pid || '-'}</div>
        <div class="sys-info-pill"><span>🌐 Host:</span> ${s.server_host || '127.0.0.1:8000'}</div>
      `;
    }
  }
}

// Instância global singleton
window.officeDiagnostics = new OfficeDiagnostics();
window.openDiagnosticsModal = () => window.officeDiagnostics.openModal();
