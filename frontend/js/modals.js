/**
 * AgentOffice 2D - Modals & Toast Manager (Etapa 4)
 * Gerencia abertura, fechamento, acessibilidade por teclado (Escape) e notificações Toast.
 */

class OfficeModals {
  constructor() {
    this.activeModals = [];
    this.toastContainer = null;
    this.init();
  }

  init() {
    document.addEventListener('DOMContentLoaded', () => {
      this.toastContainer = document.getElementById('toastContainer');
      if (!this.toastContainer) {
        this.toastContainer = document.createElement('div');
        this.toastContainer.id = 'toastContainer';
        this.toastContainer.className = 'toast-container';
        document.body.appendChild(this.toastContainer);
      }
    });

    // Tecla ESC fecha o modal mais recente no topo da pilha
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.activeModals.length > 0) {
        const topModal = this.activeModals[this.activeModals.length - 1];
        this.closeModal(topModal);
      }
    });

    // Clique fora do conteúdo fecha o modal ativo
    document.addEventListener('click', (e) => {
      if (e.target.classList.contains('modal-overlay') && e.target.classList.contains('active')) {
        this.closeModal(e.target);
      }
    });
  }

  getModal(target) {
    if (typeof target === 'string') {
      return document.getElementById(target);
    }
    return target;
  }

  showModal(target) {
    const el = this.getModal(target);
    if (!el) return;
    el.classList.add('active');
    if (!this.activeModals.includes(el)) {
      this.activeModals.push(el);
    }
    // Foca o primeiro elemento focável para acessibilidade
    const focusable = el.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (focusable) {
      focusable.focus();
    }
  }

  closeModal(target) {
    const el = this.getModal(target);
    if (!el) return;
    el.classList.remove('active');
    this.activeModals = this.activeModals.filter(m => m !== el);
  }

  closeAll() {
    [...this.activeModals].forEach(m => this.closeModal(m));
  }

  showToast(message, type = 'info', duration = 4000) {
    if (!this.toastContainer) {
      this.toastContainer = document.getElementById('toastContainer') || document.body;
    }

    const toast = document.createElement('div');
    toast.className = `toast-item toast-${type}`;

    const icons = {
      info: 'ℹ️',
      success: '✅',
      warning: '⚠️',
      error: '❌'
    };

    toast.innerHTML = `
      <div class="toast-icon">${icons[type] || 'ℹ️'}</div>
      <div class="toast-message">${message}</div>
      <button class="toast-close" type="button">&times;</button>
    `;

    toast.querySelector('.toast-close').addEventListener('click', () => {
      toast.classList.add('toast-fadeout');
      setTimeout(() => toast.remove(), 250);
    });

    this.toastContainer.appendChild(toast);

    if (duration > 0) {
      setTimeout(() => {
        if (toast.parentElement) {
          toast.classList.add('toast-fadeout');
          setTimeout(() => toast.remove(), 250);
        }
      }, duration);
    }
  }
}

// Instância global singleton
window.officeModals = new OfficeModals();
