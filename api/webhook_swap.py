from flask import Flask, request, jsonify
import os
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
    logger.info("✅ Imports successful")
except ImportError as e:
    logger.error(f"❌ Import error: {e}")
    create_engine = None

app = Flask(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
SWAP_BOT_TOKEN = os.environ.get('SWAP_BOT_TOKEN', '').strip()
engine = None

def init_db():
    global engine
    if not DATABASE_URL or not create_engine:
        return False
    try:
        engine = create_engine(
            DATABASE_URL,
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args={"sslmode": "require"},
            echo=False
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✅ Database connected")
        return True
    except Exception as e:
        logger.error(f"❌ Database error: {e}")
        return False

try:
    init_db()
except Exception as e:
    logger.error(f"❌ Init error: {e}")

@app.route('/api/webhook_swap', methods=['GET', 'POST'])
def webhook_swap():
    """Webhook endpoint for Instagram Live Swap Bot"""
    
    if request.method == 'GET':
        return jsonify({
            "status": "ok",
            "bot": "Instagram Live Swap Bot",
            "timestamp": datetime.utcnow().isoformat(),
            "database": "connected" if engine else "not connected"
        }), 200
    
    if not engine:
        logger.error("❌ Database not available")
        return jsonify({"error": "Database unavailable"}), 503
    
    try:
        update_data = request.get_json(force=True)
        
        if not update_data:
            return jsonify({"error": "No data"}), 400
        
        update_id = update_data.get('update_id', 'unknown')
        logger.info(f"📨 Swap bot update: {update_id}")
        
        # Insert job into database
        with engine.connect() as conn:
            with conn.begin():
                query = text("""
                    INSERT INTO jobs (job_type, bot_token, payload, status, created_at, updated_at)
                    VALUES (:job_type, :bot_token, :payload, 'pending', :created_at, :updated_at)
                """)
                
                conn.execute(query, {
                    'job_type': 'process_telegram_update',
                    'bot_token': SWAP_BOT_TOKEN,
                    'payload': json.dumps(update_data),
                    'created_at': datetime.utcnow(),
                    'updated_at': datetime.utcnow()
                })
        
        logger.info(f"✅ Swap bot job queued: {update_id}")
        
        return jsonify({
            "status": "ok",
            "message": "Webhook processed",
            "update_id": update_id
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

if __name__ != '__main__':
    logger.info("🚀 Swap bot webhook running (Vercel)")
else:
    app.run(debug=True, port=8001)