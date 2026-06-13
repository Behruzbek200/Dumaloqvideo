import os
import subprocess
import time
import shutil
from flask import Flask, request, jsonify
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN o'rnatilmagan!")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

TEMP_DIR = "temp_conversions"
os.makedirs(TEMP_DIR, exist_ok=True)
user_data = {}

def clean_temp_files(user_id):
    user_folder = os.path.join(TEMP_DIR, str(user_id))
    if os.path.exists(user_folder):
        shutil.rmtree(user_folder)

def convert_rectangle_to_round(input_path, output_path):
    """To'rtburchak videoni yumaloq qilish - soddalashtirilgan"""
    cmd = [
        'ffmpeg', '-i', input_path, '-y',
        '-vf', 'crop=min(iw,ih):min(iw,ih),scale=480:480',
        '-c:v', 'libx264', '-crf', '23', '-preset', 'fast',
        '-map', '0:a?', '-c:a', 'aac', '-b:a', '128k',
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"FFmpeg output: {result.stderr}")  # Debug uchun
    return result.returncode == 0

def convert_round_to_rectangle(input_path, output_path):
    """Yumaloq videoni to'rtburchak qilish - soddalashtirilgan"""
    cmd = [
        'ffmpeg', '-i', input_path, '-y',
        '-vf', 'scale=480:480,pad=480:480:(ow-iw)/2:(oh-ih)/2:black',
        '-c:v', 'libx264', '-crf', '23', '-preset', 'fast',
        '-map', '0:a?', '-c:a', 'aac', '-b:a', '128k',
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"FFmpeg output: {result.stderr}")  # Debug uchun
    return result.returncode == 0

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, 
        "🎬 Assalomu alaykum!\n\n"
        "To'rtburchak videoni yumaloq videoga yoki yumaloq videoni to'rtburchak videoga aylantirib beraman.\n\n"
        "📤 Davom etish uchun videongizni yuboring."
    )

@bot.message_handler(content_types=['video'])
def handle_video(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Tozalash
    clean_temp_files(user_id)
    user_folder = os.path.join(TEMP_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)

    # Yuklab olish
    status_msg = bot.reply_to(message, "⏳ Videongiz yuklanmoqda...")
    
    try:
        file_info = bot.get_file(message.video.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        input_path = os.path.join(user_folder, "input.mp4")
        with open(input_path, 'wb') as f:
            f.write(downloaded_file)
        
        bot.edit_message_text("✅ Video yuklandi! Endi formatni tanlang.", chat_id, status_msg.message_id)
        
        # Format tanlash tugmalari
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🔘 Yumaloq video", callback_data="to_round"),
            InlineKeyboardButton("⬜ To'rtburchak video", callback_data="to_rect")
        )
        
        bot.send_message(chat_id, "🎥 Qaysi formatga aylantirmoqchisiz?", reply_markup=markup)
        
        user_data[user_id] = {
            'input_path': input_path,
            'user_folder': user_folder
        }
        
    except Exception as e:
        bot.edit_message_text(f"❌ Xatolik: {str(e)}", chat_id, status_msg.message_id)

@bot.callback_query_handler(func=lambda call: True)
def handle_conversion(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if user_id not in user_data:
        bot.answer_callback_query(call.id, "❌ Xatolik! /start bilan qaytadan boshlang.")
        return

    bot.answer_callback_query(call.id, "✅ Qabul qilindi! Video tayyorlanmoqda...")

    # Jarayon xabari
    progress_msg = bot.send_message(chat_id, "⏳ Video tayyorlanmoqda. Iltimos, 1-2 daqiqa kuting...")

    data = user_data[user_id]
    input_path = data['input_path']
    user_folder = data['user_folder']
    
    output_path = os.path.join(user_folder, "output.mp4")
    
    # Konvertatsiya
    success = False
    if call.data == "to_round":
        success = convert_rectangle_to_round(input_path, output_path)
        convert_type = "yumaloq"
    else:
        success = convert_round_to_rectangle(input_path, output_path)
        convert_type = "to'rtburchak"

    if not success or not os.path.exists(output_path):
        bot.edit_message_text(
            "❌ Konvertatsiya davomida xatolik yuz berdi.\n\n"
            "Sabablari:\n"
            "• FFmpeg o'rnatilmagan (Render build command da ffmpeg ni qo'shing)\n"
            "• Video formati qo'llab-quvvatlanmasligi\n\n"
            "Yordam: @username",
            chat_id, progress_msg.message_id
        )
        clean_temp_files(user_id)
        del user_data[user_id]
        return

    # Hajm tekshiruvi
    file_size = os.path.getsize(output_path) / (1024 * 1024)
    if file_size > 50:
        bot.edit_message_text(
            f"⚠️ Tayyor video hajmi {file_size:.1f}MB (50MB dan oshib ketdi).\n"
            "Telegram cheklovi sababli yuborib bo'lmaydi.",
            chat_id, progress_msg.message_id
        )
        clean_temp_files(user_id)
        del user_data[user_id]
        return

    # Tayyor xabar
    bot.edit_message_text(
        f"✅ Video muvaffaqiyatli {convert_type} formatga o'tkazildi!\n\n"
        "📥 Tayyor video yuborilmoqda...",
        chat_id, progress_msg.message_id
    )

    # Videoni yuborish
    try:
        with open(output_path, 'rb') as video_file:
            bot.send_video(
                chat_id, 
                video_file, 
                caption=f"✅ Sizning {convert_type} videongiz tayyor!",
                supports_streaming=True,
                timeout=60
            )
        
        bot.send_message(chat_id, "🔄 Yana video aylantirmoqchimisiz?\n\n📤 Yangi video yuboring.")
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ Videoni yuborishda xatolik: {str(e)}")
    
    # Tozalash
    clean_temp_files(user_id)
    del user_data[user_id]

@bot.message_handler(func=lambda message: True)
def handle_other(message):
    bot.reply_to(message, "❓ Iltimos, video fayl yuboring yoki /start buyrug'ini bosing.")

# Flask webhook
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return jsonify({'status': 'ok'}), 200
    return jsonify({'status': 'error'}), 403

@app.route('/', methods=['GET'])
def index():
    return "🎬 Video Shape Converter Bot ishlamoqda"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
