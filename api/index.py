import os
import sys

# Flag serverless mode
os.environ.setdefault("VERCEL", "1")

# Ensure project root is on the Python path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Ensure finllm and oracle_ai directories are also in sys.path
finllm_dir = os.path.join(root_dir, "uploaded_model", "finllm")
if os.path.exists(finllm_dir) and finllm_dir not in sys.path:
    sys.path.insert(0, finllm_dir)

oracle_ai_dir = os.path.join(root_dir, "oracle_ai")
if os.path.exists(oracle_ai_dir) and oracle_ai_dir not in sys.path:
    sys.path.insert(0, oracle_ai_dir)

try:
    import server
    app = server.app
except Exception as _init_err:
    import traceback
    _init_tb = traceback.format_exc()
    print("[VERCEL INIT ERROR]:", _init_err)
    print(_init_tb)

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI(title="ORACLE Diagnostic Server")

    @app.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE"])
    def diagnostic_fallback(path_name: str):
        return JSONResponse(
            status_code=500,
            content={
                "status": "initialization_failed",
                "error": str(_init_err),
                "traceback": _init_tb,
                "hint": "Check Vercel Runtime Logs for module errors."
            }
        )
