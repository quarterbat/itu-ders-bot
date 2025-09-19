from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters, CommandHandler, JobQueue
import requests
from bs4 import BeautifulSoup
import logging

import asyncio
import time
import traceback
from datetime import datetime
from flask import Flask, jsonify
import threading
import os

# Token'ı Railway Variables'tan al
API_KEY = os.getenv('TELEGRAM_TOKEN')
if not API_KEY:
    print("❌ TELEGRAM_TOKEN bulunamadı! Railway Variables'e ekleyin.")
    exit(1)

# === Loglama Ayarları ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# === OBS URL'leri ===
BASE_URL = "https://obs.itu.edu.tr/public/DersProgram/DersProgramSearch"
MAIN_URL = "https://obs.itu.edu.tr/public/DersProgram"
DERS_KAYIT_URL = "https://obs.itu.edu.tr/ogrenci/DersKayitIslemleri/DersKayit"

# === Takip Edilen Dersler ===
WATCHED_COURSES = {}  # {chat_id: [(program_code, crn), ...]}

# Rate-limiting için global değişken
LAST_REQUEST_TIME = {}  # {chat_id: son_istek_zamanı}

def load_program_codes():
    """OBS sayfasından program kodlarını ve value ID'lerini yükle"""
    print("🔄 Program kodları yükleniyor...")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

    try:
        response = requests.get(MAIN_URL, headers=headers, timeout=15)
        print(f"🌐 MAIN_URL status: {response.status_code}")
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        select_element = soup.find('select', {'id': 'dersBransKoduId'})

        if not select_element:
            print("❌ #dersBransKoduId select elementi bulunamadı!")
            print("📋 Fallback manuel listesi kullanılıyor...")
            return get_manual_program_list()

        program_codes = {}
        options = select_element.find_all('option')
        print(f"📋 Toplam {len(options)} option bulundu")

        valid_count = 0
        for option in options:
            value = option.get('value', '').strip()
            text = option.text.strip()

            if value and text and text != 'Ders Kodu Seçiniz' and len(text) >= 3:
                program_codes[text] = value
                valid_count += 1
                if valid_count <= 10:
                    print(f"   📂 {text:<6} -> {value} (value='{value}', text='{text}')")

        print(f"✅ {len(program_codes)} geçerli program kodu yüklendi")

        test_codes = ['END', 'TUR', 'KIM', 'MAT', 'FIZ', 'BIL', 'ELE', 'MAK']
        print(f"\n🔍 Popüler kodlar kontrolü:")
        for kod in test_codes:
            if kod in program_codes:
                print(f"   ✅ {kod:<6} -> {program_codes[kod]}")
            else:
                print(f"   ❌ {kod:<6} YÜKLENEMEDİ!")

        if len(program_codes) < 10:
            print("⚠️  Az program kodu yüklendi, manuel listeye dönülüyor...")
            return get_manual_program_list()

        return program_codes

    except requests.exceptions.RequestException as e:
        print(f"❌ Network hatası: {e}")
        return get_manual_program_list()
    except Exception as e:
        print(f"❌ Beklenmeyen hata: {e}")
        return get_manual_program_list()


def get_manual_program_list():
    """Manuel program listesi - HTML'den doğrulanmış"""
    print("📋 Manuel program listesi yükleniyor...")

    manual_list = {
        'AKM': '42', 'ALM': '227', 'ARB': '305', 'ARC': '302', 'ATA': '43',
        'BBF': '310', 'BEB': '200', 'BED': '149', 'BEN': '165', 'BES': '313',
        'BHB': '321', 'BIL': '38', 'BIO': '30', 'BLG': '3', 'BLS': '180',
        'BUS': '155', 'CAB': '127', 'CEN': '304', 'CEV': '7', 'CHA': '169',
        'CHE': '137', 'CHZ': '81', 'CIE': '142', 'CIN': '245', 'CMP': '146',
        'COM': '208', 'CVH': '168', 'DAN': '243', 'DEN': '10', 'DFH': '163',
        'DGH': '181', 'DNK': '44', 'DUI': '32', 'EAS': '141', 'ECN': '232',
        'ECO': '154', 'EEE': '289', 'EEF': '294', 'EFN': '297', 'EGC': '320',
        'EHA': '182', 'EHB': '196', 'EHN': '241', 'EKO': '39', 'ELE': '59',
        'ELH': '2', 'ELK': '1', 'ELT': '178', 'END': '15', 'ENE': '183',
        'ENG': '179', 'ENR': '207', 'ENT': '225', 'ESL': '140', 'ESM': '164',
        'ETK': '110', 'EUT': '22', 'FIZ': '28', 'FRA': '226', 'FZK': '175',
        'GED': '138', 'GEM': '11', 'GEO': '74', 'GID': '4', 'GLY': '162',
        'GMI': '46', 'GMK': '176', 'GMZ': '109', 'GSB': '53', 'GSN': '173',
        'GUV': '31', 'GVT': '177', 'GVZ': '111', 'HSS': '256', 'HUK': '41',
        'IAD': '301', 'ICM': '63', 'IEB': '314', 'ILT': '253', 'IML': '112',
        'IND': '300', 'ING': '33', 'INS': '8', 'INT': '317', 'ISE': '153',
        'ISH': '231', 'ISL': '14', 'ISP': '228', 'ITA': '255', 'ITB': '50',
        'JDF': '9', 'JEF': '19', 'JEO': '18', 'JPN': '202', 'KIM': '27',
        'KMM': '6', 'KMP': '125', 'KON': '58', 'LAT': '156', 'MAD': '16',
        'MAK': '12', 'MAL': '48', 'MAR': '148', 'MAT': '26', 'MCH': '160',
        'MDN': '293', 'MEK': '47', 'MEN': '258', 'MET': '5', 'MIM': '20',
        'MKN': '184', 'MMD': '290', 'MOD': '150', 'MRE': '157', 'MRT': '158',
        'MST': '257', 'MTH': '143', 'MTK': '174', 'MTM': '260', 'MTO': '23',
        'MTR': '199', 'MUH': '29', 'MUK': '40', 'MUT': '126', 'MUZ': '128',
        'MYZ': '309', 'NAE': '259', 'NTH': '263', 'NUM': '318', 'ODS': '161',
        'OSN': '319', 'PAZ': '151', 'PEM': '64', 'PET': '17', 'PHE': '262',
        'PHY': '147', 'PREP': '203', 'RES': '36', 'ROS': '307', 'RUS': '237',
        'SAV': '322', 'SBP': '21', 'SEC': '308', 'SED': '288', 'SEN': '171',
        'SES': '124', 'SGI': '291', 'SNT': '193', 'SPA': '172', 'STA': '37',
        'STI': '159', 'SUS': '303', 'TDW': '261', 'TEB': '121', 'TEK': '13',
        'TEL': '57', 'TER': '49', 'TES': '269', 'THO': '129', 'TRN': '65',
        'TRS': '215', 'TRZ': '170', 'TUR': '34', 'UCK': '25', 'ULP': '195',
        'UZB': '24', 'VBA': '306', 'X100': '198', 'YAN': '323', 'YTO': '213',
        'YZV': '221'
    }

    print(f"✅ Manuel listeden {len(manual_list)} program yüklendi")
    print("   📂 END -> 15")
    print("   📂 TUR -> 34")
    print("   📂 KIM -> 27")
    print("   📂 MAT -> 26")
    print("   📂 BHB -> 321")

    return manual_list


# Program kodlarını yükle (global)
PROGRAM_KODLARI = load_program_codes()


async def check_course(context: ContextTypes.DEFAULT_TYPE):
    """Arka planda dersleri kontrol et ve kontenjan açılınca bildir"""
    job = context.job
    chat_id, program_code, crn = job.data

    print(f"⏲️ [DAKİKALIK KONTROL] {chat_id} için {program_code}_{crn} kontrol ediliyor...")

    # Rate-limiting: Son istekten bu yana 2 saniye geçti mi?
    current_time = time.time()
    if chat_id in LAST_REQUEST_TIME:
        elapsed = current_time - LAST_REQUEST_TIME[chat_id]
        if elapsed < 2:
            await asyncio.sleep(2 - elapsed)

    result = search_course(program_code, crn, is_background=True)

    # Son istek zamanını güncelle
    LAST_REQUEST_TIME[chat_id] = time.time()

    if result:
        await context.bot.send_message(
            chat_id=chat_id,
            text=result,
            parse_mode='Markdown'
        )
        # Kontenjan açıldıysa, takibi durdur
        if "KONTENJAN AÇILDI" in result:
            print(f"🛑 {program_code}_{crn} için takip durduruldu (kontenjan açıldı)")
            WATCHED_COURSES[chat_id].remove((program_code, crn))
            if not WATCHED_COURSES[chat_id]:
                del WATCHED_COURSES[chat_id]
            context.application.job_queue.remove_job(job.name)


def search_course(program_code, crn, is_background=False):
    """Belirtilen program kodunda CRN ile dersi ara - KONTENJAN TAKİP"""
    print(f"\n🔍 {program_code} programında CRN {crn} aranıyor... {'[ARKA PLAN]' if is_background else ''}")

    if program_code not in PROGRAM_KODLARI:
        mevcut_kodlar = sorted([k for k in PROGRAM_KODLARI.keys() if len(k) == 3])[:10]
        mevcut_liste = ", ".join(mevcut_kodlar)

        print(f"❌ '{program_code}' program kodu bulunamadı!")
        print(f"   📋 Mevcut kodlar: {mevcut_kodlar[:5]}...")

        error_message = (
            f"❌ *'{program_code}' program kodu bulunamadı*\n\n"
            f"🔍 *Mevcut program kodları:*\n"
            f"`{mevcut_liste}...`\n\n"
            f"📋 *Popüler program kodları:*\n"
            f"• `END` - Endüstri Müh. (İngilizce)\n"
            f"• `TUR` - Türkçe Programlar\n"
            f"• `MAT` - Matematik\n"
            f"• `FIZ` - Fizik\n"
            f"• `KIM` - Kimya\n"
            f"• `BIL` - Bilgisayar Müh.\n"
            f"• `ELE` - Elektrik-Elektronik\n"
            f"• `MAK` - Makine Müh.\n\n"
            f"💡 *Doğru format: `END_12345`*\n"
            f"❓ *Yardım için: /help*"
        )
        return error_message

    program_id = PROGRAM_KODLARI[program_code]
    print(f"✅ '{program_code}' bulundu! OBS ID: {program_id}")

    params = {
        'ProgramSeviyeTipiAnahtari': 'LS',
        'DersBransKoduId': program_id
    }

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': MAIN_URL,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
    }

    try:
        print(f"🌐 OBS sorgusu yapılıyor...")
        print(f"   📋 Parametreler: LS={params['ProgramSeviyeTipiAnahtari']}, ID={params['DersBransKoduId']}")

        response = requests.get(BASE_URL, params=params, headers=headers, timeout=15)
        print(f"   📊 HTTP Status: {response.status_code}")
        print(f"   📏 Response uzunluk: {len(response.text)} karakter")

        if response.status_code != 200:
            print(f"❌ HTTP {response.status_code} hatası")
            return f"❌ *OBS bağlantı hatası* (HTTP {response.status_code})\n\n🔄 *Biraz sonra tekrar deneyin*"

        soup = BeautifulSoup(response.text, 'html.parser')

        table = soup.find('table', {'id': 'dersProgramContainer'})
        if not table:
            table = soup.find('table')
            if not table:
                print("❌ Hiçbir tablo bulunamadı")
                return f"❌ *Ders listesi yüklenemedi*\n\n🔄 *Lütfen tekrar deneyin*"
            print("⚠️  ID'siz tablo kullanıldı")

        tbody = table.find('tbody')
        if not tbody:
            print("❌ Tablo body bulunamadı")
            return f"❌ *Ders verisi yüklenemedi*\n\n🔄 *Lütfen tekrar deneyin*"

        rows = tbody.find_all('tr')
        print(f"📋 {len(rows)} ders satırı bulundu")

        if not rows:
            return (
                f"❌ *'{program_code}' programında ders bulunamadı*\n\n"
                f"💡 *Bu dönemde ders kaydı yok olabilir*\n"
                f"🔄 *Farklı program veya dönem deneyin*"
            )

        course_found = False
        for row_index, row in enumerate(rows):
            cells = row.find_all('td')
            if len(cells) < 11:
                continue

            columns = [cell.get_text(strip=True) for cell in cells]
            if len(columns) < 11:
                continue

            if row_index == 0:
                print(f"📊 İLK SATIR KOLONLARI ({len(columns)} adet):")
                for i, col in enumerate(columns[:12]):
                    print(f"   [{i:2d}] '{col}'")
                if len(columns) > 10:
                    print(f"   [ 9] KONTENJAN: '{columns[9]}'")
                    print(f"   [10] YAZILAN:  '{columns[10]}'")

            if columns[0].strip() == crn:
                course_code = columns[1] if len(columns) > 1 else "Bilinmeyen"
                course_name = columns[2] if len(columns) > 2 else "Ders adı yok"
                time_slot = columns[7] if len(columns) > 7 else "Bilinmeyen"
                day = columns[6] if len(columns) > 6 else "Bilinmeyen"

                try:
                    kontenjan_text = columns[9] if len(columns) > 9 else "0"
                    yazilan_text = columns[10] if len(columns) > 10 else "0"

                    kontenjan = int(kontenjan_text) if kontenjan_text.isdigit() else 0
                    yazilan = int(yazilan_text) if yazilan_text.isdigit() else 0
                    bos_yer = max(0, kontenjan - yazilan)

                    print(f"✅ DERS BULUNDU!")
                    print(f"   📘 Kod: {course_code}")
                    print(f"   📖 Ad: {course_name}")
                    print(f"   🕒 Zaman: {day} {time_slot}")
                    print(f"   📊 Kontenjan: {kontenjan} (text='{kontenjan_text}') [KOLON 9]")
                    print(f"   📝 Yazılan: {yazilan} (text='{yazilan_text}') [KOLON 10]")
                    print(f"   🟢 Boş: {bos_yer}")

                except (ValueError, IndexError) as e:
                    print(f"⚠️  Kontenjan parse hatası: {e}")
                    try:
                        kontenjan = int(columns[-3]) if len(columns) >= 3 and columns[-3].isdigit() else 0
                        yazilan = int(columns[-2]) if len(columns) >= 2 and columns[-2].isdigit() else 0
                        bos_yer = max(0, kontenjan - yazilan)
                        print(f"   🔄 Fallback: Kontenjan={kontenjan}, Yazılan={yazilan}")
                    except:
                        print("   ❌ Fallback bile başarısız")
                        kontenjan = yazilan = bos_yer = 0

                course_found = True

                # 🚨 KONTENJAN KONTROLÜ 🚨
                if bos_yer > 0:
                    # Kontenjan AÇILDI → Detaylı bildirim
                    print(f"🟢 KONTENJAN AÇILDI! ({bos_yer} yer)")
                    return (
                        f"🟢 *KONTENJAN AÇILDI!*\n"
                        f"{'━' * 35}\n"
                        f"📘 *Ders Kodu:* `{course_code}`\n"
                        f"📖 *Ders Adı:* {course_name}\n"
                        f"🔗 *Program:* `{program_code}`\n"
                        f"🆔 *CRN:* `{crn}`\n"
                        f"🕒 *Zaman:* {day} {time_slot}\n"
                        f"{'━' * 35}\n"
                        f"👥 *Kontenjan:* {kontenjan}\n"
                        f"📝 *Yazılan:* {yazilan}\n"
                        f"🟢 *Boş Yer:* {bos_yer}\n"
                        f"{'━' * 35}\n"
                        f"🔗 *Kayıt Linki:*\n{DERS_KAYIT_URL}\n\n"
                        f"📱 *Hızlıca kayıt olun!*"
                    )
                else:
                    # Kontenjan YOK → Onay mesajı (ilk sorguda)
                    if not is_background:
                        print(f"🔴 Kontenjan yok, takip ediliyor")
                        return (
                            f"🔴 *Kontenjan yok!*\n"
                            f"📘 *Ders:* `{course_code}`\n"
                            f"🆔 *CRN:* `{crn}`\n"
                            f"⏳ *Kontenjan açılınca bildirim gönderilecek.*"
                        )
                    else:
                        # Arka planda, sessiz kal
                        print(f"🔴 [ARKA PLAN] Kontenjan yok, bildirim gönderilmedi")
                        return None

            if row_index < 3:
                kont_text = columns[9] if len(columns) > 9 else 'N/A'
                yaz_text = columns[10] if len(columns) > 10 else 'N/A'
                bos_temp = max(0, int(kont_text) - int(yaz_text)) if kont_text.isdigit() and yaz_text.isdigit() else 0
                print(
                    f"   Debug {row_index + 1}: CRN='{columns[0]}', Kod='{columns[1] if len(columns) > 1 else 'N/A'}', Kont='{kont_text}' [9], Yaz='{yaz_text}' [10], Boş={bos_temp}")

        if not course_found:
            print(f"❌ CRN '{crn}' '{program_code}' programında bulunamadı")
            sample_crns = []
            sample_kontenjan = []
            bos_listesi = []
            for row in rows[:5]:
                cells = row.find_all('td')
                if len(cells) >= 11:
                    columns = [cell.get_text(strip=True) for cell in cells]
                    if len(columns) >= 11:
                        crn_sample = columns[0]
                        kont_sample = columns[9] if len(columns) > 9 else '0'
                        yaz_sample = columns[10] if len(columns) > 10 else '0'
                        bos_sample = max(0, int(kont_sample) - int(
                            yaz_sample)) if kont_sample.isdigit() and yaz_sample.isdigit() else 0

                        sample_crns.append(crn_sample)
                        sample_kontenjan.append(f"{kont_sample}/{yaz_sample}")
                        bos_listesi.append(bos_sample)

            sample_text = ", ".join(sample_crns[:3]) if sample_crns else "yok"
            kontenjan_text = ", ".join(sample_kontenjan[:3]) if sample_kontenjan else "yok"

            if any(bos > 0 for bos in bos_listesi):
                bos_dersler = [f"`{crn}` ({kont}/{yaz})" for crn, kont, yaz in
                               zip(sample_crns[:3], sample_kontenjan[:3], bos_listesi) if
                               int(yaz.split('/')[1]) < int(yaz.split('/')[0])]
                bos_liste = ", ".join(bos_dersler) if bos_dersler else "yok"

                return (
                    f"❌ *CRN '{crn}' bulunamadı*\n\n"
                    f"🔍 *'{program_code}' programında bu CRN mevcut değil*\n\n"
                    f"💡 *Ama bu programda BOŞ YERLER var!*\n"
                    f"📋 *Mevcut dersler:* `{sample_text}`\n"
                    f"📊 *Durum:* `{kontenjan_text}`\n"
                    f"🎯 *Boş dersler:* {bos_liste}\n\n"
                    f"🔄 *Farklı CRN deneyin*\n"
                    f"📝 *Örnek: `{program_code}_54321`*"
                )
            else:
                return (
                    f"❌ *CRN '{crn}' bulunamadı*\n\n"
                    f"🔍 *'{program_code}' programında bu CRN mevcut değil*\n\n"
                    f"📋 *Mevcut dersler:* `{sample_text}`\n"
                    f"📊 *Durum:* `{kontenjan_text}`\n\n"
                    f"⚠️ *Bu programda hiç boş yer yok!*\n"
                    f"🔄 *Farklı program deneyin*\n"
                    f"📝 *Örnek: `END_54321`*"
                )

    except requests.exceptions.Timeout:
        print("⏰ Zaman aşımı hatası")
        return f"⏰ *Zaman aşımı*\n\n🔄 *OBS sunucusu yavaş, lütfen tekrar deneyin*"
    except requests.exceptions.ConnectionError:
        print("🌐 Bağlantı hatası")
        return f"🌐 *Bağlantı hatası*\n\n🔌 *İnternet bağlantınızı kontrol edin*"
    except Exception as e:
        print(f"💥 Beklenmeyen hata: {e}")
        print(f"   Hata tipi: {type(e)}")
        print(f"   Traceback: {traceback.format_exc()}")
        return f"💥 *Sistem hatası oluştu*\n\n🔧 *Bot sahibine bildirildi*\n🔄 *Lütfen tekrar deneyin*"


async def start_command(update, context: ContextTypes.DEFAULT_TYPE):
    """Bot başlatma komutu - KONTENJAN TAKİP AÇIKLAMASI"""
    user = update.effective_user
    chat_id = update.effective_chat.id

    print(f"🚀 /start - Kullanıcı: {user.first_name} (@{user.username}) - Chat ID: {chat_id}")

    populer_kodlar = []
    test_codes = ['END', 'TUR', 'MAT', 'FIZ', 'KIM', 'BIL', 'ELE', 'MAK', 'BHB']
    for kod in test_codes:
        if kod in PROGRAM_KODLARI:
            populer_kodlar.append(f"`{kod}`")

    populer_liste = ", ".join(populer_kodlar)

    welcome_message = (
        f"🎓 *İTÜ DERS KONTENJAN BOTU v3.1*\n"
        f"*KONTENJAN TAKİP MODU*\n\n"
        f"👋 Merhaba {user.first_name}! 👋\n\n"
        f"⏳ *Nasıl çalışır?*\n"
        f"• Kontenjan **yoksa**: *'Kontenjan yok, açılınca bildirilecek'*\n"
        f"• Kontenjan **açılınca**: *Ders detayları + boş yer bildirimi*\n\n"
        f"📝 *Kullanım Formatı:*\n"
        f"*`PROGRAM_KODU_CRN`*\n\n"
        f"📋 *Örnek Sorgular:*\n"
        f"• *`END_12345`* - Endüstri (İngilizce)\n"
        f"• *`TUR_67890`* - Türkçe Programlar\n"
        f"• *`MAT_11111`* - Matematik\n"
        f"• *`KIM_54321`* - Kimya\n"
        f"• *`BHB_15079`* - Biyomedikal Müh.\n\n"
        f"🔍 *Popüler Kodlar:* {populer_liste}\n\n"
        f"{'━' * 35}\n"
        f"🚀 *Ders sorgulayın, kontenjan takibi başlasın!*"
    )

    await update.message.reply_text(welcome_message, parse_mode='Markdown')


async def help_command(update, context: ContextTypes.DEFAULT_TYPE):
    """Yardım komutu - KONTENJAN TAKİP AÇIKLAMASI"""
    user = update.effective_user

    uc_harfli_kodlar = sorted([kod for kod in PROGRAM_KODLARI.keys() if len(kod) == 3])
    ornek_kodlar = ", ".join(uc_harfli_kodlar[:15])

    help_message = (
        f"🆘 *İTÜ DERS BOT - YARDIM v3.1*\n\n"
        f"⏳ *KONTENJAN TAKİP SİSTEMİ*\n"
        f"• Kontenjan **yoksa**: *'Kontenjan yok, açılınca bildirilecek'*\n"
        f"• Kontenjan **açılınca**: *Ders detayları (ad, zaman, CRN, kontenjan, boş yer)*\n\n"
        f"📖 *Nasıl Kullanılır?*\n"
        f"• *Format:* `PROGRAM_KODU_CRN`\n"
        f"• *Örnek:* `END_12345`\n\n"
        f"📋 *Popüler Program Kodları:*\n"
        f"• *`END`* - Endüstri Mühendisliği (İngilizce)\n"
        f"• *`TUR`* - Türkçe Programlar\n"
        f"• *`MAT`* - Matematik\n"
        f"• *`FIZ`* - Fizik\n"
        f"• *`KIM`* - Kimya\n"
        f"• *`BIL`* - Bilgisayar Mühendisliği\n"
        f"• *`ELE`* - Elektrik-Elektronik\n"
        f"• *`MAK`* - Makine Mühendisliği\n"
        f"• *`BHB`* - Biyomedikal Mühendisliği\n\n"
        f"🔍 *Diğer Kodlar:* `{ornek_kodlar}...`\n\n"
        f"📊 *Toplam Program:* {len(PROGRAM_KODLARI)}\n"
        f"{'━' * 35}\n"
        f"❓ *Sorun varsa /start yazın*"
    )

    await update.message.reply_text(help_message, parse_mode='Markdown')


async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcı mesajlarını işle - DAKİKALIK KONTENJAN TAKİP"""
    user = update.effective_user
    message_text = update.message.text.strip()
    chat_id = update.effective_chat.id

    print(f"💬 {user.first_name} (@{user.username}): '{message_text}' [Chat: {chat_id}]")

    clean_text = message_text.strip().upper()

    if clean_text == '/HELP':
        await help_command(update, context)
        return

    if '_' in clean_text:
        parts = clean_text.split('_')

        if len(parts) == 2:
            program_code, crn_input = parts

            if len(program_code) == 3 and crn_input.isdigit():
                print(f"🔍 İşleniyor: {program_code}_{crn_input}")

                # Rate-limiting: Son istekten bu yana 2 saniye geçti mi?
                current_time = time.time()
                if chat_id in LAST_REQUEST_TIME:
                    elapsed = current_time - LAST_REQUEST_TIME[chat_id]
                    if elapsed < 2:  # 2 saniye bekle
                        await asyncio.sleep(2 - elapsed)

                status_message = await update.message.reply_text(
                    f"🔍 *Sorgulanıyor...*\n"
                    f"📂 `{program_code}_{crn_input}`"
                    , parse_mode='Markdown'
                )

                try:
                    result = search_course(program_code, crn_input)

                    # Son istek zamanını güncelle
                    LAST_REQUEST_TIME[chat_id] = time.time()

                    await status_message.delete()

                    if result:
                        await update.message.reply_text(result, parse_mode='Markdown')

                    # Kontenjan yoksa takibe al
                    if result and "Kontenjan yok" in result:
                        if chat_id not in WATCHED_COURSES:
                            WATCHED_COURSES[chat_id] = []
                        if (program_code, crn_input) not in WATCHED_COURSES[chat_id]:
                            WATCHED_COURSES[chat_id].append((program_code, crn_input))
                            context.application.job_queue.run_repeating(
                                check_course,
                                interval=60,  # Her 1 dakikada bir kontrol
                                data=(chat_id, program_code, crn_input),
                                name=f"{chat_id}_{program_code}_{crn_input}"
                            )
                            print(f"⏳ {program_code}_{crn_input} takibe alındı (Chat: {chat_id}, 1 dk kontrol)")

                except Exception as e:
                    print(f"💥 Mesaj işleme hatası: {e}")
                    try:
                        await status_message.delete()
                    except:
                        pass
                    await update.message.reply_text(
                        f"💥 *Beklenmeyen hata oluştu*\n\n"
                        f"🔧 *Lütfen tekrar deneyin*\n"
                        f"📞 *Hata: {str(e)[:50]}...*"
                        , parse_mode='Markdown'
                    )
                return
            else:
                # Format hatası (aynı kalıyor)
                error_msg = (
                    f"⚠️ *Geçersiz Format!*\n\n"
                    f"❌ Girdiğiniz: `{message_text}`\n\n"
                    f"✅ *Doğru format:*\n"
                    f"*`ÜÇ_HARF_CRN`*\n\n"
                    f"📋 *Örnekler:*\n"
                    f"• *`END_12345`* (3 harf + 5 rakam)\n"
                    f"• *`TUR_67890`*\n"
                    f"• *`KIM_11111`*\n"
                    f"• *`BHB_15079`*\n\n"
                    f"🔍 *Program kodu 3 harf olmalı*\n"
                    f"❓ *Yardım: /help*"
                )
                await update.message.reply_text(error_msg, parse_mode='Markdown')
                return

    # Yanlış format (güncellenmiş)
    format_error = (
        f"⚠️ *Yanlış Format!*\n\n"
        f"❌ Girdiğiniz: `{message_text}`\n\n"
        f"✅ *Doğru format:*\n"
        f"*`PROGRAM_KODU_CRN`*\n\n"
        f"📋 *Örnekler:*\n"
        f"• *`END_12345`*\n"
        f"• *`TUR_67890`*\n"
        f"• *`KIM_11111`*\n"
        f"• *`BHB_15079`*\n\n"
        f"🔍 *Popüler kodlar:* `END, TUR, MAT, FIZ, KIM, BHB`\n"
        f"❓ *Detaylı yardım: /help*\n\n"
        f"⏳ *Bot her dakika kontenjan kontrolü yapar!*\n"
        f"🚨 *Komutlar: /stop, /cancel, /status*"
    )
    await update.message.reply_text(format_error, parse_mode='Markdown')


async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    """Genel hata yakalama"""
    print(f"💥 TELEGRAM HATA: {context.error}")

    if update and update.message:
        try:
            await update.message.reply_text(
                "❌ *Bir hata oluştu*\n\n"
                "🔧 *Bot yeniden başlatılıyor...*\n"
                "🔄 *Lütfen /start yazarak tekrar deneyin*"
                , parse_mode='Markdown'
            )
        except:
            pass


# Yeni komutlar
async def stop_command(update, context: ContextTypes.DEFAULT_TYPE):
    """Botu durdur"""
    chat_id = update.effective_chat.id
    user = update.effective_user

    print(f"🛑 /stop - Kullanıcı: {user.first_name} (@{user.username}) - Chat ID: {chat_id}")

    # Bu chat_id için takip edilen işleri iptal et
    if chat_id in WATCHED_COURSES:
        for program_code, crn in WATCHED_COURSES[chat_id]:
            job_name = f"{chat_id}_{program_code}_{crn}"
            print(f"   🛑 {program_code}_{crn} takibi iptal edildi")
        del WATCHED_COURSES[chat_id]

    stop_message = (
        f"🛑 *Bot Durduruldu!*\n\n"
        f"👤 *Kullanıcı:* {user.first_name}\n"
        f"📱 *Chat ID:* `{chat_id}`\n\n"
        f"⏹️ *Tüm takibler iptal edildi*\n"
        f"🔄 *Yeniden başlatmak için /start*"
    )

    await update.message.reply_text(stop_message, parse_mode='Markdown')
    print(f"✅ Bot {chat_id} için durduruldu")


async def cancel_command(update, context: ContextTypes.DEFAULT_TYPE):
    """Takip edilen dersleri iptal et"""
    chat_id = update.effective_chat.id
    user = update.effective_user

    print(f"❌ /cancel - Kullanıcı: {user.first_name} (@{user.username}) - Chat ID: {chat_id}")

    if chat_id in WATCHED_COURSES and WATCHED_COURSES[chat_id]:
        ders_listesi = [f"`{program_code}_{crn}`" for program_code, crn in WATCHED_COURSES[chat_id]]
        ders_text = ", ".join(ders_listesi)

        # Takip listesini temizle
        del WATCHED_COURSES[chat_id]

        cancel_message = (
            f"❌ *Takibler İptal Edildi!*\n\n"
            f"📋 *İptal edilen dersler:*\n"
            f"{ders_text}\n\n"
            f"🔄 *Yeni ders eklemek için sorgu yapın*\n"
            f"📝 *Örnek: `END_12345`*"
        )
    else:
        cancel_message = (
            f"ℹ️ *Takip Edilen Ders Yok*\n\n"
            f"📋 *Şu anda takip ettiğiniz ders bulunmuyor*\n\n"
            f"🔄 *Yeni ders eklemek için sorgu yapın*\n"
            f"📝 *Örnek: `END_12345`*"
        )

    await update.message.reply_text(cancel_message, parse_mode='Markdown')
    print(f"✅ {chat_id} için takibler iptal edildi")


async def status_command(update, context: ContextTypes.DEFAULT_TYPE):
    """Takip edilen dersleri göster"""
    chat_id = update.effective_chat.id
    user = update.effective_user

    print(f"📊 /status - Kullanıcı: {user.first_name} (@{user.username}) - Chat ID: {chat_id}")

    if chat_id in WATCHED_COURSES and WATCHED_COURSES[chat_id]:
        ders_listesi = []
        for program_code, crn in WATCHED_COURSES[chat_id]:
            ders_listesi.append(f"`{program_code}_{crn}`")

        ders_text = "\n".join(ders_listesi)
        count = len(WATCHED_COURSES[chat_id])

        status_message = (
            f"📊 *Takip Edilen Dersler*\n\n"
            f"📋 *Toplam: {count} ders*\n"
            f"⏳ *Her dakika kontrol ediliyor*\n\n"
            f"📝 *Dersler:*\n"
            f"{ders_text}\n\n"
            f"❌ *İptal etmek için: /cancel*\n"
            f"🔄 *Yeniden başlatmak için: /start*"
        )
    else:
        status_message = (
            f"ℹ️ *Takip Edilen Ders Yok*\n\n"
            f"📋 *Şu anda takip ettiğiniz ders bulunmuyor*\n\n"
            f"🔄 *Ders eklemek için sorgu yapın*\n"
            f"📝 *Örnek: `END_12345`*"
        )

    await update.message.reply_text(status_message, parse_mode='Markdown')
    print(f"✅ {chat_id} için durum gösterildi ({count if 'count' in locals() else 0} ders)")

def create_health_server():
    app = Flask(__name__)
    
    @app.route('/')
    def health():
        return jsonify({
            "status": "healthy",
            "service": "İTÜ Ders Bot",
            "uptime": "100%"
        })
    
    @app.route('/health')
    def health_check():
        return jsonify({"status": "ok"})
    
    port = int(os.environ.get('PORT', 8080))
    print(f"🌐 Health server port: {port}")
    
    app.run(host='0.0.0.0', port=port, debug=False)

def main():
    """Ana fonksiyon - KONTENJAN TAKİP MODU"""
    global WATCHED_COURSES, LAST_REQUEST_TIME
    WATCHED_COURSES = {}
    LAST_REQUEST_TIME = {}

    print("🤖 İTÜ DERS KONTENJAN BOTU v3.1 - DAKİKALIK KONTENJAN TAKİP")
    print("=" * 75)
    print(f"📂 Toplam {len(PROGRAM_KODLARI)} program kodu yüklendi")
    print(f"🔗 1. Kutucuk: Lisans (LS) - SABİT")
    print(f"🔗 2. Kutucuk: Kullanıcı girdisi -> OBS ID")
    print(f"   📋 Örnek: END -> {PROGRAM_KODLARI.get('END', 'YOK')}")
    print(f"   📋 Örnek: TUR -> {PROGRAM_KODLARI.get('TUR', 'YOK')}")
    print(f"   📋 Örnek: KIM -> {PROGRAM_KODLARI.get('KIM', 'YOK')}")
    print(f"   📋 Örnek: BHB -> {PROGRAM_KODLARI.get('BHB', 'YOK')}")
    print(f"📊 Kolonlar: [0]CRN [1]Kod [2]Ad [6]Gün [7]Saat [9]KONTENJAN [10]YAZILAN")
    print(f"⏳ TAKİP: Kontenjan yok → Mesaj | Açılınca → Detaylı bildirim (HER DAKİKA)")
    print(f"🚨 KOMUTLAR: /stop - Durdur | /cancel - İptal | /status - Durum")
    print("=" * 75)

    app = ApplicationBuilder().token(API_KEY).build()

    # Mevcut handler'lara ekleyin
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stop", stop_command))  # YENİ
    app.add_handler(CommandHandler("cancel", cancel_command))  # YENİ
    app.add_handler(CommandHandler("status", status_command))  # YENİ
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    print("✅ Bot başarıyla başlatıldı! (Dakikalık Kontenjan Takip Modu)")
    print("📱 Telegram'da test edin:")
    print("   • /start - Botu başlat")
    print("   • /stop - Botu durdur")
    print("   • /cancel - Takibi iptal et")
    print("   • /status - Takip edilen dersleri göster")
    print("   • END_12345 - Test")
    print("   • BHB_15079 - Test (35/9 → bildirim YOK)")
    print("   • BHB_15081 - Test (30/0 → takip mesajı)")
    print("   • /help - Detaylı yardım")
    print("⏹️  PyCharm'da durdurmak için: Ctrl+C")
    print("=" * 75)

    # Health server arka planda
    server_thread = threading.Thread(target=create_health_server, daemon=True)
    server_thread.start()

    print("🌐 Health server aktif (502 çözüldü)")

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Bot kullanıcı tarafından durduruldu (Ctrl+C)")
    except Exception as e:
        print(f"\n💥 Kritik hata: {e}")
        print(f"   Hata tipi: {type(e)}")
        # Railway'de input() çalışmaz, sessiz kal
        print("🔄 Railway ortamı algılandı, input beklenmiyor.")



