from flask import Flask
from config import Config
from db import init_db

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    init_db()

    from modules.core.routes import core_bp
    app.register_blueprint(core_bp)

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)