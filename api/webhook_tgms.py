from flask import Flask, request, jsonify
import os
import json
import logging
from datetime import datetime
import time
import threading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
    import httpx
except ImportError as e:
    logger.error(f"❌ Import error: {e}")
    httpx = None

# Same DB setup as webhook.py
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
engine = None

def init_db():
    global engine
    if not DATABASE_URL:
        return False
    try:
        engine = create_engine(
            DATABASE_URL,
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args={"sslmode": "require"},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✅ TGMS Database connected")
        return True
    except Exception as e:
        logger.error(f"❌ DB error: {e}")
        return False

init_db()

app = Flask(__name__)

def send_typing_action(bot_token, chat_id, duration=5):
    """Same typing function"""
    if not httpx or not bot_token or not chat_id:
        return
    
    def _send_typing():
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendChatAction"
            end_time = time.time() + duration
            
            while time.time() < end_time:
                try:
                    httpx.post(url, json={"chat_id": chat_id, "action": "typing"}, timeout=2.0)
                except:
                    break
                time.sleep(4)
        except:
            pass
    
    threading.Thread(target=_send_typing, daemon=True).start()


@app.route('/api/webhook_tgms', methods=['GET', 'POST'])
def webhook_tgms():
    """TGMS Bot webhook endpoint"""
    
    if request.method == 'GET':
        return jsonify({
            "status": "ok",
            "bot": "TGMS",
            "database": "connected" if engine else "not connected"
        }), 200
    
    if not engine:
        return jsonify({"error": "Database unavailable"}), 503
    
    try:
        update_data = request.get_json(force=True)
        if not update_data:
            return jsonify({"error": "No data"}), 400
        
        update_id = update_data.get('update_id', 'unknown')
        logger.info(f"📨 TGMS webhook update: {update_id}")
        
        bot_token = os.environ.get('TGMS_BOT_TOKEN')
        if not bot_token:
            return jsonify({"error": "TGMS_BOT_TOKEN not configured"}), 500
        
        # Determine job type
        if 'my_chat_member' in update_data:
            new_status = update_data['my_chat_member'].get('new_chat_member', {}).get('status')
            if new_status in {'administrator', 'creator'}:
                job_type = 'tgms_register_group'
            else:
                job_type = 'tgms_process_update'
            chat_id = update_data['my_chat_member'].get('chat', {}).get('id')
            
        elif 'chat_join_request' in update_data:
            job_type = 'tgms_process_join_request'
            chat_id = update_data['chat_join_request'].get('chat', {}).get('id')
            
        elif 'message' in update_data:
            job_type = 'tgms_process_update'
            chat_id = update_data['message'].get('chat', {}).get('id')
            
        else:
            job_type = 'tgms_process_update'
            chat_id = None
        
        # Send typing
        if chat_id:
            send_typing_action(bot_token, chat_id, duration=5)
        
        # Insert job
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
        
        logger.info(f"✅ TGMS job queued: {update_id}")
        return jsonify({"status": "ok", "bot": "TGMS", "update_id": update_id}), 200
        
    except Exception as e:
        logger.error(f"❌ TGMS webhook error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500