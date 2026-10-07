import re

with open('ui/phoebe_ui.py', 'r', encoding='utf-8') as f:
    code = f.read()

replacement = """if __name__ in {"__main__", "__mp_main__"}:
    from nicegui import ui, app
    from fastapi import Request
    from fastapi.responses import PlainTextResponse

    @app.exception_handler(404)
    async def custom_404_handler(request: Request, exc):
        return PlainTextResponse("Not Found", status_code=404)

    # Initialize API clients
    session_api = SessionAPI(base_url="http://localhost:8001")
    phoebe_api = PhoebeAPI(base_url="http://localhost:8001")

    # Create UI with API instances
    ui_app = PhoebeUI(session_api=session_api, phoebe_api=phoebe_api)

    ui.run(host='0.0.0.0', port=8082, title='PHOEBE Lab UI', reload=False, favicon='✨')
"""

code = re.sub(r"if __name__ in \{.*", replacement, code, flags=re.DOTALL)

with open('ui/phoebe_ui.py', 'w', encoding='utf-8') as f:
    f.write(code)

print('Fixed final')
