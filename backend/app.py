"""
Simplified Flask Application Entry Point
"""
import os
import sys
import logging
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy.engine import Engine
import sqlite3
from sqlalchemy.exc import SQLAlchemyError
from flask_migrate import Migrate

# Load environment variables from project root .env file
_project_root = Path(__file__).parent.parent
_env_file = _project_root / '.env'
if os.getenv('TESTING') != 'true':
    load_dotenv(dotenv_path=_env_file, override=True)

from flask import Flask
from flask_cors import CORS
from models import db
from config import Config
from controllers.material_controller import material_bp, material_global_bp
from controllers.reference_file_controller import reference_file_bp
from controllers.settings_controller import settings_bp
from controllers.translate_controller import translate_bp
from controllers import project_bp, page_bp, template_bp, user_template_bp, export_bp, file_bp, restyle_bp, auth_bp, task_bp


# Enable SQLite WAL mode for all connections
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """
    Enable WAL mode and related PRAGMAs for each SQLite connection.
    Registered once at import time to avoid duplicate handlers when
    create_app() is called multiple times.
    """
    # Only apply to SQLite connections
    if not isinstance(dbapi_conn, sqlite3.Connection):
        return

    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")  # 30 seconds timeout
    finally:
        cursor.close()


def create_app():
    """Application factory"""
    app = Flask(__name__)

    _preflight_env_or_raise()
    
    # Load configuration from Config class
    app.config.from_object(Config)
    app.config['IMAGE_PROVIDER_FORMAT'] = os.getenv(
        'IMAGE_PROVIDER_FORMAT',
        app.config.get('AI_PROVIDER_FORMAT', 'gemini')
    )
    
    # Override with environment-specific paths (use absolute path)
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    instance_dir = os.path.join(backend_dir, 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    
    db_path = os.path.join(instance_dir, 'database.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    
    # Ensure upload folder exists
    project_root = os.path.dirname(backend_dir)
    upload_folder = os.path.join(project_root, 'uploads')
    os.makedirs(upload_folder, exist_ok=True)
    app.config['UPLOAD_FOLDER'] = upload_folder
    
    # CORS configuration (parse from environment)
    raw_cors = os.getenv('CORS_ORIGINS', 'http://localhost:3000')
    if raw_cors.strip() == '*':
        cors_origins = '*'
    else:
        cors_origins = [o.strip() for o in raw_cors.split(',') if o.strip()]
    app.config['CORS_ORIGINS'] = cors_origins

    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() in ('1', 'true', 'yes')
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
    
    # Initialize logging (log to stdout so Docker can capture it)
    log_level = getattr(logging, app.config['LOG_LEVEL'], logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    
    # 设置第三方库的日志级别，避免过多的DEBUG日志
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('werkzeug').setLevel(logging.INFO)  # Flask开发服务器日志保持INFO

    # Initialize extensions
    db.init_app(app)
    supports_credentials = True
    if supports_credentials and cors_origins == '*':
        logging.warning('CORS_ORIGINS="*" is invalid when credentials are enabled, fallback to http://localhost:3000')
        cors_origins = ['http://localhost:3000']
        app.config['CORS_ORIGINS'] = cors_origins
    CORS(app, origins=cors_origins, supports_credentials=supports_credentials)
    # Database migrations (Alembic via Flask-Migrate)
    Migrate(app, db)
    
    # Register blueprints
    app.register_blueprint(project_bp)
    app.register_blueprint(page_bp)
    app.register_blueprint(template_bp)
    app.register_blueprint(user_template_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(file_bp)
    app.register_blueprint(material_bp)
    app.register_blueprint(material_global_bp)
    app.register_blueprint(reference_file_bp, url_prefix='/api/reference-files')
    app.register_blueprint(settings_bp)
    app.register_blueprint(restyle_bp)
    app.register_blueprint(translate_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(task_bp)

    # Health check endpoint
    @app.route('/health')
    def health_check():
        return {'status': 'ok', 'message': 'Banana Slides API is running'}
    
    # Output language endpoint
    @app.route('/api/output-language', methods=['GET'])
    def get_output_language():
        """Return output language from current runtime config (env-managed)."""
        return {'data': {'language': app.config.get('OUTPUT_LANGUAGE', Config.OUTPUT_LANGUAGE)}}

    # Root endpoint
    @app.route('/')
    def index():
        return {
            'name': 'Banana Slides API',
            'version': '1.0.0',
            'description': 'AI-powered PPT generation service',
            'endpoints': {
                'health': '/health',
                'api_docs': '/api',
                'projects': '/api/projects'
            }
        }
    
    return app


def _load_settings_to_config(app):
    """Load settings from database and apply to app.config on startup"""
    from models import Settings
    try:
        settings = Settings.get_settings()
        
        # Load AI provider format (always sync, has default value)
        if settings.ai_provider_format:
            app.config['AI_PROVIDER_FORMAT'] = settings.ai_provider_format
            logging.info(f"Loaded AI_PROVIDER_FORMAT from settings: {settings.ai_provider_format}")
        
        # Load API configuration
        # Note: We load even if value is None/empty to allow clearing settings
        # But we only log if there's an actual value
        if settings.api_base_url is not None:
            # 将数据库中的统一 API Base 同步到 Google/OpenAI 两个配置，确保覆盖环境变量
            app.config['GOOGLE_API_BASE'] = settings.api_base_url
            app.config['OPENAI_API_BASE'] = settings.api_base_url
            if settings.api_base_url:
                logging.info(f"Loaded API_BASE from settings: {settings.api_base_url}")
            else:
                logging.info("API_BASE is empty in settings, using env var or default")

        if settings.api_key is not None:
            # 同步到两个提供商的 key，数据库优先于环境变量
            app.config['GOOGLE_API_KEY'] = settings.api_key
            app.config['OPENAI_API_KEY'] = settings.api_key
            if settings.api_key:
                logging.info("Loaded API key from settings")
            else:
                logging.info("API key is empty in settings, using env var or default")

        # Load image generation settings
        app.config['DEFAULT_RESOLUTION'] = settings.image_resolution
        app.config['DEFAULT_ASPECT_RATIO'] = settings.image_aspect_ratio
        logging.info(f"Loaded image settings: {settings.image_resolution}, {settings.image_aspect_ratio}")

        # Load worker settings
        app.config['MAX_DESCRIPTION_WORKERS'] = settings.max_description_workers
        app.config['MAX_IMAGE_WORKERS'] = settings.max_image_workers
        logging.info(f"Loaded worker settings: desc={settings.max_description_workers}, img={settings.max_image_workers}")

        # Load model settings (FIX for Issue #136: these were missing before)
        if settings.text_model:
            app.config['TEXT_MODEL'] = settings.text_model
            logging.info(f"Loaded TEXT_MODEL from settings: {settings.text_model}")
        
        if settings.image_model:
            app.config['IMAGE_MODEL'] = settings.image_model
            logging.info(f"Loaded IMAGE_MODEL from settings: {settings.image_model}")
        
        # Load MinerU settings
        if settings.mineru_api_base:
            app.config['MINERU_API_BASE'] = settings.mineru_api_base
            logging.info(f"Loaded MINERU_API_BASE from settings: {settings.mineru_api_base}")
        
        if settings.mineru_token:
            app.config['MINERU_TOKEN'] = settings.mineru_token
            logging.info("Loaded MINERU_TOKEN from settings")
        
        # Load image caption model
        if settings.image_caption_model:
            app.config['IMAGE_CAPTION_MODEL'] = settings.image_caption_model
            logging.info(f"Loaded IMAGE_CAPTION_MODEL from settings: {settings.image_caption_model}")
        
        # Load output language
        if settings.output_language:
            app.config['OUTPUT_LANGUAGE'] = settings.output_language
            logging.info(f"Loaded OUTPUT_LANGUAGE from settings: {settings.output_language}")
        
        # Load reasoning mode settings (separate for text and image)
        app.config['ENABLE_TEXT_REASONING'] = settings.enable_text_reasoning
        app.config['TEXT_THINKING_BUDGET'] = settings.text_thinking_budget
        app.config['IMAGE_THINKING_LEVEL'] = settings.image_thinking_level
        logging.info(f"Loaded reasoning config: text={settings.enable_text_reasoning}(budget={settings.text_thinking_budget}), image_thinking_level={settings.image_thinking_level}")
        
        # Load Baidu OCR settings
        if settings.baidu_ocr_api_key:
            app.config['BAIDU_OCR_API_KEY'] = settings.baidu_ocr_api_key
            logging.info("Loaded BAIDU_OCR_API_KEY from settings")

    except Exception as e:
        logging.warning(f"Could not load settings from database: {e}")


def _preflight_env_or_raise() -> None:
    """Fail fast on invalid required envs for env-only mode."""
    provider = (os.getenv('AI_PROVIDER_FORMAT') or '').strip().lower()
    if provider not in {'openai', 'gemini'}:
        raise ValueError('AI_PROVIDER_FORMAT must be set to "openai" or "gemini"')

    image_provider = (os.getenv('IMAGE_PROVIDER_FORMAT') or provider).strip().lower().replace('-', '_')
    if image_provider not in {'openai', 'gemini'}:
        raise ValueError(f'IMAGE_PROVIDER_FORMAT must be set to "openai" or "gemini" (got {image_provider!r})')

    if provider == 'openai':
        if not (os.getenv('OPENAI_API_KEY') or '').strip():
            raise ValueError('OPENAI_API_KEY is required when AI_PROVIDER_FORMAT=openai')
    else:
        if not (os.getenv('GOOGLE_API_KEY') or '').strip():
            raise ValueError('GOOGLE_API_KEY is required when AI_PROVIDER_FORMAT=gemini')

    if image_provider == 'openai':
        image_backend = (os.getenv('OPENAI_IMAGE_BACKEND') or 'proxy').strip().lower().replace('-', '_')
        image_mode = (os.getenv('OPENAI_IMAGE_MODE') or 'responses').strip().lower().replace('-', '_')
        if image_backend not in {'proxy', 'azure', 'chatgpt'}:
            raise ValueError('OPENAI_IMAGE_BACKEND must be set to "proxy", "azure", or "chatgpt"')
        if image_mode not in {'responses', 'chat'}:
            raise ValueError('OPENAI_IMAGE_MODE must be set to "responses" or "chat"')
        if image_mode == 'chat' and image_backend != 'proxy':
            raise ValueError('OPENAI_IMAGE_MODE=chat is only supported when OPENAI_IMAGE_BACKEND=proxy')
        if image_backend != 'chatgpt' and not (os.getenv('OPENAI_API_KEY') or '').strip():
            raise ValueError('OPENAI_API_KEY is required when IMAGE_PROVIDER_FORMAT=openai')
        if image_backend == 'chatgpt' and not ((os.getenv('OPENAI_API_KEY') or '').strip() or (os.getenv('OPENAI_AUTH_JSON') or '').strip()):
            raise ValueError('OPENAI_API_KEY or OPENAI_AUTH_JSON is required when OPENAI_IMAGE_BACKEND=chatgpt')
        if image_mode == 'responses':
            if not (os.getenv('OPENAI_RESPONSES_MODEL') or '').strip():
                raise ValueError('OPENAI_RESPONSES_MODEL is required when OPENAI_IMAGE_MODE=responses')
            if not (os.getenv('OPENAI_IMAGE_MODEL') or '').strip():
                raise ValueError('OPENAI_IMAGE_MODEL is required when OPENAI_IMAGE_MODE=responses')
        if image_backend == 'azure':
            if not (os.getenv('OPENAI_API_BASE') or '').strip():
                raise ValueError('OPENAI_API_BASE is required when OPENAI_IMAGE_BACKEND=azure')
            if not (os.getenv('OPENAI_IMAGE_DEPLOYMENT') or '').strip():
                raise ValueError('OPENAI_IMAGE_DEPLOYMENT is required when OPENAI_IMAGE_BACKEND=azure')


# Create app instance
app = create_app()


if __name__ == '__main__':
    # Run development server
    if os.getenv("IN_DOCKER", "0") == "1":
        port = 5000  # Docker 容器内部固定使用 5000 端口
    else:
        port = int(os.getenv('BACKEND_PORT', 5000))
    debug = os.getenv('FLASK_ENV', 'development') == 'development'
    
    logging.info(
        "\n"
        "╔══════════════════════════════════════╗\n"
        "║   🍌 Banana Slides API Server 🍌   ║\n"
        "╚══════════════════════════════════════╝\n"
        f"Server starting on: http://localhost:{port}\n"
        f"Output Language: {Config.OUTPUT_LANGUAGE}\n"
        f"Environment: {os.getenv('FLASK_ENV', 'development')}\n"
        f"Debug mode: {debug}\n"
        f"API Base URL: http://localhost:{port}/api\n"
        f"Database: {app.config['SQLALCHEMY_DATABASE_URI']}\n"
        f"Uploads: {app.config['UPLOAD_FOLDER']}"
    )
    
    # Using absolute paths for database, so WSL path issues should not occur
    app.run(host='0.0.0.0', port=port, debug=debug, use_reloader=False)
