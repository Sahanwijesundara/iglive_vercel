from flask import Flask, request, jsonify
import os
import json
import logging
from datetime import datetime
import time
import threading

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
    create_engine = None
    httpx = None

# Initialize Flask app
app = Flask(__name__)

# Database connection
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
engine = None

def init_db():
    """Initialize database connection"""
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
        
        logger.info("✅ Database connected successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False

# Initialize DB
try:
    init_db()
except Exception as e:
    logger.error(f"❌ DB initialization error: {e}")


def send_typing_action(bot_token, chat_id, duration=5):
    """Send typing action for specified duration (in background)"""
    if not httpx or not bot_token or not chat_id:
        return
    
    def _send_typing():
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendChatAction"
            end_time = time.time() + duration
            
            while time.time() < end_time:
                try:
                    httpx.post(
                        url,
                        json={"chat_id": chat_id, "action": "typing"},
                        timeout=2.0
                    )
                    logger.info(f"✅ Sent typing action to chat {chat_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to send typing: {e}")
                    break
                
                # Telegram typing lasts ~5 seconds, so send again after 4 seconds
                time.sleep(4)
                
        except Exception as e:
            logger.warning(f"⚠️ Typing thread error: {e}")
    
    # Run in background thread (non-blocking)
    thread = threading.Thread(target=_send_typing, daemon=True)
    thread.start()


def answer_callback_query(bot_token, callback_query_id):
    """Answer callback query immediately"""
    if not httpx or not bot_token or not callback_query_id:
        return
    
    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id},
            timeout=2.0
        )
        logger.info("✅ Answered callback query")
    except Exception as e:
        logger.warning(f"⚠️ Failed to answer callback: {e}")


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
        
        # Determine job type and extract chat info
        chat_id = None
        callback_query_id = None
        
        if 'chat_join_request' in update_data:
            job_type = 'tgms_process_join_request'
            bot_token = os.environ.get('TGMS_BOT_TOKEN')
            chat_id = update_data['chat_join_request'].get('chat', {}).get('id')
            
        elif 'callback_query' in update_data:
            job_type = 'process_telegram_update'
            bot_token = os.environ.get('BOT_TOKEN')
            callback_query_id = update_data['callback_query'].get('id')
            chat_id = update_data['callback_query'].get('message', {}).get('chat', {}).get('id')
            
        elif 'message' in update_data:
            job_type = 'process_telegram_update'
            bot_token = os.environ.get('BOT_TOKEN')
            chat_id = update_data['message'].get('chat', {}).get('id')
            
        elif 'my_chat_member' in update_data:
            job_type = 'tgms_process_update'
            bot_token = os.environ.get('TGMS_BOT_TOKEN')
            chat_id = update_data['my_chat_member'].get('chat', {}).get('id')
            
        else:
            job_type = 'process_telegram_update'
            bot_token = os.environ.get('BOT_TOKEN')
        
        if not bot_token:
            logger.error(f"❌ Bot token not configured for job type: {job_type}")
            return jsonify({"error": "Bot not configured"}), 500
        
        # === SEND IMMEDIATE RESPONSES ===
        
        # 1. Answer callback query if present (removes loading state)
        if callback_query_id:
            answer_callback_query(bot_token, callback_query_id)
        
        # 2. Send typing action for 5 seconds (background thread)
        if chat_id:
            send_typing_action(bot_token, chat_id, duration=5)
            logger.info(f"🔄 Started typing indicator for chat {chat_id}")
        
        # === INSERT JOB INTO DATABASE ===
        
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
        
        # Return success immediately (typing continues in background)
        return jsonify({
            "status": "ok",
            "message": "Webhook processed",
            "update_id": update_id,
            "typing_started": bool(chat_id)
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


# Critical for Vercel
if __name__ != '__main__':
    logger.info("🚀 Running in production mode (Vercel)")
else:
    logger.info("🔧 Running in development mode")
    app.run(debug=True, port=8000)