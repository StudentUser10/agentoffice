# 🏢 AgentOffice 2D

Interface visual de escritório em pixel art para criar e interagir com agentes de Inteligência Artificial em execução local ou remota, com motor de gameplay 2D top-down e orquestração hierárquica (Supervisor & Workers).

---

## 🎮 Funcionalidades da Etapa 2

1. **Gameplay 2D Top-Down no Canvas Nativo**:
   - Controle do jogador pelo escritório com `W`, `A`, `S`, `D` ou Setas do teclado.
   - Cálculo de física e velocidade constante com delta time (`requestAnimationFrame`).
   - Caixas delimitadoras (AABB) com bloqueio de passagem contra paredes, mesas, bebedouro e quadro de avisos.
   - Interação por proximidade: a menos de 48px de uma mesa ou agente, surge o indicador flutuante `[E] Interagir`. Pressionar `E` abre a contratação ou o chat.
   - Seleção também disponível clicando diretamente sobre a mesa com o mouse.
2. **Hierarquia de Agentes (Supervisor & Workers)**:
   - Configuração de papéis: `Solo` (Autônomo), `Supervisor` (Tech Lead) e `Worker` (Subordinado).
   - Quando configurado como Worker, vincula-se ao Supervisor selecionado.
3. **Orquestração Autônoma e Física no Canvas**:
   - Ao receber uma tarefa, o **Supervisor** entra em estado `THINKING` 💭 e decompõe o objetivo em subtarefas estruturadas em JSON.
   - Cada **Worker** entra em estado `WORKING` ⚡ e executa sua parte com o modelo LLM real configurado.
   - Concluída a subtarefa, o Worker entra em estado `WALKING` 🚶 e **caminha fisicamente até a mesa do supervisor** para entregar o relatório (`REPORTING` 📄 com balão de fala), retornando em seguida à própria mesa.
   - O Supervisor consolida os relatórios dos subordinados e gera a resposta final em streaming ao vivo para o usuário.
4. **Painel de Atividades do Escritório**:
   - Log visual em tempo real registrando deslocamentos, estados e relatórios entregues no escritório.

---

## 🚀 Como Iniciar

### 1. Instalação das Dependências

```bash
pip install -r requirements.txt
```

### 2. Iniciar o Aplicativo

```bash
python main.py
```

O aplicativo abrirá automaticamente `http://127.0.0.1:8000` no seu navegador padrão.

---

## ⌨️ Controles do Escritório

- **W, A, S, D** ou **Setas**: Movimentar seu avatar pelo escritório.
- **E**: Interagir com a mesa ou agente mais próximo.
- **Clique do Mouse**: Selecionar qualquer mesa diretamente no Canvas.
- **Enter**: Enviar mensagem ou objetivo na janela de chat do agente.

---

## 🧪 Testes Automatizados

Para rodar todos os testes de unidade e integração:

```bash
# Testes da Etapa 1 (Persistência, Segurança e Endpoints Básicos)
python tests/test_stage1.py

# Testes da Etapa 2 (Hierarquia, Waypoints de Mesas e CRUD de Agentes)
python tests/test_stage2.py

# Testes da Etapa 2 Ponta a Ponta (WebSocket em tempo real + Chat Orchestrator)
python tests/test_stage2_integration.py
```

---

## 📌 Status Atual e Limitações

### O que está implementado:
- [x] Motor de Canvas nativo 2D, zero-build, zero dependência de CDN.
- [x] Movimentação fluida do jogador com colisão física AABB.
- [x] Interação por proximidade (`[E]`) e por clique.
- [x] Modelos de dados com papéis hierárquicos (`Solo`, `Supervisor`, `Worker`) e estados (`IDLE`, `THINKING`, `WORKING`, `WALKING`, `REPORTING`).
- [x] Waypoints de assento (`seat_pos`) e atendimento (`front_pos`) em todas as 6 mesas.
- [x] Orquestrador real assíncrono com decomposição de tarefas e delegação para workers.
- [x] Movimentação física do NPC até a mesa do supervisor para entrega de relatórios antes de retornar.
- [x] Chat com streaming de texto em tempo real via WebSocket.
- [x] Painel retrô de logs de eventos do escritório.

### Limitações conhecidas para etapas seguintes:
- ⚠️ **Execução de Ferramentas / Shell**: Mantida desativada por estritas razões de segurança do MVP.
