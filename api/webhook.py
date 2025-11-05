# api/webhook.py
import os
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import dependencies
try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
    import httpx
    logger.info("✅ Imports successful")
except ImportError as e:
    logger.error(f"❌ Import failed: {e}")
    raise

# Database setup
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
engine = None

if DATABASE_URL:
    try:
        engine = create_engine(
            DATABASE_URL,
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args={"sslmode": "require"}
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✅ Database connected")
    except Exception as e:
        logger.error(f"❌ DB connection failed: {e}")

# === VERCEL HANDLER (WSGI) ===
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/api/webhook', methods=['GET', 'POST'])
def webhook():
    """Main webhook endpoint"""

    if request.method == 'GET':
        # Health check
        health = {
            "status": "healthy" if engine else "degraded",
            "database": bool(engine),
            "bot_token": bool(os.environ.get('BOT_TOKEN')),
            "tgms_token": bool(os.environ.get('TGMS_BOT_TOKEN')),
            "timestamp": datetime.utcnow().isoformat()
        }
        return jsonify(health), 200 if engine else 503

    # POST request - webhook processing
    if not engine:
        return jsonify({'error': 'Database unavailable'}), 503

    try:
        update_data = request.get_json()
        if not update_data or 'update_id' not in update_data:
            return jsonify({'error': 'Invalid payload'}), 400

        update_id = update_data.get('update_id')
        logger.info(f"📨 Received update {update_id}")

        # Determine job type based on update
        if 'chat_join_request' in update_data:
            job_type = 'tgms_process_join_request'
            bot_token = os.environ.get('TGMS_BOT_TOKEN')
        else:
            job_type = 'process_telegram_update'
            bot_token = os.environ.get('BOT_TOKEN')

        if not bot_token:
            logger.error("❌ Bot token not configured")
            return jsonify({'error': 'Bot token not configured'}), 500

        # Insert job into database
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text("""
                    INSERT INTO jobs (job_type, bot_token, payload, status, created_at, updated_at)
                    VALUES (:job_type, :bot_token, :payload, 'pending', :created_at, :updated_at)
                """), {
                    'job_type': job_type,
                    'bot_token': bot_token,
                    'payload': json.dumps(update_data),
                    'created_at': datetime.utcnow(),
                    'updated_at': datetime.utcnow()
                })

        logger.info(f"✅ Job queued for update {update_id}")

        # Send immediate response to user
        try:
            if 'callback_query' in update_data:
                callback_query_id = update_data['callback_query'].get('id')
                if callback_query_id:
                    httpx.post(
                        f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
                        json={"callback_query_id": callback_query_id},
                        timeout=2.0
                    )
        except:
            pass

        return jsonify({'status': 'ok', 'message': 'Webhook processed'}), 200

    except Exception as e:
        logger.error(f"❌ Error processing webhook: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/')
def index():
    """Root endpoint"""
    return "<h1>✅ Webhook Service Running</h1>", 200

# Vercel expects this
def handler(event, context):
    """Vercel serverless handler"""
    return app(event, context)
