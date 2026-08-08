"""
Servidor Web de Pruebas (Capa IT)
Orquesta el subproceso OT sin dependencias de siemens_tia_scripting.
"""

import asyncio
import json
import sys
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI(title="ZC Automation Suite - Test Harness")

WORKER_SCRIPT = Path(__file__).parent / "main.py"
TIMEOUT_SECS = 180.0

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>ZC Automation Suite - Test Web</title>
    <style>
        body { font-family: system-ui, sans-serif; background: #1e1e1e; color: #fff; padding: 20px; }
        .container { max-width: 800px; margin: auto; }
        textarea { width: 100%; height: 150px; background: #2d2d2d; color: #00ff00; font-family: monospace; padding: 10px; border: 1px solid #444; }
        button { background: #007acc; color: white; border: none; padding: 10px 20px; cursor: pointer; margin-top: 10px; font-weight: bold; }
        button:hover { background: #005f9e; }
        pre { background: #000; padding: 15px; border: 1px solid #444; overflow-x: auto; white-space: pre-wrap; }
        .success { color: #00ff00; }
        .error { color: #ff4444; }
    </style>
</head>
<body>
    <div class="container">
        <h2>Motor OT - Ejecución Directa</h2>
        <p>Introduce el payload JSON a enviar al subproceso <code>worker_tia.py</code>:</p>
        <textarea id="payloadInput">{
  "command": "list_plcs",
  "args": {}
}</textarea>
        <br>
        <button onclick="sendCommand()">Ejecutar Comando</button>
        
        <h3>Respuesta del Subproceso:</h3>
        <pre id="outputArea">Esperando ejecución...</pre>
    </div>

    <script>
        async function sendCommand() {
            const outputArea = document.getElementById('outputArea');
            const payloadStr = document.getElementById('payloadInput').value;
            
            outputArea.className = '';
            outputArea.textContent = 'Ejecutando subproceso OT... (Espera, TIA Portal puede tardar)';
            
            try {
                const payload = JSON.parse(payloadStr);
                const response = await fetch('/api/v1/worker', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                const data = await response.json();
                outputArea.textContent = JSON.stringify(data, null, 2);
                
                if (response.ok && data.ok) {
                    outputArea.className = 'success';
                } else {
                    outputArea.className = 'error';
                }
            } catch (err) {
                outputArea.className = 'error';
                outputArea.textContent = 'Error de conexión o JSON inválido: ' + err.message;
            }
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Sirve la interfaz HTML estática."""
    return HTML_TEMPLATE

@app.post("/api/v1/worker")
async def execute_worker(request: Request):
    """
    Endpoint que actúa como Gateway.
    Lanza el subproceso efímero y canaliza el IPC.
    """
    try:
        payload = await request.json()
        payload_bytes = json.dumps(payload).encode("utf-8")
        
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", str(WORKER_SCRIPT), "--worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(input=payload_bytes),
                timeout=TIMEOUT_SECS
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"ok": False, "error": f"Timeout tras {TIMEOUT_SECS}s. Subproceso aniquilado."}
            
        stdout_text = stdout_b.decode("utf-8", errors="replace").strip()
        
        # Filtro de seguridad para capturar solo la última línea JSON emitida por el worker
        json_response = None
        for line in reversed(stdout_text.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    json_response = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
                    
        if json_response is not None:
            return json_response
            
        stderr_text = stderr_b.decode("utf-8", errors="replace").strip()
        return {"ok": False, "error": "El worker no devolvió JSON válido.", "stdout": stdout_text, "stderr": stderr_text}

    except Exception as e:
        return {"ok": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    # Se ejecuta en el puerto 8000
    uvicorn.run(app, host="127.0.0.1", port=8000)