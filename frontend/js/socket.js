/**
 * AgentOffice 2D - WebSocket Client (Etapa 4: Robust Reconnection & Protocol Compliance)
 * Gerencia a conexão com o backend, reconexão progressiva sem duplicação de sockets,
 * despacho de eventos tipados e solicitação de ressincronização com a API REST.
 */

class OfficeSocket {
  constructor() {
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectDelay = 5000;
    this.reconnectTimer = null;
    this.hasEverConnected = false;
    this.handlers = new Map();
  }

  connect() {
    // Evitar conexões duplicadas simultâneas
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log("[WebSocket] Conectado ao servidor do escritório.");
        this.reconnectAttempts = 0;
        const isReconnect = this.hasEverConnected;
        this.hasEverConnected = true;

        this.emit('connection.status', { connected: true, isReconnect });
        if (isReconnect) {
          console.log("[WebSocket] Reconexão detectada. Disparando evento 'connection.reconnected'...");
          this.emit('connection.reconnected', { connected: true });
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const eventType = data.event || data.type;
          if (eventType) {
            this.emit(eventType, data);
          }
          // Dispara também para ouvintes genéricos
          this.emit('*', data);
        } catch (err) {
          console.error("[WebSocket] Erro ao decodificar mensagem JSON:", err);
        }
      };

      this.ws.onclose = (event) => {
        console.warn(`[WebSocket] Conexão encerrada (código ${event.code}). Agendando reconexão...`);
        this.ws = null;
        this.emit('connection.status', { connected: false, code: event.code });
        this.scheduleReconnect();
      };

      this.ws.onerror = (err) => {
        console.error("[WebSocket] Erro na conexão:", err);
      };
    } catch (e) {
      console.error("[WebSocket] Falha ao iniciar WebSocket:", e);
      this.scheduleReconnect();
    }
  }

  scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), this.maxReconnectDelay);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  on(eventType, callback) {
    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, []);
    }
    this.handlers.get(eventType).push(callback);
  }

  off(eventType, callback) {
    if (!this.handlers.has(eventType)) return;
    const list = this.handlers.get(eventType).filter(cb => cb !== callback);
    this.handlers.set(eventType, list);
  }

  emit(eventType, data) {
    const callbacks = this.handlers.get(eventType) || [];
    callbacks.forEach(cb => {
      try {
        cb(data);
      } catch (e) {
        console.error(`Erro no listener para [${eventType}]:`, e);
      }
    });
  }

  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }
}

// Instância global singleton
window.officeSocket = new OfficeSocket();
