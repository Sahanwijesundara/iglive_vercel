from flask import Flask, request, jsonify
import os
import json
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import dependencies with error handling
try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
    import httpx
    logger.info("✅ All imports successful")
except ImportError as e:
    logger.error(f"❌ Import error: {e}")
    # Continue anyway for basic health check
    create_engine = None

# Initialize Flask app
app = Flask(__name__)

# Database connection
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
engine = None

def init_db():
    """Initialize database connection"""
    global engine

    if not DATABASE_URL:
        logger.warning("⚠️ DATABASE_URL not set")
        return False

    if not create_engine:
        logger.error("❌ SQLAlchemy not available")
        return False

    try:
        engine = create_engine(
            DATABASE_URL,
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args={"sslmode": "require"},
            echo=False
        )

        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        logger.info("✅ Database connected successfully")
        return True

    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False

# Initialize DB (but don't fail if it doesn't work)
try:
    init_db()
except Exception as e:
    logger.error(f"❌ DB initialization error: {e}")

@app.route('/api/webhook', methods=['GET', 'POST'])
def webhook():
    """Main webhook endpoint"""

    # GET - Health check
    if request.method == 'GET':
        health_status = {
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat(),
            "database": "connected" if engine else "not connected",
            "environment": {
                "DATABASE_URL": "set" if DATABASE_URL else "not set",
                "BOT_TOKEN": "set" if os.environ.get('BOT_TOKEN') else "not set",
                "TGMS_BOT_TOKEN": "set" if os.environ.get('TGMS_BOT_TOKEN') else "not set"
            }
        }
        return jsonify(health_status), 200

    # POST - Process webhook
    if not engine:
        logger.error("❌ Database not available for webhook processing")
        return jsonify({"error": "Database unavailable"}), 503

    try:
        # Get webhook data
        update_data = request.get_json(force=True)

        if not update_data:
            return jsonify({"error": "No data received"}), 400

        update_id = update_data.get('update_id', 'unknown')
        logger.info(f"📨 Processing webhook update: {update_id}")

        # Determine job type
        if 'chat_join_request' in update_data:
            job_type = 'tgms_process_join_request'
            bot_token = os.environ.get('TGMS_BOT_TOKEN')
        else:
            job_type = 'process_telegram_update'
            bot_token = os.environ.get('BOT_TOKEN')

        if not bot_token:
            logger.error(f"❌ Bot token not configured for job type: {job_type}")
            return jsonify({"error": "Bot not configured"}), 500

        # Insert job into database
        with engine.connect() as conn:
            with conn.begin():
                query = text("""
                    INSERT INTO jobs (job_type, bot_token, payload, status, created_at, updated_at)
                    VALUES (:job_type, :bot_token, :payload, 'pending', :created_at, :updated_at)
                """)

                conn.execute(query, {
                    'job_type': job_type,
                    'bot_token': bot_token,
                    'payload': json.dumps(update_data),
                    'created_at': datetime.utcnow(),
                    'updated_at': datetime.utcnow()
                })

        logger.info(f"✅ Job queued successfully for update: {update_id}")

        # Send immediate response if it's a callback query
        try:
            if 'callback_query' in update_data and httpx:
                callback_id = update_data['callback_query'].get('id')
                if callback_id:
                    httpx.post(
                        f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
                        json={"callback_query_id": callback_id},
                        timeout=2.0
                    )
        except Exception as e:
            logger.warning(f"⚠️ Could not send callback response: {e}")

        return jsonify({
            "status": "ok",
            "message": "Webhook processed",
            "update_id": update_id
        }), 200

    except Exception as e:
        logger.error(f"❌ Error processing webhook: {e}", exc_info=True)
        return jsonify({"error": "Processing failed", "details": str(e)}), 500

@app.route('/')
def index():
    """Root endpoint"""
    return """
    <html>
        <head><title>Webhook Service</title></head>
        <body>
            <h1>✅ Webhook Service Running</h1>
            <p>Endpoints:</p>
            <ul>
                <li><a href="/api/webhook">GET /api/webhook</a> - Health check</li>
                <li>POST /api/webhook - Process webhooks</li>
            </ul>
        </body>
    </html>
    """, 200

# This is critical for Vercel!
# Vercel will call this app object directly
if __name__ != '__main__':
    # Production mode (Vercel)
    logger.info("🚀 Running in production mode (Vercel)")
else:
    # Local development
    logger.info("🔧 Running in development mode")
    app.run(debug=True, port=8000)
