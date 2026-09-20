import os
import time
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kubepreview-app")

app = FastAPI(title="KubePreview Staging App")

# Environment Metadata injected via Kubernetes Pod Spec Downward API & Configs
PR_NUMBER = os.getenv("PR_NUMBER", "N/A")
POD_NAME = os.getenv("POD_NAME", "unknown-pod")
POD_NAMESPACE = os.getenv("POD_NAMESPACE", "default")
NODE_NAME = os.getenv("NODE_NAME", "unknown-node")

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "kubepreview_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres_password")

def get_db_connection():
    """
    Establishes a PostgreSQL database connection with exponential backoff / retry
    loop to handle cold-start container startup gracefully.
    """
    max_retries = 5
    base_delay = 2
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Connecting to DB {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME} (Attempt {attempt}/{max_retries})...")
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                connect_timeout=3
            )
            logger.info("Database connection established successfully!")
            return conn
        except Exception as e:
            logger.warning(f"Database connection attempt {attempt} failed: {e}")
            if attempt == max_retries:
                logger.error("Max DB connection retries reached.")
                raise e
            sleep_time = base_delay * attempt
            logger.info(f"Retrying in {sleep_time} seconds...")
            time.sleep(sleep_time)

@app.get("/healthz")
def healthz():
    """Healthcheck endpoint for Kubernetes liveness & readiness probes."""
    try:
        conn = get_db_connection()
        conn.close()
        return {
            "status": "ok",
            "database": "connected",
            "pr_number": PR_NUMBER,
            "namespace": POD_NAMESPACE,
            "pod_name": POD_NAME
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection failure: {str(e)}")

@app.get("/", response_class=HTMLResponse)
def index():
    db_records = []
    db_status = "Connected"
    db_error = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, feature_key, feature_name, status, created_at FROM preview_features ORDER BY id ASC;")
        db_records = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as e:
        db_status = "Disconnected / Error"
        db_error = str(e)

    # Construct table rows
    rows_html = ""
    if db_records:
        for r in db_records:
            status_color = "#10b981" if r['status'] == 'ACTIVE' else "#f59e0b" if r['status'] == 'PENDING' else "#6b7280"
            rows_html += f"""
            <tr class="hover:bg-gray-800/40 transition-colors">
                <td class="px-4 py-3 border-b border-gray-800 text-gray-400 font-mono text-xs">{r['id']}</td>
                <td class="px-4 py-3 border-b border-gray-800 font-mono text-cyan-400 font-semibold">{r['feature_key']}</td>
                <td class="px-4 py-3 border-b border-gray-800 text-gray-200 text-sm">{r['feature_name']}</td>
                <td class="px-4 py-3 border-b border-gray-800">
                    <span class="px-2.5 py-1 text-xs font-semibold rounded-full" style="background-color: {status_color}22; color: {status_color}; border: 1px solid {status_color}44;">
                        {r['status']}
                    </span>
                </td>
                <td class="px-4 py-3 border-b border-gray-800 text-gray-500 text-xs font-mono">{r['created_at']}</td>
            </tr>
            """
    elif db_error:
        rows_html = f'<tr><td colspan="5" class="px-4 py-6 text-center text-red-400 font-mono text-sm">Database Error: {db_error}</td></tr>'
    else:
        rows_html = '<tr><td colspan="5" class="px-4 py-6 text-center text-gray-500 text-sm">No data found in ephemeral database.</td></tr>'

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>KubePreview Staging Sandbox - PR #{PR_NUMBER}</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Inter', sans-serif; background: #0b0f19; color: #f3f4f6; }}
            .glass {{ background: rgba(17, 24, 39, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }}
            .gradient-text {{ background: linear-gradient(135deg, #38bdf8 0%, #818cf8 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        </style>
    </head>
    <body class="min-h-screen p-6 md:p-12">
        <div class="max-w-5xl mx-auto space-y-8">
            
            <!-- Header -->
            <div class="glass p-8 rounded-2xl shadow-2xl flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
                <div>
                    <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20 mb-3">
                        <span class="w-2 h-2 rounded-full bg-blue-400 animate-pulse"></span>
                        Preview Environment Live
                    </div>
                    <h1 class="text-3xl font-bold tracking-tight">Welcome to <span class="gradient-text">KubePreview</span> Sandbox</h1>
                    <p class="text-gray-400 text-sm mt-1">Automated Multi-Tenant Staging Environment for Pull Request #{PR_NUMBER}</p>
                </div>
                <div class="flex items-center gap-3">
                    <span class="text-xs px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 font-mono">TTL: 2 Hours</span>
                    <span class="text-xs px-3 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">Status: Healthy</span>
                </div>
            </div>

            <!-- Metadata Cards Grid -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div class="glass p-6 rounded-xl space-y-2">
                    <span class="text-xs uppercase tracking-wider text-gray-400 font-medium">Pull Request ID</span>
                    <div class="text-2xl font-bold font-mono text-cyan-400">PR #{PR_NUMBER}</div>
                    <div class="text-xs text-gray-500 font-mono">pr-{PR_NUMBER}.127.0.0.1.nip.io</div>
                </div>
                
                <div class="glass p-6 rounded-xl space-y-2">
                    <span class="text-xs uppercase tracking-wider text-gray-400 font-medium">Kubernetes Namespace</span>
                    <div class="text-xl font-bold font-mono text-purple-400 truncate">{POD_NAMESPACE}</div>
                    <div class="text-xs text-gray-500">Quota: 600m CPU / 512Mi RAM</div>
                </div>

                <div class="glass p-6 rounded-xl space-y-2">
                    <span class="text-xs uppercase tracking-wider text-gray-400 font-medium">Pod Name</span>
                    <div class="text-sm font-semibold font-mono text-amber-300 truncate">{POD_NAME}</div>
                    <div class="text-xs text-gray-500 font-mono">Node: {NODE_NAME}</div>
                </div>
            </div>

            <!-- Ephemeral Database Table -->
            <div class="glass rounded-2xl overflow-hidden border border-gray-800 shadow-xl">
                <div class="p-6 border-b border-gray-800 flex justify-between items-center">
                    <div>
                        <h2 class="text-lg font-semibold text-gray-100">Ephemeral PostgreSQL Database Records</h2>
                        <p class="text-xs text-gray-400">Queried dynamically from host <code class="text-indigo-300">{DB_HOST}:{DB_PORT}</code></p>
                    </div>
                    <span class="text-xs px-3 py-1 rounded-full font-mono font-medium" style="background: rgba(16, 185, 129, 0.1); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.2);">
                        {db_status}
                    </span>
                </div>
                
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="bg-gray-900/80 text-xs font-semibold text-gray-400 uppercase tracking-wider border-b border-gray-800">
                                <th class="px-4 py-3">ID</th>
                                <th class="px-4 py-3">Feature Key</th>
                                <th class="px-4 py-3">Feature Description</th>
                                <th class="px-4 py-3">Status</th>
                                <th class="px-4 py-3">Seeded Timestamp</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows_html}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Footer -->
            <div class="text-center text-xs text-gray-500 pt-4">
                Powered by <span class="text-gray-400 font-semibold">KubePreview Orchestrator</span> &bull; Cloud-Native Multi-Tenant Preview Infrastructure
            </div>

        </div>
    </body>
    </html>
    """
    return html_content
