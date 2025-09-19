from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters, CommandHandler, JobQueue
import requests
from bs4 import BeautifulSoup
import logging
import time
import os
from flask import Flask, jsonify
import threading

# === Loglama ===
logging.basicConfig(level=logging.INFO)

# === Token ===
API_KEY = os.getenv('TELEGRAM_TOKEN') or "7980506780:AAHcKJvk6LXFfa_Co5lvk-znFkTRCOzTNxI"

# === URL'ler ===
BASE_URL = "https://obs.itu.edu.tr/public/DersProgram/DersProgramSearch"
MAIN_URL = "https://obs.itu.edu.tr/public/DersProgram"
DERS_KAYIT_URL = "https://obs.itu.edu.tr/ogrenci/DersKayitIslemleri/DersKayit"

# === Veri Yapıları ===
WATCHED_COURSES = {}  # {chat_id: [(program, crn)]}
COMPLETED_COURSES = {}  # {chat_id: set((program, crn))} - Bildirim gönderilenler
LAST_REQUEST_TIME = {}

def load_program_codes():
    """Program kodlarını yükle"""
    try:
        resp = requests.get(MAIN_URL, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        programs = {}
        for opt in soup.select("select#dersBransKoduId option"):
            val = opt.get("value", "").strip()
            text = opt.text.strip()
            if val and text and text != "Ders Kodu Seçiniz":
                programs[text] = val
        print(f"✅ {len(programs)} program yüklendi")
        return programs
    except:
        # Fallback
        return {'END': '15', 'TUR': '34', 'KIM': '27', 'MAT': '26', 'FIZ': '28', 'BIL': '38'}

PROGRAM_KODLARI = load_program_codes()

def search_course(program_code, crn, is_background=False):
    """Ders ara - Boş kontenjan kontrolü"""
    print(f"🔍 {program_code}_{crn} {'[arka plan]' if is_background else ''}")
    
    if program_code not in PROGRAM_KODLARI:
        return f"❌ '{program_code}' bulunamadı\n💡 Örnek: END_12345"
    
    params = {
        'ProgramSeviyeTipiAnahtari': 'LS',
        'DersBransKoduId': PROGRAM_KODLARI[program_code]
    }
    
    try:
        resp = requests.get(BASE_URL, params=params, timeout=10)
        if resp.status_code != 200:
            return f"❌ OBS hatası ({resp.status_code})"
        
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("table tbody tr")
        
        for row in rows:
            cols = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cols) < 11 or cols[0] != crn:
                continue
            
            code = cols[1] or "Bilinmeyen"
            name = cols[2] or "Ders adı yok"
            kontenjan = int(cols[9]) if len(cols) > 9 and cols[9].isdigit() else 0
            yazilan = int(cols[10]) if len(cols) > 10 and cols[10].isdigit() else 0
            bos = kontenjan - yazilan
            
            print(f"📊 {code}: {kontenjan}/{yazilan} = {bos} boş")
            
            # ❌ SORUN 1 ÇÖZÜLDÜ: Boş kontenjan varsa BİLDİRİM GÖNDERME
            if bos > 0:
                # Bildirim gönder ve takibi DURDUR
                key = (program_code, crn)
                chat_id = next((cid for cid, courses in WATCHED_COURSES.items() if key in courses), None)
                if chat_id:
                    COMPLETED_COURSES.setdefault(chat_id, set()).add(key)
                    WATCHED_COURSES[chat_id].remove(key)
                    if not WATCHED_COURSES[chat_id]:
                        del WATCHED_COURSES[chat_id]
                
                return (
                    f"🟢 *KONTENJAN AÇILDI!*\n"
                    f"{'━' * 30}\n"
                    f"📘 *Ders:* `{code}`\n"
                    f"📖 *Ad:* {name}\n"
                    f"🆔 *CRN:* `{crn}`\n"
                    f"{'━' * 30}\n"
                    f"👥 *Kontenjan:* {kontenjan}\n"
                    f"📝 *Yazılan:* {yazilan}\n"
                    f"🟢 *Boş:* {bos}\n"
                    f"{'━' * 30}\n"
                    f"🔗 *Kayıt:* {DERS_KAYIT_URL}"
                )
            else:
                # Kontenjan dolu - ilk sorguda mesaj ver
                if not is_background:
                    return f"🔴 *Kontenjan dolu!*\n📘 *Ders:* `{code}`\n🆔 *CRN:* `{crn}`\n⏳ *Boşalınca bildiririm.*"
                return None  # Arka planda sessiz kal
        
        return f"❌ CRN {crn} bulunamadı"
        
    except Exception as e:
        print(f"💥 Hata: {e}")
        return f"💥 *Arama hatası:* {str(e)[:50]}"

# === KOMUTLAR ===
async def start_command(update, context):
    """Menü - DÜZENLİ VERSİYON"""
    keyboard = [
        [CommandHandler("help", "Yardım"), CommandHandler("status", "Durum")],
        [CommandHandler("cancel", "Takibi İptal Et")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎓 *İTÜ DERS KONTENJAN BOTU*\n\n"
        "👋 Hoş geldiniz!\n\n"
        "📝 *Kullanım:* `PROGRAM_CRN`\n"
        "📋 *Örnek:* `END_12345`\n\n"
        "🔍 *Popüler:* END, TUR, MAT, KIM, BHB\n\n"
        "⏳ *Otomatik takip:* Kontenjan açılınca bildirim\n"
        "📊 *Komutlar:* Aşağıdaki menüden seçin",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def help_command(update, context):
    """Yardım menüsü"""
    await update.message.reply_text(
        "🆘 *YARDIM MENÜSÜ*\n\n"
        "📖 *Temel Kullanım:*\n"
        "• `END_12345` - Endüstri dersi\n"
        "• `TUR_67890` - Türkçe dersi\n\n"
        "📋 *Popüler Kodlar:*\n"
        "• `END` - Endüstri Müh. (İngilizce)\n"
        "• `TUR` - Türkçe Programlar\n"
        "• `MAT` - Matematik\n"
        "• `KIM` - Kimya\n"
        "• `BHB` - Biyomedikal\n\n"
        "⏳ *Takip Sistemi:*\n"
        "• Kontenjan dolu → Takibe al\n"
        "• Boşalınca → Tek bildirim (spam yok)\n"
        "• `/status` - Takip listesi\n"
        "• `/cancel` - Tümünü iptal"
    )

async def status_command(update, context):
    """Takip durumu - DÜZENLİ"""
    chat_id = update.effective_chat.id
    
    if chat_id in WATCHED_COURSES and WATCHED_COURSES[chat_id]:
        active = [(p, c) for p, c in WATCHED_COURSES[chat_id] if (p, c) not in COMPLETED_COURSES.get(chat_id, set())]
        completed = [(p, c) for p, c in COMPLETED_COURSES.get(chat_id, set())]
        
        text = f"📊 *TAKİP DURUMU*\n\n"
        text += f"🔄 *Aktif Takip:* {len(active)} ders\n"
        
        if active:
            text += "📝 *Bekleyenler:*\n"
            for p, c in active[:5]:  # İlk 5 tanesini göster
                text += f"• `{p}_{c}`\n"
            if len(active) > 5:
                text += f"... ve {len(active)-5} tane daha\n"
        
        if completed:
            text += f"\n✅ *Tamamlanan:* {len(completed)} ders\n"
            for p, c in completed[-3:]:  # Son 3 tanesini göster
                text += f"• `{p}_{c}` (bildirim gönderildi)\n"
        
        text += f"\n❌ *İptal:* `/cancel`\n⏳ *Kontrol:* Her dakika"
    else:
        text = "ℹ️ *Henüz takip ettiğiniz ders yok*\n\n🔄 *Yeni ekleyin:* `END_12345`"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def cancel_command(update, context):
    """Takip iptali - DÜZENLİ"""
    chat_id = update.effective_chat.id
    
    if chat_id in WATCHED_COURSES and WATCHED_COURSES[chat_id]:
        canceled = list(WATCHED_COURSES[chat_id])
        del WATCHED_COURSES[chat_id]
        if chat_id in COMPLETED_COURSES:
            del COMPLETED_COURSES[chat_id]
        
        text = f"❌ *TAKİP İPTAL EDİLDİ!*\n\n"
        text += f"📋 *İptal edilen ({len(canceled)}):*\n"
        for p, c in canceled[:5]:
            text += f"• `{p}_{c}`\n"
        if len(canceled) > 5:
            text += f"... ve {len(canceled)-5} tane daha\n"
        text += f"\n🔄 *Yeni ekleyin:* `END_12345`"
        
        # Job'ları iptal et
        for p, c in canceled:
            job_name = f"{chat_id}_{p}_{c}"
            jobs = context.application.job_queue.get_jobs_by_name(job_name)
            for job in jobs:
                job.schedule_removal()
    else:
        text = "ℹ️ *İptal edilecek takip yok*\n\n🔄 *Yeni ekleyin:* `END_12345`"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    """Ana mesaj işleyici - DÜZENLİ"""
    user = update.effective_user
    text = update.message.text.strip().upper()
    chat_id = update.effective_chat.id
    
    print(f"💬 {user.first_name}: '{text}' [Chat: {chat_id}]")
    
    # Komutlar
    if text in ['/HELP', '/STATUS', '/CANCEL']:
        if text == '/HELP':
            await help_command(update, context)
        elif text == '/STATUS':
            await status_command(update, context)
        elif text == '/CANCEL':
            await cancel_command(update, context)
        return
    
    # Ders sorgusu
    if '_' in text:
        parts = text.split('_')
        if len(parts) == 2:
            program_code, crn = parts
            if len(program_code) == 3 and crn.isdigit():
                # Rate limiting
                current_time = time.time()
                if chat_id not in LAST_REQUEST_TIME:
                    LAST_REQUEST_TIME[chat_id] = 0
                elapsed = current_time - LAST_REQUEST_TIME[chat_id]
                if elapsed < 2:
                    await asyncio.sleep(2 - elapsed)
                
                status_msg = await update.message.reply_text(
                    f"🔍 *Sorgulanıyor...*\n📂 `{program_code}_{crn}`"
                    , parse_mode='Markdown'
                )
                
                try:
                    result = search_course(program_code, crn)
                    LAST_REQUEST_TIME[chat_id] = time.time()
                    
                    await status_msg.delete()
                    
                    if result:
                        await update.message.reply_text(result, parse_mode='Markdown')
                        
                        # Takibe alma (sadece doluysa)
                        if "Kontenjan dolu" in result:
                            if chat_id not in WATCHED_COURSES:
                                WATCHED_COURSES[chat_id] = []
                            if (program_code, crn) not in WATCHED_COURSES[chat_id]:
                                WATCHED_COURSES[chat_id].append((program_code, crn))
                                context.application.job_queue.run_repeating(
                                    check_course,
                                    interval=60,
                                    data=(chat_id, program_code, crn),
                                    name=f"{chat_id}_{program_code}_{crn}"
                                )
                                print(f"⏳ {program_code}_{crn} takibe alındı")
                
                except Exception as e:
                    print(f"💥 Hata: {e}")
                    await status_msg.delete()
                    await update.message.reply_text(f"💥 *Hata:* {str(e)[:50]}")
                return
    
    # Ana menü
    await update.message.reply_text(
        "🎓 *İTÜ DERS BOTU*\n\n"
        "📝 *Kullanım:* `PROGRAM_CRN`\n\n"
        "📋 *Örnek:* `END_12345`\n\n"
        "🔍 *Popüler:* END, TUR, MAT, KIM\n\n"
        "❓ *Yardım:* `/help`\n"
        "📊 *Status:* `/status`"
        , parse_mode='Markdown'
    )

async def check_course(context: ContextTypes.DEFAULT_TYPE):
    """Arka plan kontrolü - BİLDİRİM BİR KEZ"""
    job = context.job
    chat_id, program_code, crn = job.data
    
    print(f"⏲️ Kontrol: {program_code}_{crn}")
    
    result = search_course(program_code, crn, is_background=True)
    
    if result and "KONTENJAN AÇILDI" in result:
        # Bildirim gönder
        await context.bot.send_message(chat_id=chat_id, text=result, parse_mode='Markdown')
        
        # Takibi DURDUR (spam önleme)
        if chat_id in WATCHED_COURSES:
            WATCHED_COURSES[chat_id].remove((program_code, crn))
            if not WATCHED_COURSES[chat_id]:
                del WATCHED_COURSES[chat_id]
        
        # Job'u iptal et
        job.schedule_removal()
        print(f"🛑 {program_code}_{crn} takibi durduruldu (bildirim gönderildi)")

# === RAILWAY HEALTH CHECK ===
def create_health_server():
    """502 hatası için Flask server"""
    app = Flask(__name__)
    
    @app.route('/')
    def root():
        return jsonify({
            "status": "healthy",
            "service": "İTÜ Ders Bot",
            "uptime": "100%"
        })
    
    @app.route('/health')
    def health():
        return jsonify({"status": "ok"})
    
    port = int(os.environ.get('PORT', 8080))
    print(f"🌐 Health server: port {port}")
    
    app.run(host='0.0.0.0', port=port, debug=False)

def main():
    """Ana fonksiyon"""
    global LAST_REQUEST_TIME
    LAST_REQUEST_TIME = {}
    
    print("🤖 İTÜ DERS BOTU v3.4 - RAILWAY")
    print(f"🔑 Token: {len(API_KEY)} karakter")
    
    # Telegram bot
    application = ApplicationBuilder().token(API_KEY).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Telegram bot hazır!")
    
    # Health server arka planda
    server_thread = threading.Thread(target=create_health_server, daemon=True)
    server_thread.start()
    
    print("🌐 Health server aktif")
    
    # Telegram polling
    print("🚀 Polling başlıyor...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
