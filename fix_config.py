paths = [
    'C:/Users/BOTTA THARUN/Videos/oracle/oracle/oracle_ai/config.py',
    'C:/Users/BOTTA THARUN/OneDrive/Pictures/Screenshots/finllm (1)1/finllm/oracle_ai/config.py'
]

for p in paths:
    with open(p, 'r', encoding='utf-8') as f:
        text = f.read()
    text = text.replace('\r\n', '\n')
    text = text.replace('DB_PATH = os.getenv("ORACLE_DB", os.path.join(BASE, "data", "oracle_data.db"))',
                        'DB_PATH = os.getenv("ORACLE_AI_DB", os.path.join(BASE, "data", "oracle_data.db"))')
    text = text.replace('for _d in (os.path.dirname(DB_PATH), MODEL_DIR, UPLOAD_DIR):\n    os.makedirs(_d, exist_ok=True)',
                        'for _d in (os.path.dirname(DB_PATH), MODEL_DIR, UPLOAD_DIR):\n    if _d:\n        os.makedirs(_d, exist_ok=True)')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text.replace('\n', '\r\n'))
    print(f'Updated {p}')
