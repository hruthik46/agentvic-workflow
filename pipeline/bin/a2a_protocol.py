"""A2A Protocol Server for KAIROS v4.0 (G7)
    
Agent-to-Agent messaging protocol based on JSON-RPC 2.0 over HTTP.
Enables interoperability between KAIROS agents and external agents.
"""
import json, uuid, time, hashlib, threading
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import urllib.request, urllib.parse
import os

# Default configuration
A2A_DEFAULT_PORT = 8093
A2A_ENDPOINT = "/a2a"
KARIOS_A2A_TOKEN = os.environ.get("KARIOS_A2A_TOKEN", "")


@dataclass
class AgentCard:
    """Agent capability discovery card."""
    name: str
    description: str
    version: str
    capabilities: List[str]
    endpoint: str
    supported_tasks: List[str]
    authentication: Dict[str, str]
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'description': self.description,
            'version': self.version,
            'capabilities': self.capabilities,
            'endpoint': self.endpoint,
            'supported_tasks': self.supported_tasks,
            'authentication': self.authentication
        }

@dataclass
class Task:
    """A2A task representation."""
    task_id: str
    gap_id: str
    phase: str
    payload: Dict[str, Any]
    status: str = "pending"  # pending, accepted, in_progress, completed, failed
    created_at: str = ""
    updated_at: str = ""
    result: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> dict:
        return {
            'task_id': self.task_id,
            'gap_id': self.gap_id,
            'phase': self.phase,
            'payload': self.payload,
            'status': self.status,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'result': self.result
        }

class A2AServer:
    """
    JSON-RPC 2.0 A2A Server for agent-to-agent communication.
    
    Endpoints:
    - POST /a2a - Send task to agent
    - GET  /a2a/agents - List all agent cards
    - GET  /a2a/agents/{agent_id} - Get specific agent card
    - POST /a2a/tasks/{task_id}/subscribe - SSE stream for task updates
    """
    
    def __init__(self, port: int = A2A_DEFAULT_PORT, 
                 orchestrator_url: str = "http://localhost:8080"):
        self.port = port
        self.orchestrator_url = orchestrator_url
        self.agent_cards: Dict[str, AgentCard] = {}
        self.tasks: Dict[str, Task] = {}
        self.subscribers: Dict[str, List[Callable]] = {}  # task_id -> [callbacks]
        self._sse_clients: Dict[str, list] = {}
        self._server = None
        self._running = False
        
    def register_agent(self, card: AgentCard):
        """Register an agent card for capability discovery."""
        self.agent_cards[card.name] = card
        
    def send_task(self, agent_id: str, task: Task) -> Dict[str, Any]:
        """
        Send a task to a specific agent via JSON-RPC 2.0.
        Returns JSON-RPC response.
        """
        request_id = f"req_{uuid.uuid4().hex[:8]}"
        
        jsonrpc_request = {
            'jsonrpc': '2.0',
            'method': 'agent.send_task',
            'params': {
                'agent_id': agent_id,
                'task': task.to_dict()
            },
            'id': request_id
        }
        
        # Find agent card
        agent_card = self.agent_cards.get(agent_id)
        if not agent_card:
            return {
                'jsonrpc': '2.0',
                'error': {
                    'code': -32602,
                    'message': f'Agent {agent_id} not found'
                },
                'id': request_id
            }
        
        # If target is ourselves (orchestrator), handle directly
        if agent_card.endpoint == self.orchestrator_url or agent_id == 'orchestrator':
            return self._handle_task_locally(agent_id, task, request_id)
        
        # Otherwise, forward via HTTP
        try:
            req = urllib.request.Request(
                agent_card.endpoint,
                data=json.dumps(jsonrpc_request).encode(),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {KARIOS_A2A_TOKEN}',
                }
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception as e:
            return {
                'jsonrpc': '2.0',
                'error': {
                    'code': -32603,
                    'message': f'Failed to send task: {str(e)}'
                },
                'id': request_id
            }
    
    def _handle_task_locally(self, agent_id: str, task: Task, request_id: str) -> Dict[str, Any]:
        """Handle task directly (same process)."""
        # Store task
        task.task_id = task.task_id or f"task_{uuid.uuid4().hex[:12]}"
        task.status = 'accepted'
        task.created_at = datetime.utcnow().isoformat() + 'Z'
        self.tasks[task.task_id] = task
        
        # Notify subscribers
        self._notify_subscribers(task.task_id)
        
        return {
            'jsonrpc': '2.0',
            'result': {
                'task_id': task.task_id,
                'status': task.status,
                'estimated_completion': datetime.utcnow().isoformat() + 'Z'
            },
            'id': request_id
        }
    
    def subscribe(self, task_id: str, callback: Callable):
        """Subscribe to task updates via SSE callback."""
        if task_id not in self.subscribers:
            self.subscribers[task_id] = []
        self.subscribers[task_id].append(callback)
        
    def _notify_subscribers(self, task_id: str):
        """Notify all subscribers of task update."""
        task = self.tasks.get(task_id)
        if not task:
            return
            
        for callback in self.subscribers.get(task_id, []):
            try:
                callback(task)
            except Exception as e:
                print(f"[A2A] Subscriber callback failed: {e}")
    
    def update_task_status(self, task_id: str, status: str, result: Dict[str, Any] = None):
        """Update task status and notify subscribers."""
        if task_id in self.tasks:
            self.tasks[task_id].status = status
            self.tasks[task_id].updated_at = datetime.utcnow().isoformat() + 'Z'
            if result:
                self.tasks[task_id].result = result
            self._notify_subscribers(task_id)
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        return self.tasks.get(task_id)
    
    def list_agents(self) -> List[AgentCard]:
        """List all registered agent cards."""
        return list(self.agent_cards.values())
    
    def get_agent_card(self, agent_id: str) -> Optional[AgentCard]:
        """Get agent card by ID."""
        return self.agent_cards.get(agent_id)
    def start(self):
        """Start the A2A HTTP server."""
        # FIX v5.4: Use HTTPServer with handler class (closure captures self),
        # not BaseHTTPRequestHandler instance which requires client_address.
        self._running = True
        handler = self._make_handler(self)
        self._server = HTTPServer(('0.0.0.0', self.port), handler)
        server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        server_thread.start()
        print(f"[A2A] Server started on port {self.port}")

    def _make_handler(self, a2a_server: 'A2AServer'):
        """Create a handler class bound to the given A2A server instance."""
        # Closure captures a2a_server — each HTTP request handler gets a reference to it.
        # This avoids passing A2AServerHTTP instance to HTTPServer (BaseHTTPRequestHandler
        # requires client_address and server at __init__, which isn't available here).
        class BoundHandler(BaseHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                # Capture a2a_server before super().__init__ sets self.server
                self.a2a_server = a2a_server
                super().__init__(*args, **kwargs)
            def do_GET(self):
                """Handle GET requests (agent cards, SSE subscriptions)."""
                parsed = urlparse(self.path)
                path = parsed.path

                if path == '/a2a/agents':
                    self._send_json(200, [card.to_dict() for card in self.a2a_server.list_agents()])

                elif path.startswith('/a2a/agents/'):
                    agent_id = path.split('/a2a/agents/')[1]
                    card = self.a2a_server.get_agent_card(agent_id)
                    if card:
                        self._send_json(200, card.to_dict())
                    else:
                        self._send_json(404, {'error': 'Agent not found'})

                elif path.startswith('/a2a/tasks/') and path.endswith('/subscribe'):
                    task_id = path.split('/a2a/tasks/')[1].replace('/subscribe', '')
                    self._handle_sse_subscribe(task_id)

                else:
                    self._send_json(404, {'error': 'Not found'})

            def do_POST(self):
                """Handle POST requests (send task, etc.)."""
                parsed = urlparse(self.path)
                path = parsed.path

                if path == '/a2a':
                    content_length = int(self.headers.get('Content-Length', 0))
                    body = self.rfile.read(content_length).decode()

                    try:
                        request = json.loads(body)
                        response = self._handle_jsonrpc(request)
                        self._send_json(200, response)
                    except json.JSONDecodeError:
                        self._send_json(400, {'error': 'Invalid JSON'})

                else:
                    self._send_json(404, {'error': 'Not found'})

            def _handle_jsonrpc(self, request: dict) -> dict:
                """Handle JSON-RPC 2.0 request."""
                method = request.get('method')
                params = request.get('params', {})
                request_id = request.get('id')

                if method == 'agent.send_task':
                    agent_id = params.get('agent_id')
                    task_data = params.get('task', {})

                    task = Task(
                        task_id=task_data.get('task_id', ''),
                        gap_id=task_data.get('gap_id', ''),
                        phase=task_data.get('phase', ''),
                        payload=task_data.get('payload', {})
                    )

                    result = self.a2a_server.send_task(agent_id, task)
                    return result

                elif method == 'agent.get_task':
                    task_id = params.get('task_id')
                    task = self.a2a_server.get_task(task_id)
                    if task:
                        return {'jsonrpc': '2.0', 'result': task.to_dict(), 'id': request_id}
                    return {'jsonrpc': '2.0', 'error': {'code': -32602, 'message': 'Task not found'}, 'id': request_id}

                elif method == 'agent.list_tasks':
                    tasks = [t.to_dict() for t in self.a2a_server.tasks.values()]
                    return {'jsonrpc': '2.0', 'result': tasks, 'id': request_id}

                else:
                    return {'jsonrpc': '2.0', 'error': {'code': -32601, 'message': f'Method {method} not found'}, 'id': request_id}

            def _handle_sse_subscribe(self, task_id: str):
                """Handle Server-Sent Events subscription for task updates."""
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'keep-alive')
                self.end_headers()

                def callback(task: Task):
                    data = f"data: {json.dumps(task.to_dict())}\n\n"
                    self.wfile.write(data.encode())

                self.a2a_server.subscribe(task_id, callback)

                try:
                    while True:
                        time.sleep(1)
                except:
                    pass

            def _send_json(self, status: int, data):
                """Send JSON response."""
                body = json.dumps(data).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                """Suppress default logging."""
                pass
        return BoundHandler

    def stop(self):
        """Stop the A2A server."""
        self._running = False
        if self._server:
            self._server.shutdown()


# Singleton instance
_a2a_server = None

def get_a2a_server() -> A2AServer:
    global _a2a_server
    if _a2a_server is None:
        _a2a_server = A2AServer()
    return _a2a_server


if __name__ == "__main__":
    import sys, os
    
    port = int(os.environ.get("A2A_PORT", "8080"))
    server = A2AServer(port=port)
    
    # Register default KAIROS agents
    server.register_agent(AgentCard(
        name="karios-architect",
        description="Research + Architecture agent for KAIROS Migration",
        version="4.0",
        capabilities=["web-search", "read_file", "write_file", "architecture-design", "code-analysis"],
        endpoint=f"http://localhost:{port}/a2a",
        supported_tasks=["phase-1-research", "phase-2-architecture"],
        authentication={"type": "bearer", "token_env": "KARIOS_A2A_TOKEN"}
    ))
    
    server.register_agent(AgentCard(
        name="karios-backend",
        description="Backend coder agent for KAIROS Migration",
        version="4.0",
        capabilities=["write_file", "read_file", "code-generation", "api-development"],
        endpoint=f"http://localhost:{port}/a2a",
        supported_tasks=["phase-3-coding"],
        authentication={"type": "bearer", "token_env": "KARIOS_A2A_TOKEN"}
    ))
    
    print(f"[A2A] Starting server on port {port}")
    server.start()
    
    # Keep running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
