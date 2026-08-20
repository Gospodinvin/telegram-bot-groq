# webhook_server.py
import hmac
import hashlib
import json
import logging
from flask import Flask, request, jsonify
from config import PRODAMUS_SECRET_KEY, ADMIN_ID, WEBHOOK_BASE_URL
from db import set_subscription

logger = logging.getLogger(__name__)
app = Flask(__name__)

if not PRODAMUS_SECRET_KEY:
    logger.critical("PRODAMUS_SECRET_KEY не задан! Вебхук не будет работать без подписи.")
    # В продакшене лучше завершить работу, но для отладки можно предупредить
    # raise ValueError("PRODAMUS_SECRET_KEY must be set for webhook security")

def verify_signature(data: dict, signature: str) -> bool:
    if not PRODAMUS_SECRET_KEY:
        # В продакшене здесь должен быть return False
        logger.warning("Проверка подписи отключена из-за отсутствия секрета!")
        return False  # Теперь отклоняем все запросы без секрета
    sorted_data = {k: v for k, v in sorted(data.items()) if k != 'signature'}
    sign_string = '&'.join([f"{k}={v}" for k, v in sorted_data.items()])
    expected = hmac.new(
        PRODAMUS_SECRET_KEY.encode('utf-8'),
        sign_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

@app.route('/webhook/prodamus', methods=['POST'])
def prodamus_webhook():
    data = request.json
    signature = request.headers.get('X-Signature', '')
    if not verify_signature(data, signature):
        logger.warning(f"Неверная подпись от {request.remote_addr}")
        return jsonify({"status": "error", "message": "Invalid signature"}), 400

    logger.info(f"💰 Получен вебхук: {json.dumps(data, ensure_ascii=False)}")

    try:
        user_id = data.get('user_id')
        plan = data.get('plan', 'basic')
        days = data.get('days', 30)
        if user_id:
            set_subscription(user_id, plan, days)
            logger.info(f"✅ Подписка активирована для user {user_id} ({plan}, {days} дн.)")
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"Ошибка обработки вебхука: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/webhook/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "webhook_url": WEBHOOK_BASE_URL + "/webhook/prodamus"})

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(port=8080, debug=False)