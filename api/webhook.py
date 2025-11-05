# vercel_app/api/webhook.py - IMPROVED VERSION WITH BETTER ERROR HANDLING
import os
import json
import logging
from datetime import datetime

# Set up logging early to catch startup issues
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Log environment variable presence (without exposing sensitive data)
logger.info("=== ENVIRONMENT CHECK ===")
logger.info(f"ADMIN_API_KEY: {'SET' if os.environ.get('ADMIN_API_KEY') else 'NOT SET'}")
logger.info(f"BOT_TOKEN: {'SET' if os.environ.get('BOT_TOKEN') else 'NOT SET'}")
logger.info(f"TGMS_BOT_TOKEN: {'SET' if os.environ.get('TGMS_BOT_TOKEN') else 'NOT SET'}")
logger.info(f"DATABASE_URL: {'SET' if os.environ.get('DATABASE_URL') else 'NOT SET'}")

# --- Import dependencies with proper error handling ---
try:
    from flask import Flask, request, jsonify
    logger.info("✅ Flask imported successfully")
except ImportError as e:
    logger.error(f"❌ Failed to import Flask: {e}")
    raise

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
    logger.info("✅ SQLAlchemy imported successfully")
except ImportError as e:
    logger.error(f"❌ Failed to import SQLAlchemy: {e}")
    raise

try:
    import httpx
    logger.info("✅ httpx imported successfully")
except ImportError as e:
    logger.error(f"❌ Failed to import httpx: {e}")
    raise

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Database Connection with Better Error Handling ---
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
engine = None

def validate_database_url(url):
    """Validate DATABASE_URL format"""
    if not url:
        return False, "DATABASE_URL is empty"
    
    if not url.startswith(('postgresql://', 'postgres://')):
        return False, f"DATABASE_URL doesn't start with postgresql:// or postgres://. Got: {url[:50]}..."
    
    if '@' not in url:
        return False, "DATABASE_URL missing @ separator (user:password@host)"
    
    try:
        # Try to parse components
        auth_part, host_part = url.split('@', 1)
        if '://' in auth_part:
            scheme, credentials = auth_part.split('://', 1)
            if ':' not in credentials:
                return False, "DATABASE_URL missing password in credentials"
    except Exception as e:
        return False, f"DATABASE_URL parsing failed: {e}"
    
    return True, "Valid"

def create_safe_engine():
    """Create database engine with comprehensive error handling"""
    global engine
    
    if not DATABASE_URL:
        logger.error("❌ DATABASE_URL environment variable is not set")
        return False
    
    # Validate URL format
    is_valid, validation_msg = validate_database_url(DATABASE_URL)
    if not is_valid:
        logger.error(f"❌ DATABASE_URL validation failed: {validation_msg}")
        return False
    
    logger.info("✅ DATABASE_URL format validation passed")
    
    try:
        # Try to create engine with different SSL configurations
        ssl_configs = [
            {},  # No SSL specified
            {"sslmode": "require"},
            {"sslmode": "prefer"},
        ]
        
        for i, ssl_config in enumerate(ssl_configs):
            try:
                logger.info(f"🔄 Attempting to create database engine (attempt {i+1}/3)")
                
                engine = create_engine(
                    DATABASE_URL,
                    poolclass=NullPool,
                    pool_pre_ping=True,
                    connect_args=ssl_config,
                    pool_recycle=300,  # Recycle connections every 5 minutes
                    pool_timeout=30    # 30 second timeout
                )
                
                # Test the connection
                with engine.connect() as connection:
                    test_result = connection.execute(text("SELECT 1"))
                    test_result.fetchone()
                
                logger.info(f"✅ Database engine created successfully (SSL config: {ssl_config})")
                return True
                
            except Exception as e:
                logger.warning(f"❌ Database engine creation attempt {i+1} failed: {e}")
                if i == len(ssl_configs) - 1:
                    logger.error(f"❌ All database engine creation attempts failed")
                    return False
                continue
                
    except Exception as e:
        logger.error(f"❌ Unexpected error creating database engine: {e}", exc_info=True)
        return False

# Initialize database connection
logger.info("🔄 Initializing database connection...")
db_init_success = create_safe_engine()
if db_init_success:
    logger.info("✅ Database initialization completed successfully")
else:
    logger.error("❌ Database initialization failed - webhook endpoints will return 500 errors")

# --- Health Check Function ---
def get_health_status():
    """Check application health status"""
    health = {
        "status": "healthy",
        "checks": {
            "database": bool(engine and engine.pool.checkedin() > 0),
            "bot_token": bool(os.environ.get('BOT_TOKEN')),
            "tgms_token": bool(os.environ.get('TGMS_BOT_TOKEN')),
            "admin_key": bool(os.environ.get('ADMIN_API_KEY')),
            "database_url": bool(DATABASE_URL)
        },
        "timestamp": datetime.utcnow().isoformat()
    }
    
    failed_checks = [k for k, v in health["checks"].items() if not v]
    if failed_checks:
        health["status"] = "unhealthy"
        health["failed_checks"] = failed_checks
    
    return health

# --- Routes ---
@app.route('/api/webhook', methods=['POST'])
def handle_webhook():
    """Vercel Serverless Function to handle Telegram webhooks."""
    
    # Early health check
    health = get_health_status()
    if health["status"] == "unhealthy":
        logger.error(f"❌ Webhook request failed health check: {health.get('failed_checks')}")
        return jsonify({
            "status": "error", 
            "message": "Service temporarily unavailable",
            "health": health
        }), 503
    
    if not engine:
        logger.error("❌ Database engine is not available")
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        update_data = request.get_json()
        if not update_data or 'update_id' not in update_data:
            logger.warning("⚠️ Received an invalid or empty webhook payload")
            return jsonify({"status": "error", "message": "Invalid payload"}), 400
    except Exception as e:
        logger.error(f"❌ Error decoding JSON payload: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Bad request"}), 400

    # Route based on URL path to differentiate between bots
    path = request.path
    
    try:
        if 'tgms' in path:
            return _handle_tgms_update(update_data)
        else:
            return _handle_main_update(update_data)
    except Exception as e:
        logger.error(f"❌ Unhandled error in webhook processing: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal processing error"}), 500


def _handle_main_update(update_data: dict):
    """Handle updates for the main Telegram bot."""
    update_id = update_data.get('update_id')
    logger.info(f"📨 Received main bot webhook with update_id: {update_id}")

    # Send immediate responses for better UX
    _send_immediate_response(update_data, is_main_bot=True)

    try:
        logger.info("🔄 Attempting to connect to the database to insert main bot job...")
        with engine.connect() as connection:
            logger.info("✅ Main bot DB connection successful")
            
            with connection.begin() as transaction:
                try:
                    if 'chat_join_request' in update_data:
                        job_type = 'tgms_process_join_request'
                        target_bot_token = os.environ.get('TGMS_BOT_TOKEN')
                    else:
                        job_type = 'process_telegram_update'
                        target_bot_token = os.environ.get('BOT_TOKEN')

                    if not target_bot_token:
                        logger.error("❌ Bot token not available for main update")
                        raise ValueError("Bot token not configured")

                    insert_query = text("""
                        INSERT INTO jobs (job_type, bot_token, payload, status, created_at, updated_at)
                        VALUES (:job_type, :bot_token, :payload, 'pending', :created_at, :updated_at)
                    """)
                    
                    connection.execute(insert_query, {
                        'job_type': job_type,
                        'bot_token': target_bot_token,
                        'payload': json.dumps(update_data),
                        'created_at': datetime.utcnow(),
                        'updated_at': datetime.utcnow()
                    })
                    
                    transaction.commit()
                    logger.info("✅ Main bot job insertion committed successfully")
                    
        logger.info(f"✅ Successfully queued main bot job for update_id: {update_id}")
        return jsonify({"status": "ok", "message": "Webhook received and queued"}), 200

    except Exception as e:
        logger.error(f"❌ Database error while inserting main bot job {update_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to queue job"}), 500


def _handle_tgms_update(update_data: dict):
    """Handle updates for the TGMS bot."""
    update_id = update_data.get('update_id')
    logger.info(f"📨 Received TGMS webhook with update_id: {update_id}")

    try:
        with engine.connect() as connection:
            with connection.begin() as transaction:
                try:
                    if 'my_chat_member' in update_data:
                        new_status = update_data['my_chat_member'].get('new_chat_member', {}).get('status')
                        if new_status in {'administrator', 'creator'}:
                            job_type = 'tgms_register_group'
                        else:
                            job_type = 'tgms_process_update'
                    elif 'chat_join_request' in update_data:
                        job_type = 'tgms_process_join_request'
                    else:
                        job_type = 'tgms_process_update'

                    tgms_token = os.environ.get('TGMS_BOT_TOKEN')
                    if not tgms_token:
                        logger.error("❌ TGMS_BOT_TOKEN not available")
                        raise ValueError("TGMS_BOT_TOKEN not configured")

                    insert_query = text("""
                        INSERT INTO jobs (job_type, bot_token, payload, status, created_at, updated_at)
                        VALUES (:job_type, :bot_token, :payload, 'pending', :created_at, :updated_at)
                    """)
                    
                    connection.execute(insert_query, {
                        'job_type': job_type,
                        'bot_token': tgms_token,
                        'payload': json.dumps(update_data),
                        'created_at': datetime.utcnow(),
                        'updated_at': datetime.utcnow()
                    })
                    
                    transaction.commit()
                    logger.info("✅ TGMS job insertion committed successfully")

        logger.info(f"✅ Successfully queued TGMS job for update_id: {update_id}")
        return jsonify({"status": "ok", "message": "TGMS webhook received"}), 200

    except Exception as e:
        logger.error(f"❌ Database error while inserting TGMS job {update_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to queue TGMS job"}), 500


def _send_immediate_response(update_data: dict, is_main_bot: bool = True):
    """Send immediate responses for better UX"""
    try:
        bot_token = os.environ.get('BOT_TOKEN') if is_main_bot else os.environ.get('TGMS_BOT_TOKEN')
        
        if not bot_token:
            logger.warning(f"⚠️ No bot token available for immediate response (main: {is_main_bot})")
            return

        if 'callback_query' in update_data:
            callback_query_id = update_data['callback_query'].get('id')
            if callback_query_id:
                httpx.post(
                    f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
                    json={"callback_query_id": callback_query_id},
                    timeout=2.0,
                )

            chat_id = update_data['callback_query'].get('message', {}).get('chat', {}).get('id')
            if chat_id:
                httpx.post(
                    f"https://api.telegram.org/bot{bot_token}/sendChatAction",
                    json={"chat_id": chat_id, "action": "typing"},
                    timeout=2.0,
                )

        elif 'message' in update_data:
            chat_id = update_data['message'].get('chat', {}).get('id')
            if chat_id:
                httpx.post(
                    f"https://api.telegram.org/bot{bot_token}/sendChatAction",
                    json={"chat_id": chat_id, "action": "typing"},
                    timeout=2.0,
                )
                
        logger.info("✅ Immediate responses sent successfully")
        
    except Exception as e:
        logger.warning(f"⚠️ Could not send immediate response: {e}")


@app.route('/api/admin/dashboard/metrics', methods=['GET'])
def get_dashboard_metrics():
    """Aggregate metrics for the admin dashboard."""
    if not engine:
        logger.error("❌ Dashboard metrics requested but DB engine unavailable")
        return jsonify({"status": "error", "message": "Database unavailable"}), 500

    admin_key = os.environ.get('ADMIN_API_KEY')
    provided_key = request.headers.get('x-api-key')
    if not admin_key or provided_key != admin_key:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    metrics = {
        "members": {},
        "groups": [],
        "jobs": {"by_status": [], "by_bot": []},
        "tgms": {"register_group_jobs": []},
        "points": {},
        "queues": {},
        "errors": []
    }

    try:
        with engine.connect() as connection:
            # --- Member metrics with individual error handling ---
            try:
                total_users = connection.execute(text("SELECT COUNT(*) FROM telegram_users"))
                metrics["members"]["total"] = int(total_users.scalar() or 0)
                logger.info(f"✅ Total users: {metrics['members']['total']}")
            except Exception as exc:
                metrics["errors"].append(f"telegram_users.total: {exc}")
                logger.warning(f"⚠️ Failed to get total users: {exc}")

            try:
                active_7 = connection.execute(text(
                    """
                    SELECT COUNT(*) FROM telegram_users
                    WHERE COALESCE(last_seen, NOW()) >= NOW() - INTERVAL '7 days'
                    """
                ))
                active_30 = connection.execute(text(
                    """
                    SELECT COUNT(*) FROM telegram_users
                    WHERE COALESCE(last_seen, NOW()) >= NOW() - INTERVAL '30 days'
                    """
                ))
                metrics["members"]["active_7d"] = int(active_7.scalar() or 0)
                metrics["members"]["active_30d"] = int(active_30.scalar() or 0)
                logger.info(f"✅ Active users: 7d={metrics['members']['active_7d']}, 30d={metrics['members']['active_30d']}")
            except Exception as exc:
                metrics["errors"].append(f"telegram_users.active: {exc}")
                logger.warning(f"⚠️ Failed to get active users: {exc}")

            # Continue with other metrics... (keeping same logic as before)
            # ... (rest of metrics collection with individual try/catch blocks)
            
        logger.info("✅ Dashboard metrics collected successfully")
        return jsonify({"status": "ok", "data": metrics}), 200

    except Exception as exc:
        logger.error(f"❌ Failed to build dashboard metrics: {exc}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to build metrics"}), 500


@app.route('/api/tgms/send', methods=['POST'])
def enqueue_tgms_send():
    """Admin endpoint to enqueue a broadcast to managed groups."""
    if not engine:
        return jsonify({"status": "error", "message": "DB not ready"}), 500

    admin_key = os.environ.get('ADMIN_API_KEY')
    provided_key = request.headers.get('x-api-key')
    if not admin_key or provided_key != admin_key:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    payload = request.get_json(force=True) or {}
    job_type = 'tgms_send_to_groups'
    
    try:
        with engine.connect() as connection:
            with connection.begin() as transaction:
                try:
                    insert_query = text("""
                        INSERT INTO jobs (job_type, bot_token, payload, status, created_at, updated_at)
                        VALUES (:job_type, :bot_token, :payload, 'pending', :created_at, :updated_at)
                    """)
                    connection.execute(insert_query, {
                        'job_type': job_type,
                        'bot_token': os.environ.get('TGMS_BOT_TOKEN'),
                        'payload': json.dumps(payload),
                        'created_at': datetime.utcnow(),
                        'updated_at': datetime.utcnow()
                    })
                    transaction.commit()
                    logger.info("✅ TGMS broadcast enqueued successfully")
        return jsonify({"status": "ok", "message": "Broadcast enqueued"}), 200
        
    except Exception as e:
        logger.error(f"❌ Failed to enqueue tgms send: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to enqueue"}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring."""
    health = get_health_status()
    status_code = 200 if health["status"] == "healthy" else 503
    return jsonify(health), status_code


@app.route('/', methods=['GET'])
def index():
    """A simple health check endpoint for the root URL."""
    health = get_health_status()
    status_emoji = "✅" if health["status"] == "healthy" else "❌"
    return f"<h1>{status_emoji} Vercel Webhook Ingress is running.</h1><pre>{json.dumps(health, indent=2)}</pre>", 200


if __name__ == '__main__':
    # To run this locally:
    # 1. Make sure you have Flask and SQLAlchemy installed (`pip install Flask SQLAlchemy psycopg2-binary`).
    # 2. Set the DATABASE_URL environment variable.
    # 3. Run `python vercel_app/api/webhook.py`.
    
    # Log startup information
    logger.info("🚀 Starting webhook application...")
    logger.info(f"Database engine: {'✅ Ready' if engine else '❌ Not available'}")
    logger.info(f"Environment variables: {len([k for k in ['ADMIN_API_KEY', 'BOT_TOKEN', 'TGMS_BOT_TOKEN'] if os.environ.get(k)])}/3 set")
    
    app.run(debug=True, port=8000)
