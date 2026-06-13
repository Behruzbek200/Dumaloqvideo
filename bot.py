import os
import subprocess
import time
import shutil
from flask import Flask, request, jsonify
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# .env faylini yuklash
load_dotenv()

# Muhit o‘zgaruvchilaridan o‘qish
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 5000))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN muhit o‘zgaruvchisi o‘rnatilmagan!")
if not WEBHOOK_URL:
    raise ValueError("WEBHOOK_URL muhit o‘zgaruvchisi o‘rnatilmagan!")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Vaqtinchalik fayllar va holat
TEMP_DIR = "temp_conversions"
os.makedirs(TEMP_DIR, exist_ok=True)
user_data = {}

# ------------------- YORDAMCHI FUNKSIYALAR -------------------
def clean_temp_files(user_id):
    user_folder = os.path.join(TEMP_DIR, str(user_id))
    if os.path.exists(user_folder):
        shutil.rmtree(user_folder)

def get_video_duration(file_path):
    cmd = [
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except:
        return None

def convert_rectangle_to_round(input_path, output_path):
    cmd = [
        'ffmpeg', '-i', input_path,
        '-filter_complex',
        "[0:v]format=rgba,geq='alpha=if(lte(sqrt((X-W/2)^2+(Y-H/2)^2),min(W/2,H/2)),255,0)',format=yuv420p",
        '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
        '-map', '0:a?', '-c:a', 'aac', '-b:a', '128k',
        '-movflags', '+faststart', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0

def convert_round_to_rectangle(input_path, output_path):
    probe_cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height', '-of', 'csv=p=0',
        input_path
    ]
    result = subprocess.run(probe_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False
    dimensions = result.stdout.strip().split(',')
    if len(dimensions) != 2:
        return False
    width, height = dimensions[0], dimensions[1]

    cmd = [
        'ffmpeg', '-i', input_path,
        '-filter_complex',
        f"[0:v]format=rgba,color=black:{width}x{height}[bg];[bg][0:v]overlay=format=auto:shortest=1",
        '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
        '-map', '0:a?', '-c:a', 'aac', '-b:a', '128k',
        '-movflags', '+faststart', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0

def send_conversion_progress(chat_id, message_id, step):
    messages = {
        1: "⏳ Video tayyorlanmoqda...",
        2: "🎬 Kadrlar qayta ishlanmoqda...",
        3: "✨ Format o'zgartirilmoqda...",
        4: "📦 Yakuniy fayl tayyorlanmoqda..."
    }
    text = messages.get(step, "⏳ Iltimos, biroz kuting...")
    try:
        bot.edit_message_text(text, chat_id, message_id)
    except Exception:
        pass

# ------------------- BOT HANDLERLAR -------------------
@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = (
        "🎬 Assalomu alaykum!\n\n"
        "To'rtburchak videoni yumaloq videoga yoki yumaloq videoni to'rtburchak videoga aylantirib beraman.\n\n"
        "📤 Davom etish uchun videongizni yuboring."
    )
    bot.reply_to(message, welcome_text)

@bot.message_handler(content_types=['video'])
def handle_video(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    clean_temp_files(user_id)

    user_folder = os.path.join(TEMP_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)

    file_info = bot.get_file(message.video.file_id)
    downloaded_file = bot.download_file(file_info.file_path)

    input_path = os.path.join(user_folder, "input.mp4")
    with open(input_path, 'wb') as f:
        f.write(downloaded_file)

    duration = get_video_duration(input_path)
    if duration and duration > 300:
        bot.reply_to(message, "⚠️ Video uzunligi 5 daqiqadan oshib ketdi. Jarayon biroz vaqt olishi mumkin.")

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔘 Yumaloq video", callback_data="convert_round"),
        InlineKeyboardButton("⬜ To'rtburchak video", callback_data="convert_rect")
    )

    prompt_msg = bot.reply_to(
        message,
        "🎥 Qaysi formatga aylantirmoqchisiz?",
        reply_markup=markup
    )

    user_data[user_id] = {
        'input_path': input_path,
        'user_folder': user_folder,
        'prompt_msg_id': prompt_msg.message_id,
        'original_message_id': message.message_id
    }

@bot.callback_query_handler(func=lambda call: call.data in ['convert_round', 'convert_rect'])
def handle_conversion(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if user_id not in user_data:
        bot.answer_callback_query(call.id, "❌ Xatolik yuz berdi. Iltimos, /start bilan qaytadan boshlang.")
        return

    data = user_data[user_id]
    input_path = data['input_path']
    user_folder = data['user_folder']
    prompt_msg_id = data['prompt_msg_id']

    bot.answer_callback_query(call.id, "✅ Qabul qilindi! Video tayyorlanmoqda...")

    progress_msg = bot.send_message(chat_id, "⏳ Video tayyorlanmoqda...\nIltimos, biroz kuting.")
    progress_msg_id = progress_msg.message_id

    convert_type = call.data
    output_filename = "output_round.mp4" if convert_type == "convert_round" else "output_rect.mp4"
    output_path = os.path.join(user_folder, output_filename)

    send_conversion_progress(chat_id, progress_msg_id, 1)
    time.sleep(0.5)
    send_conversion_progress(chat_id, progress_msg_id, 2)

    success = False
    if convert_type == "convert_round":
        success = convert_rectangle_to_round(input_path, output_path)
    else:
        success = convert_round_to_rectangle(input_path, output_path)

    send_conversion_progress(chat_id, progress_msg_id, 3)
    time.sleep(0.5)
    send_conversion_progress(chat_id, progress_msg_id, 4)
    time.sleep(0.5)

    if not success or not os.path.exists(output_path):
        bot.edit_message_text(
            "❌ Konvertatsiya davomida xatolik yuz berdi. Iltimos, videongizni tekshirib qaytadan urunib ko'ring.",
            chat_id, progress_msg_id
        )
        clean_temp_files(user_id)
        del user_data[user_id]
        return

    file_size = os.path.getsize(output_path) / (1024 * 1024)
    if file_size > 50:
        bot.edit_message_text(
            "⚠️ Tayyor video hajmi 50MB dan oshib ketdi. Telegram yuklash limiti sababli yuborib bo'lmaydi.\n"
            "Iltimos, kichikroq video bilan urunib ko'ring.",
            chat_id, progress_msg_id
        )
        clean_temp_files(user_id)
        del user_data[user_id]
        return

    bot.edit_message_text(
        "✅ Video muvaffaqiyatli tayyorlandi!\n\n🎉 Sizning videongiz tayyor.\n📥 Quyidagi faylni yuklab olishingiz mumkin.",
        chat_id, progress_msg_id
    )

    with open(output_path, 'rb') as video_file:
        bot.send_video(
            chat_id,
            video_file,
            caption="✅ Sizning aylantirilgan videongiz",
            supports_streaming=True
        )

    bot.send_message(
        chat_id,
        "🔄 Yana video aylantirmoqchimisiz?\n\n📤 Yangi video yuboring."
    )

    clean_temp_files(user_id)
    del user_data[user_id]

# ------------------- FLASK WEBHOOK -------------------
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return jsonify({'status': 'ok'}), 200
    else:
        return jsonify({'status': 'error', 'message': 'Invalid content type'}), 403

# ------------------- O‘RNATISH/TOZALASH ENDPOINTLARI -------------------
@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    result = bot.set_webhook(url=WEBHOOK_URL)
    if result:
        return f"✅ Webhook muvaffaqiyatli o‘rnatildi: {WEBHOOK_URL}", 200
    else:
        return "❌ Webhook o‘rnatilmadi. URL to‘g‘riligini tekshiring.", 500

@app.route('/remove_webhook', methods=['GET'])
def remove_webhook():
    result = bot.remove_webhook()
    if result:
        return "✅ Webhook o‘chirildi", 200
    else:
        return "❌ Xatolik", 500

@app.route('/', methods=['GET'])
def index():
    return "🎬 Video Shape Converter Bot ishlamoqda. Webhook endpoint: /webhook"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)
