"""Dev 入口:`python run.py` 启动开发服务器。

生产请用 `gunicorn -w 4 -b 0.0.0.0:5000 'run:app'`。
"""

from __future__ import annotations

import os

from app import create_app
from cli import register_cli

app = create_app()
register_cli(app)


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host=host, port=port, debug=debug, use_reloader=False)
