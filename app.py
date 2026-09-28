"""
Q-Hold: Maruti Suzuki Quality Hold, Vehicle Repair & Inspection Platform
Application Server & Entry Point
"""

import os
import secrets
import sys
import webbrowser
from flask import Flask, render_template, session
from markupsafe import Markup
from qhold.authorization import DEMO_ROLES
from qhold.rich_text import sanitize_rich_text
from qhold.database import init_db
from qhold.seed_data import seed_database
from qhold.repositories.hold_repo import HoldRepository

# Import blueprints
from qhold.routes.home_routes import home_bp
from qhold.routes.about_routes import about_bp
from qhold.routes.repair_inspection_routes import repair_inspection_bp
from qhold.routes.procedure_routes import procedure_bp
from qhold.routes.production_routes import production_bp
from qhold.routes.approval_routes import approval_bp

def create_app():
    """Application factory for Q-Hold."""
    base_dir = os.path.abspath(os.path.dirname(__file__))
    app = Flask(
        __name__,
        template_folder=os.path.join(base_dir, 'qhold', 'templates'),
        static_folder=os.path.join(base_dir, 'qhold', 'static')
    )

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

    # Ensure database is initialized
    init_db()

    # If database is fresh or empty, automatically populate demonstration data
    existing_holds = HoldRepository.get_all_holds()
    if len(existing_holds) == 0:
        print("[Q-Hold] Populating initial demonstration data...")
        seed_database()

    # Register blueprints
    app.register_blueprint(home_bp)
    app.register_blueprint(about_bp)
    app.register_blueprint(repair_inspection_bp)
    app.register_blueprint(procedure_bp)
    app.register_blueprint(production_bp)
    app.register_blueprint(approval_bp)

    # Context processors
    @app.template_filter('richtext')
    def richtext_filter(value):
        return Markup(sanitize_rich_text(value))

    @app.context_processor
    def inject_global_data():
        active_role = session.get('demo_role', 'Administrator')
        return {
            'roles_list': DEMO_ROLES,
            'current_role': active_role
        }

    # Error handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template(
            'error.html',
            error_title='Page or Record Not Found',
            error_message='The requested quality hold, procedure, or resource could not be found.',
            status_code=404
        ), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template(
            'error.html',
            error_title='Internal Server Error',
            error_message='An unexpected error occurred while processing this request. Please try again.',
            status_code=500
        ), 500

    @app.errorhandler(403)
    def access_forbidden(e):
        return render_template('403.html'), 403

    @app.errorhandler(413)
    def upload_too_large(e):
        return render_template(
            'error.html',
            error_title='Upload Too Large',
            error_message='The request exceeds the 16 MB upload limit. Choose a smaller file and try again.',
            status_code=413
        ), 413

    return app

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    url = f"http://127.0.0.1:{port}"
    print("=" * 64)
    print("  MARUTI SUZUKI &mdash; Q-HOLD QUALITY CONTAINMENT PLATFORM")
    print(f"  Server URL: {url}")
    print("  Standard: IATF 16949 / ISO 9001 Compliance")
    print("=" * 64)

    # Auto-open browser if not disabled
    if '--no-browser' not in sys.argv:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    app.run(host='127.0.0.1', port=port, debug=os.environ.get('FLASK_DEBUG') == '1')
