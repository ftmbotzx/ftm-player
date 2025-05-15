# ###############################################################
# #                                                             #
# #                  Spotify Downloader Bot                     #
# #                  Copyright © ftmdeveloperz                  #
# #                       #ftmdeveloperz                        #
# #                                                             #
# ###############################################################

import os
import logging
import re
import time
import json
import asyncio
import tempfile
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.ext import ContextTypes
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from yt_dlp import YoutubeDL
import pymongo

# Import proxy manager for YouTube request rotation
from proxy_manager import proxy_manager

# Set up advanced logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Create a custom handler for file logging
try:
    os.makedirs('logs', exist_ok=True)
    file_handler = logging.FileHandler('logs/bot.log')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logging.getLogger().addHandler(file_handler)
except Exception as e:
    print(f"Could not set up file logging: {e}")

logger = logging.getLogger(__name__)

# Small caps conversion dictionary
small_caps_map = {
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ꜰ',
    'g': 'ɢ', 'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ',
    'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ', 'q': 'Q', 'r': 'ʀ',
    's': 'ꜱ', 't': 'ᴛ', 'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x',
    'y': 'ʏ', 'z': 'ᴢ'
}

# Emoji dictionary
emoji_map = {
    "start": "🎵",
    "track": "🎧",
    "album": "💿",
    "playlist": "📋",
    "premium": "⭐",
    "wait": "⏳",
    "error": "❌",
    "success": "✅",
    "info": "ℹ️",
    "download": "⬇️",
    "file": "📁",
    "package": "📦",
    "speed": "🚀",
    "time": "⏱️",
    "cpu": "🏮",
    "search": "🔍",
    "play": "▶️",
    "stats": "📊",
    "user": "👤",
    "developer": "👨‍💻",
    "headphones": "🎧",
    "rate": "⭐",
    "feedback": "📝"
}

# Constants
FREE_DAILY_LIMIT = 10
FREE_BITRATE = 128
PREMIUM_BITRATE = 320
ADMINS = os.environ.get("ADMINS", "").split(",")
LOG_CHANNEL = os.environ.get("LOG_CHANNEL")
DB_CHANNEL = os.environ.get("DB_CHANNEL")

# Bot start time (for uptime calculation)
bot_start_time = datetime.now()

# Connect to MongoDB
client = pymongo.MongoClient(os.environ.get("MONGODB_URI"))
db = client.get_database("spotify_downloader")
users_collection = db.users
downloads_collection = db.downloads
songs_collection = db.songs

# Initialize Spotify API
spotify = spotipy.Spotify(
    client_credentials_manager=SpotifyClientCredentials(
        client_id=os.environ.get("SPOTIFY_CLIENT_ID"),
        client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET")
    )
)

# Helper functions
def to_small_caps(text):
    """Convert text to small caps"""
    result = ""
    for char in text.lower():
        result += small_caps_map.get(char, char)
    return result

def get_emoji(key):
    """Get emoji by key"""
    return emoji_map.get(key, "")

async def delete_message_after_delay(context, chat_id, message_id, delay=60):
    """
    Delete a message after a specified delay
    
    Args:
        context: Bot context for sending messages
        chat_id: Chat ID where the message is
        message_id: Message ID to delete
        delay: Delay in seconds before deletion (default: 60 seconds)
    """
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Auto-deleted message {message_id} in chat {chat_id} after {delay} seconds")
    except Exception as e:
        logger.error(f"Failed to auto-delete message: {e}")

async def forward_to_db_channel(context, message):
    """
    Forward a message to the DB channel for archiving
    
    Args:
        context: Bot context
        message: Message to forward
    """
    if DB_CHANNEL:
        try:
            await context.bot.forward_message(
                chat_id=DB_CHANNEL,
                from_chat_id=message.chat_id,
                message_id=message.message_id
            )
        except Exception as e:
            logger.error(f"Error forwarding message to DB channel: {e}")

async def log_activity(context, activity_type, user_info, details, level="INFO"):
    """
    Log activity to file and log channel
    
    Args:
        context: Bot context for sending messages
        activity_type: Type of activity (e.g., 'download', 'premium', 'error')
        user_info: User information (id, username, first_name)
        details: Additional details about the activity
        level: Logging level (INFO, WARNING, ERROR)
    """
    # Create log entry
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "type": activity_type,
        "user": user_info,
        "details": details
    }
    
    # Log to appropriate level
    if level == "ERROR":
        logger.error(f"{activity_type}: {json.dumps(user_info)} - {json.dumps(details)}")
    elif level == "WARNING":
        logger.warning(f"{activity_type}: {json.dumps(user_info)} - {json.dumps(details)}")
    else:
        logger.info(f"{activity_type}: {json.dumps(user_info)} - {json.dumps(details)}")
    
    # Add to MongoDB log collection
    try:
        db.logs.insert_one(log_entry)
    except Exception as e:
        logger.error(f"Failed to write to log collection: {e}")
    
    # Send to log channel if available
    if LOG_CHANNEL and context:
        try:
            # Format message for Telegram
            if activity_type == "download":
                emoji = get_emoji("download")
            elif activity_type == "premium":
                emoji = get_emoji("premium")
            elif activity_type == "error":
                emoji = get_emoji("error")
            else:
                emoji = get_emoji("info")
            
            # Format user info
            user_id = user_info.get("id", "unknown")
            username = user_info.get("username", "")
            first_name = user_info.get("first_name", "")
            user_display = f"{first_name} (@{username})" if username else first_name
            
            # Create a readable message
            log_message = f"{emoji} {activity_type.upper()}\n"
            log_message += f"👤 User: {user_display} (ID: {user_id})\n"
            
            # Format details based on type
            if activity_type == "download":
                track_name = details.get("track_name", "Unknown")
                artist = details.get("artist", "Unknown")
                quality = details.get("quality", "Unknown")
                log_message += f"🎵 Track: {track_name}\n"
                log_message += f"👨‍🎤 Artist: {artist}\n"
                log_message += f"🎚️ Quality: {quality}kbps\n"
                log_message += f"⏱️ Time: {datetime.now().strftime('%H:%M:%S')}"
            elif activity_type == "error":
                log_message += f"❌ Error: {details.get('message', 'Unknown error')}\n"
                log_message += f"📌 Context: {details.get('context', 'No context')}\n"
                log_message += f"⏱️ Time: {datetime.now().strftime('%H:%M:%S')}"
            else:
                # Generic details
                for key, value in details.items():
                    log_message += f"• {key}: {value}\n"
                log_message += f"⏱️ Time: {datetime.now().strftime('%H:%M:%S')}"
            
            await context.bot.send_message(chat_id=LOG_CHANNEL, text=log_message)
        except Exception as e:
            logger.error(f"Failed to send to log channel: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    
    # Create user in database if not exists
    is_new_user = False
    if not users_collection.find_one({"user_id": user.id}):
        is_new_user = True
        users_collection.insert_one({
            "user_id": user.id,
            "username": user.username or "",
            "first_name": user.first_name,
            "joined_at": datetime.now(),
            "is_premium": False,
            "downloads_today": 0,
            "total_downloads": 0,
            "last_download_date": datetime.now(),
            "last_activity": datetime.now(),
        })
        
        # Log new user registration
        user_info = {
            "id": user.id,
            "username": user.username or "",
            "first_name": user.first_name,
            "is_bot": user.is_bot
        }
        details = {
            "action": "new_registration",
            "source": "start_command",
            "platform": "telegram"
        }
        await log_activity(context, "registration", user_info, details)
    else:
        # Update last activity time
        users_collection.update_one(
            {"user_id": user.id},
            {"$set": {"last_activity": datetime.now()}}
        )
    
    welcome_msg = f"{get_emoji('start')} {to_small_caps('ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ꜱᴘᴏᴛɪꜰʏ ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ʙᴏᴛ!')}\n\n"
    welcome_msg += f"{get_emoji('info')} {to_small_caps('ᴀʙᴏᴜᴛ ᴛʜɪꜱ ʙᴏᴛ:')}\n"
    welcome_msg += f"• {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅ ᴀɴʏ ꜱᴘᴏᴛɪꜰʏ ᴛʀᴀᴄᴋ, ᴀʟʙᴜᴍ ᴏʀ ᴘʟᴀʏʟɪꜱᴛ')}\n"
    welcome_msg += f"• {to_small_caps('ʜɪɢʜ ǫᴜᴀʟɪᴛʏ ᴍᴘ3 ᴄᴏɴᴠᴇʀꜱɪᴏɴ')}\n"
    welcome_msg += f"• {to_small_caps('ꜱᴇᴀʀᴄʜ ꜰᴏʀ ᴍᴜꜱɪᴄ ᴜꜱɪɴɢ /ꜰᴛᴍᴅʟ ᴄᴏᴍᴍᴀɴᴅ')}\n\n"
    welcome_msg += f"{get_emoji('headphones')} {to_small_caps('ʜᴏᴡ ᴛᴏ ᴜꜱᴇ:')}\n"
    welcome_msg += f"1. {to_small_caps('ꜱᴇɴᴅ ᴀɴʏ ꜱᴘᴏᴛɪꜰʏ ʟɪɴᴋ')}\n"
    welcome_msg += f"2. {to_small_caps('ᴏʀ ᴜꜱᴇ /ꜰᴛᴍᴅʟ ꜱᴏɴɢ ɴᴀᴍᴇ ᴛᴏ ꜱᴇᴀʀᴄʜ')}\n"
    welcome_msg += f"3. {to_small_caps('ꜱᴇʟᴇᴄᴛ ᴀɴᴅ ᴅᴏᴡɴʟᴏᴀᴅ ʏᴏᴜʀ ᴍᴜꜱɪᴄ')}"
    
    # Create inline keyboard with more options
    keyboard = [
        [
            InlineKeyboardButton(f"{get_emoji('info')} Help", callback_data="help"),
            InlineKeyboardButton(f"{get_emoji('premium')} Premium", callback_data="premium_info")
        ],
        [
            InlineKeyboardButton(f"{get_emoji('stats')} My Status", callback_data="my_status"),
            InlineKeyboardButton(f"{get_emoji('developer')} About Dev", callback_data="about_dev")
        ],
        [
            InlineKeyboardButton(f"{get_emoji('search')} Search Music", callback_data="search_music")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Log start command
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    details = {
        "action": "start_command",
        "is_new_user": is_new_user
    }
    await log_activity(context, "command", user_info, details)
    
    await update.message.reply_text(welcome_msg, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    help_text = f"{get_emoji('info')} {to_small_caps('ʜᴏᴡ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ʙᴏᴛ:')}\n\n"
    help_text += f"1️⃣ {to_small_caps('ꜱᴇɴᴅ ᴀɴʏ ꜱᴘᴏᴛɪꜰʏ ʟɪɴᴋ (ᴛʀᴀᴄᴋ, ᴀʟʙᴜᴍ ᴏʀ ᴘʟᴀʏʟɪꜱᴛ)')}\n\n"
    help_text += f"2️⃣ {to_small_caps('ᴛʜᴇ ʙᴏᴛ ᴡɪʟʟ ꜰᴇᴛᴄʜ ᴛʜᴇ ᴅᴇᴛᴀɪʟꜱ ᴀɴᴅ ꜱʜᴏᴡ ʏᴏᴜ ᴏᴘᴛɪᴏɴꜱ')}\n\n"
    help_text += f"3️⃣ {to_small_caps('ᴄʟɪᴄᴋ ᴏɴ ᴛʜᴇ ᴅᴏᴡɴʟᴏᴀᴅ ʙᴜᴛᴛᴏɴ ᴛᴏ ɢᴇᴛ ʏᴏᴜʀ ᴍᴘ3')}\n\n"
    help_text += f"📋 {to_small_caps('ᴀᴠᴀɪʟᴀʙʟᴇ ᴄᴏᴍᴍᴀɴᴅꜱ:')}\n"
    help_text += f"/start - {to_small_caps('ꜱᴛᴀʀᴛ ᴛʜᴇ ʙᴏᴛ')}\n"
    help_text += f"/help - {to_small_caps('ꜱʜᴏᴡ ᴛʜɪꜱ ʜᴇʟᴘ ᴍᴇꜱꜱᴀɢᴇ')}\n"
    help_text += f"/status - {to_small_caps('ᴄʜᴇᴄᴋ ʏᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ ꜱᴛᴀᴛᴜꜱ')}\n"
    help_text += f"/developer - {to_small_caps('ꜱʜᴏᴡ ᴅᴇᴠᴇʟᴏᴘᴇʀ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ')}\n"
    
    # Create inline keyboard with premium info button and back button
    keyboard = [
        [InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ᴘʀᴇᴍɪᴜᴍ ꜰᴇᴀᴛᴜʀᴇꜱ')}", callback_data="premium_info")],
        [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(help_text, reply_markup=reply_markup)
    
    # Log help command usage
    user = update.effective_user
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    details = {
        "action": "help_command_used",
        "source": "direct_command"
    }
    await log_activity(context, "help", user_info, details)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user status"""
    user_id = update.effective_user.id
    user_data = users_collection.find_one({"user_id": user_id})
    
    if not user_data:
        await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ᴜꜱᴇʀ ɴᴏᴛ ꜰᴏᴜɴᴅ.')}")
        return
    
    # Check if download count should be reset (new day)
    last_download_date = user_data.get("last_download_date")
    if last_download_date and isinstance(last_download_date, datetime):
        today = datetime.now().date()
        last_date = last_download_date.date()
        
        if today > last_date:
            # Reset download count for a new day
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"downloads_today": 0, "last_download_date": datetime.now()}}
            )
            logger.info(f"Reset download count for user {user_id} (new day)")
            # Refresh user data
            user_data = users_collection.find_one({"user_id": user_id})
    
    status_text = f"{get_emoji('info')} {to_small_caps('ʏᴏᴜʀ ꜱᴛᴀᴛᴜꜱ:')}\n\n"
    
    if user_data.get("is_premium"):
        # Check if premium has expired
        premium_expires = user_data.get("premium_expires")
        if premium_expires and isinstance(premium_expires, datetime):
            if datetime.now() > premium_expires:
                # Premium expired, update user to free with enhanced logging
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_premium": False}}
                )
                
                # Detailed premium expiration logging
                expiry_log = {
                    "action": "premium_subscription_expired",
                    "user_id": user_id,
                    "expired_at": premium_expires.strftime("%Y-%m-%d %H:%M:%S"),
                    "detection_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                logger.info(f"Premium subscription expired: {json.dumps(expiry_log)}")
                
                # Log activity in database
                premium_expiry_activity = {
                    "type": "premium_expired",
                    "user_id": user_id,
                    "expired_at": premium_expires,
                    "detection_time": datetime.now()
                }
                db.premium_logs.insert_one(premium_expiry_activity)
                
                # Send premium expiration notification to log channel if configured
                if LOG_CHANNEL:
                    try:
                        log_text = f"⏱️ {to_small_caps('ᴘʀᴇᴍɪᴜᴍ ꜱᴜʙꜱᴄʀɪᴘᴛɪᴏɴ ᴇxᴘɪʀᴇᴅ')}\n\n"
                        log_text += f"{to_small_caps('ᴜꜱᴇʀ ɪᴅ:')} {user_id}\n"
                        log_text += f"{to_small_caps('ᴇxᴘɪʀᴇᴅ ᴏɴ:')} {premium_expires.strftime('%Y-%m-%d')}"
                        
                        # Send notification asynchronously
                        asyncio.create_task(context.bot.send_message(
                            chat_id=LOG_CHANNEL,
                            text=log_text
                        ))
                    except Exception as e:
                        logger.error(f"Failed to send premium expiration notification to log channel: {e}")
                
                # Show free status
                downloads_today = user_data.get("downloads_today", 0)
                status_text += f"{to_small_caps('ꜰʀᴇᴇ ᴜꜱᴇʀ')} ({get_emoji('error')} {to_small_caps('ᴘʀᴇᴍɪᴜᴍ ᴇxᴘɪʀᴇᴅ')})\n"
                status_text += f"{to_small_caps(f'ᴅᴏᴡɴʟᴏᴀᴅꜱ ᴛᴏᴅᴀʏ: {downloads_today}/{FREE_DAILY_LIMIT}')}\n"
                status_text += f"{to_small_caps(f'ǫᴜᴀʟɪᴛʏ: {FREE_BITRATE}ᴋʙᴘꜱ')}"
                
                # Add premium button
                keyboard = [[InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ')}",
                                         callback_data="premium_info")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(status_text, reply_markup=reply_markup)
                return
            
            # Premium is active, show expiry date
            days_left = (premium_expires - datetime.now()).days
            expires_text = f" ({to_small_caps(f'ᴇxᴘɪʀᴇꜱ ɪɴ {days_left} ᴅᴀʏꜱ')})"
        else:
            expires_text = ""
            
        status_text += f"{get_emoji('premium')} {to_small_caps('ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀ')}{expires_text}\n"
        status_text += f"{get_emoji('success')} {to_small_caps('ᴜɴʟɪᴍɪᴛᴇᴅ ᴅᴏᴡɴʟᴏᴀᴅꜱ')}\n"
        status_text += f"{get_emoji('success')} {to_small_caps(f'ʜɪɢʜ ǫᴜᴀʟɪᴛʏ ({PREMIUM_BITRATE}ᴋʙᴘꜱ)')}"

        # Show total downloads
        total_downloads = user_data.get("total_downloads", 0)
        if total_downloads > 0:
            status_text += f"\n{get_emoji('download')} {to_small_caps(f'ᴛᴏᴛᴀʟ ᴅᴏᴡɴʟᴏᴀᴅꜱ: {total_downloads}')}"
    else:
        downloads_today = user_data.get("downloads_today", 0)
        status_text += f"{to_small_caps('ꜰʀᴇᴇ ᴜꜱᴇʀ')}\n"
        status_text += f"{to_small_caps(f'ᴅᴏᴡɴʟᴏᴀᴅꜱ ᴛᴏᴅᴀʏ: {downloads_today}/{FREE_DAILY_LIMIT}')}\n"
        status_text += f"{to_small_caps(f'ǫᴜᴀʟɪᴛʏ: {FREE_BITRATE}ᴋʙᴘꜱ')}"
        
        # Show total downloads
        total_downloads = user_data.get("total_downloads", 0)
        if total_downloads > 0:
            status_text += f"\n{get_emoji('download')} {to_small_caps(f'ᴛᴏᴛᴀʟ ᴅᴏᴡɴʟᴏᴀᴅꜱ: {total_downloads}')}"
        
        # Add premium button
        keyboard = [[InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ')}",
                                 callback_data="premium_info")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(status_text, reply_markup=reply_markup)
        return
    
    await update.message.reply_text(status_text)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bot statistics (admin only)"""
    user_id = update.effective_user.id
    
    # Check if user is admin
    if str(user_id) not in ADMINS:
        await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ.')}")
        return
    
    # Gather statistics
    total_users = users_collection.count_documents({})
    premium_users = users_collection.count_documents({"is_premium": True})
    active_users = users_collection.count_documents({"last_activity": {"$gt": datetime.now() - timedelta(days=7)}})
    total_downloads = downloads_collection.count_documents({})
    total_songs = songs_collection.count_documents({})
    
    stats_text = f"{get_emoji('info')} {to_small_caps('ʙᴏᴛ ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ:')}\n\n"
    stats_text += f"👤 {to_small_caps(f'ᴜꜱᴇʀꜱ: {total_users}')}\n"
    stats_text += f"{get_emoji('premium')} {to_small_caps(f'ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ: {premium_users}')}\n"
    stats_text += f"📊 {to_small_caps(f'ᴀᴄᴛɪᴠᴇ ᴜꜱᴇʀꜱ: {active_users}')}\n"
    stats_text += f"📥 {to_small_caps(f'ᴛᴏᴛᴀʟ ᴅᴏᴡɴʟᴏᴀᴅꜱ: {total_downloads}')}\n"
    stats_text += f"🎵 {to_small_caps(f'ᴄᴀᴄʜᴇᴅ ꜱᴏɴɢꜱ: {total_songs}')}\n"
    
    await update.message.reply_text(stats_text)


async def developer_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show developer information"""
    dev_text = f"👨‍💻 {to_small_caps('ᴅᴇᴠᴇʟᴏᴘᴇʀ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ')}\n\n"
    dev_text += f"{to_small_caps('ᴛʜɪꜱ ʙᴏᴛ ᴡᴀꜱ ᴅᴇᴠᴇʟᴏᴘᴇᴅ ʙʏ:')} @SpotifyDLBot_Admin\n\n"
    dev_text += f"{to_small_caps('ᴠᴇʀꜱɪᴏɴ:')} 2.0.0\n"
    dev_text += f"{to_small_caps('ʟᴀꜱᴛ ᴜᴘᴅᴀᴛᴇ:')} {datetime.now().strftime('%Y-%m-%d')}\n\n"
    dev_text += f"{to_small_caps('ᴛᴇᴄʜɴᴏʟᴏɢɪᴇꜱ ᴜꜱᴇᴅ:')}\n"
    dev_text += f"• Python-Telegram-Bot\n• Spotipy\n• yt-dlp\n• MongoDB\n• FFmpeg\n\n"
    dev_text += f"{to_small_caps('ꜰᴏʀ ꜱᴜᴘᴘᴏʀᴛ ᴏʀ ꜰᴇᴇᴅʙᴀᴄᴋ, ᴄᴏɴᴛᴀᴄᴛ:')} @SpotifyDLBot_Admin"
    
    # Create support and feedback buttons
    keyboard = [
        [InlineKeyboardButton("📨 Contact Developer", url="https://t.me/SpotifyDLBot_Admin")],
        [InlineKeyboardButton("⭐ Rate Bot", callback_data="rate_bot")],
        [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(dev_text, reply_markup=reply_markup)
    
    # Log developer command usage
    user = update.effective_user
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    details = {
        "action": "developer_info_viewed"
    }
    await log_activity(context, "command", user_info, details)

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check bot's response time"""
    start_time = time.time()
    
    # Send initial message
    message = await update.message.reply_text(f"{get_emoji('time')} {to_small_caps('ᴘɪɴɢɪɴɢ...')}")
    
    # Calculate response time
    end_time = time.time()
    ping_time = round((end_time - start_time) * 1000, 2)
    
    # Edit message with ping result
    response_text = f"{get_emoji('success')} {to_small_caps('ᴘᴏɴɢ!')}\n\n"
    response_text += f"{to_small_caps(f'ʀᴇꜱᴘᴏɴꜱᴇ ᴛɪᴍᴇ: {ping_time} ᴍꜱ')}"
    
    await message.edit_text(response_text)
    
    # Log ping command
    user = update.effective_user
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    details = {
        "action": "ping_command",
        "response_time_ms": ping_time
    }
    await log_activity(context, "command", user_info, details)

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show information about the bot"""
    # Get bot uptime
    current_time = datetime.now()
    uptime_seconds = (current_time - bot_start_time).total_seconds()
    
    # Format uptime
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if days > 0:
        uptime_text = f"{int(days)}d {int(hours)}h {int(minutes)}m"
    elif hours > 0:
        uptime_text = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
    else:
        uptime_text = f"{int(minutes)}m {int(seconds)}s"
    
    # Count stats
    total_users = users_collection.count_documents({})
    total_downloads = downloads_collection.count_documents({})
    total_tracks = songs_collection.count_documents({})
    
    about_text = f"{get_emoji('info')} {to_small_caps('ʙᴏᴛ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ')}\n\n"
    about_text += f"{to_small_caps('ɴᴀᴍᴇ:')} Spotify Downloader Bot\n"
    about_text += f"{to_small_caps('ᴠᴇʀꜱɪᴏɴ:')} 2.0.0\n"
    about_text += f"{to_small_caps('ᴜᴘᴛɪᴍᴇ:')} {uptime_text}\n\n"
    
    about_text += f"{get_emoji('stats')} {to_small_caps('ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ:')}\n"
    about_text += f"• {to_small_caps(f'ᴜꜱᴇʀꜱ: {total_users}')}\n"
    about_text += f"• {to_small_caps(f'ᴅᴏᴡɴʟᴏᴀᴅꜱ: {total_downloads}')}\n"
    about_text += f"• {to_small_caps(f'ᴛʀᴀᴄᴋꜱ: {total_tracks}')}\n\n"
    
    about_text += f"{get_emoji('developer')} {to_small_caps('ᴅᴇᴠᴇʟᴏᴘᴇᴅ ʙʏ:')} @SpotifyDLBot_Admin"
    
    # Create keyboard with buttons
    keyboard = [
        [
            InlineKeyboardButton(f"{get_emoji('developer')} Developer Info", callback_data="about_dev"),
            InlineKeyboardButton(f"{get_emoji('premium')} Premium", callback_data="premium_info")
        ],
        [
            InlineKeyboardButton(f"{get_emoji('rate')} Rate Bot", callback_data="rate_bot")
        ],
        [
            InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", callback_data="back_to_start")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(about_text, reply_markup=reply_markup)
    
    # Log about command usage
    user = update.effective_user
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    details = {
        "action": "about_command_used"
    }
    await log_activity(context, "command", user_info, details)

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's Telegram ID"""
    user = update.effective_user
    chat = update.effective_chat
    
    response_text = f"{get_emoji('user')} {to_small_caps('ʏᴏᴜʀ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ:')}\n\n"
    response_text += f"{to_small_caps('ᴜꜱᴇʀ ɪᴅ:')} {user.id}\n"
    if user.username:
        response_text += f"{to_small_caps('ᴜꜱᴇʀɴᴀᴍᴇ:')} @{user.username}\n"
    response_text += f"{to_small_caps('ɴᴀᴍᴇ:')} {user.first_name}"
    
    if chat.type != "private":
        response_text += f"\n\n{to_small_caps('ᴄʜᴀᴛ ɪᴅ:')} {chat.id}\n"
        response_text += f"{to_small_caps('ᴄʜᴀᴛ ᴛʏᴘᴇ:')} {chat.type}"
    
    # Removed Markdown parsing to avoid issues
    await update.message.reply_text(response_text)
    
    # Log ID command usage
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    details = {
        "action": "id_command_used",
        "chat_type": chat.type
    }
    await log_activity(context, "command", user_info, details)

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show subscription information"""
    user = update.effective_user
    
    premium_text = f"{get_emoji('premium')} {to_small_caps('ᴘʀᴇᴍɪᴜᴍ ꜱᴜʙꜱᴄʀɪᴘᴛɪᴏɴ')}\n\n"
    premium_text += f"{to_small_caps('ᴇɴᴊᴏʏ ᴛʜᴇꜱᴇ ʙᴇɴᴇꜰɪᴛꜱ ᴡɪᴛʜ ᴘʀᴇᴍɪᴜᴍ:')}\n\n"
    premium_text += f"✅ {to_small_caps('ᴜɴʟɪᴍɪᴛᴇᴅ ᴅᴏᴡɴʟᴏᴀᴅꜱ')}\n"
    premium_text += f"✅ {to_small_caps(f'ʜɪɢʜᴇʀ ǫᴜᴀʟɪᴛʏ ({PREMIUM_BITRATE}ᴋʙᴘꜱ)')}\n"
    premium_text += f"✅ {to_small_caps('ᴘʀɪᴏʀɪᴛʏ ꜱᴜᴘᴘᴏʀᴛ')}\n"
    premium_text += f"✅ {to_small_caps('ꜰᴀꜱᴛᴇʀ ᴅᴏᴡɴʟᴏᴀᴅꜱ')}\n\n"
    
    premium_text += f"{to_small_caps('ᴘʀᴇᴍɪᴜᴍ ᴘʟᴀɴꜱ:')}\n"
    premium_text += f"• {to_small_caps('1 ᴍᴏɴᴛʜ: $5')}\n"
    premium_text += f"• {to_small_caps('3 ᴍᴏɴᴛʜꜱ: $12')}\n"
    premium_text += f"• {to_small_caps('1 ʏᴇᴀʀ: $40')}\n\n"
    
    premium_text += f"{to_small_caps('ᴛᴏ ᴘᴜʀᴄʜᴀꜱᴇ, ᴄᴏɴᴛᴀᴄᴛ ᴏᴜʀ ꜱᴜᴘᴘᴏʀᴛ:')}"
    
    # Create keyboard with contact button and back button
    keyboard = [
        [InlineKeyboardButton("📨 Contact Support", url="https://t.me/SpotifyDLBot_Admin")],
        [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(premium_text, reply_markup=reply_markup)
    
    # Log subscribe command usage
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    details = {
        "action": "subscribe_command_used"
    }
    await log_activity(context, "command", user_info, details)

async def check_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check user's premium status"""
    user_id = update.effective_user.id
    user = update.effective_user
    
    # Get user data from database
    user_data = users_collection.find_one({"user_id": user_id})
    
    if not user_data:
        await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ᴜꜱᴇʀ ɴᴏᴛ ꜰᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀꜱᴇ.')}")
        return
    
    response_text = f"{get_emoji('premium')} {to_small_caps('ᴘʀᴇᴍɪᴜᴍ ꜱᴛᴀᴛᴜꜱ:')}\n\n"
    
    is_premium = user_data.get("is_premium", False)
    if is_premium:
        # Check expiry date
        premium_expires = user_data.get("premium_expires")
        if premium_expires and isinstance(premium_expires, datetime):
            if datetime.now() > premium_expires:
                # Premium expired, update user to free
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_premium": False}}
                )
                
                # Show expired message
                expired_date = premium_expires.strftime("%Y-%m-%d")
                response_text += f"{get_emoji('error')} {to_small_caps('ʏᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ʜᴀꜱ ᴇxᴘɪʀᴇᴅ!')}\n\n"
                response_text += f"{to_small_caps('ᴇxᴘɪʀᴇᴅ ᴏɴ:')} {expired_date}\n\n"
                response_text += f"{to_small_caps('ᴛᴏ ʀᴇɴᴇᴡ ʏᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ, ᴜꜱᴇ /subscribe')}"
            else:
                # Premium still active
                days_left = (premium_expires - datetime.now()).days
                response_text += f"{get_emoji('success')} {to_small_caps('ʏᴏᴜ ᴀʀᴇ ᴀ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀ!')}\n\n"
                expires_date = premium_expires.strftime("%Y-%m-%d")
                days_remaining_text = to_small_caps(f'ᴅᴀʏꜱ ʀᴇᴍᴀɪɴɪɴɢ: {days_left}')
                expires_on_text = to_small_caps(f'ᴇxᴘɪʀᴇꜱ ᴏɴ: {expires_date}')
                response_text += f"{days_remaining_text}\n"
                response_text += f"{expires_on_text}\n\n"
                response_text += f"{get_emoji('success')} {to_small_caps('ᴇɴᴊᴏʏ ʜɪɢʜ ǫᴜᴀʟɪᴛʏ ᴍᴜꜱɪᴄ!')}"
        else:
            response_text += f"{get_emoji('success')} {to_small_caps('ʏᴏᴜ ᴀʀᴇ ᴀ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀ!')}\n\n"
            response_text += f"{to_small_caps('ɴᴏ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ ꜱᴇᴛ')}\n\n"
            response_text += f"{get_emoji('success')} {to_small_caps('ᴇɴᴊᴏʏ ʜɪɢʜ ǫᴜᴀʟɪᴛʏ ᴍᴜꜱɪᴄ!')}"
    else:
        response_text += f"{get_emoji('error')} {to_small_caps('ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀ')}\n\n"
        downloads_today = user_data.get("downloads_today", 0)
        response_text += f"{to_small_caps('ʏᴏᴜʀ ᴄᴜʀʀᴇɴᴛ ʟɪᴍɪᴛꜱ:')}\n"
        response_text += f"• {to_small_caps(f'ᴅᴏᴡɴʟᴏᴀᴅꜱ: {downloads_today}/{FREE_DAILY_LIMIT} ᴘᴇʀ ᴅᴀʏ')}\n"
        response_text += f"• {to_small_caps(f'ǫᴜᴀʟɪᴛʏ: {FREE_BITRATE}ᴋʙᴘꜱ')}\n\n"
        response_text += f"{to_small_caps('ᴛᴏ ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ, ᴜꜱᴇ')} /subscribe"
    
    await update.message.reply_text(response_text)
    
    # Log check premium command usage
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    details = {
        "action": "check_premium_command_used",
        "is_premium": is_premium
    }
    await log_activity(context, "command", user_info, details)

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all users (Admin only)"""
    user_id = update.effective_user.id
    user = update.effective_user
    
    # Check if user is admin
    if str(user_id) not in ADMINS:
        await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ.')}")
        return
    
    # Get parameters
    args = context.args
    limit = 10  # Default limit
    skip = 0    # Default skip
    
    if args:
        try:
            if len(args) >= 1:
                limit = int(args[0])
            if len(args) >= 2:
                skip = int(args[1])
        except ValueError:
            await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ɪɴᴠᴀʟɪᴅ ᴘᴀʀᴀᴍᴇᴛᴇʀꜱ. ᴜꜱᴇ: /users [limit] [skip]')}")
            return
    
    # Get total user count
    total_users = users_collection.count_documents({})
    
    # Fetch users with pagination
    users = list(users_collection.find({}).sort("joined_at", -1).skip(skip).limit(limit))
    
    if not users:
        await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ɴᴏ ᴜꜱᴇʀꜱ ꜰᴏᴜɴᴅ.')}")
        return
    
    response_text = f"👥 {to_small_caps('ᴜꜱᴇʀ ʟɪꜱᴛ')} ({len(users)}/{total_users})\n\n"
    
    for idx, user_data in enumerate(users, start=1):
        username = user_data.get("username", "")
        username_display = f"@{username}" if username else "No username"
        is_premium = "⭐️ Premium" if user_data.get("is_premium", False) else "Free"
        joined_date = user_data.get("joined_at", datetime.now()).strftime("%Y-%m-%d")
        total_downloads = user_data.get("total_downloads", 0)
        user_id = user_data.get('user_id')
        
        # Avoid Markdown formatting issues by not using backticks
        response_text += f"{idx}. ID: {user_id} - {username_display}\n"
        response_text += f"   {is_premium} | Joined: {joined_date} | DL: {total_downloads}\n\n"
    
    # Add pagination info
    response_text += f"{to_small_caps('ᴘᴀɢᴇ:')} {skip//limit + 1}/{(total_users-1)//limit + 1}\n"
    response_text += f"{to_small_caps('ᴜꜱᴇ:')} /users {limit} {skip+limit} {to_small_caps('ꜰᴏʀ ɴᴇxᴛ ᴘᴀɢᴇ')}"
    
    # Don't use Markdown parsing to avoid issues
    await update.message.reply_text(response_text)
    
    # Log users command usage
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    details = {
        "action": "users_command_used",
        "limit": limit,
        "skip": skip
    }
    await log_activity(context, "command", user_info, details)

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin statistics (Admin only)"""
    user_id = update.effective_user.id
    user = update.effective_user
    
    # Check if user is admin
    if str(user_id) not in ADMINS:
        error_msg = await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ.')}")
        # Auto-delete error message after 1 minute
        asyncio.create_task(delete_message_after_delay(context, error_msg.chat_id, error_msg.message_id))
        return
    
    # Gather statistics
    total_users = users_collection.count_documents({})
    premium_users = users_collection.count_documents({"is_premium": True})
    
    # Get active users in the last 24 hours
    active_24h = users_collection.count_documents({"last_activity": {"$gt": datetime.now() - timedelta(days=1)}})
    
    # Get active users in the last 7 days
    active_7d = users_collection.count_documents({"last_activity": {"$gt": datetime.now() - timedelta(days=7)}})
    
    # Get total downloads today
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    downloads_today = downloads_collection.count_documents({"download_time": {"$gt": today_start}})
    
    # Get total downloads
    total_downloads = downloads_collection.count_documents({})
    
    # Get database size
    total_songs = songs_collection.count_documents({})
    cached_size_mb = round(total_songs * 5, 2)  # Estimate 5MB per song
    
    # Get users joined today
    users_today = users_collection.count_documents({"joined_at": {"$gt": today_start}})
    
    # Get uptime
    current_time = datetime.now()
    uptime_seconds = (current_time - bot_start_time).total_seconds()
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_text = f"{int(days)}d {int(hours)}h {int(minutes)}m {int(seconds)}s"
    
    admin_text = f"👑 {to_small_caps('ᴀᴅᴍɪɴ ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ')}\n\n"
    
    # Bot information
    admin_text += f"{get_emoji('info')} {to_small_caps('ʙᴏᴛ ɪɴꜰᴏ:')}\n"
    admin_text += f"• {to_small_caps(f'ᴜᴘᴛɪᴍᴇ: {uptime_text}')}\n"
    admin_text += f"• {to_small_caps(f'ᴄᴀᴄʜᴇᴅ ᴛʀᴀᴄᴋꜱ: {total_songs}')}\n"
    admin_text += f"• {to_small_caps(f'ᴇꜱᴛɪᴍᴀᴛᴇᴅ ᴄᴀᴄʜᴇ ꜱɪᴢᴇ: {cached_size_mb}ᴍʙ')}\n\n"
    
    # User statistics
    admin_text += f"👥 {to_small_caps('ᴜꜱᴇʀ ꜱᴛᴀᴛꜱ:')}\n"
    admin_text += f"• {to_small_caps(f'ᴛᴏᴛᴀʟ ᴜꜱᴇʀꜱ: {total_users}')}\n"
    admin_text += f"• {to_small_caps(f'ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ: {premium_users}')}\n"
    admin_text += f"• {to_small_caps(f'ɴᴇᴡ ᴜꜱᴇʀꜱ ᴛᴏᴅᴀʏ: {users_today}')}\n"
    admin_text += f"• {to_small_caps(f'ᴀᴄᴛɪᴠᴇ (24ʜ): {active_24h}')}\n"
    admin_text += f"• {to_small_caps(f'ᴀᴄᴛɪᴠᴇ (7ᴅ): {active_7d}')}\n\n"
    
    # Download statistics
    admin_text += f"📥 {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅ ꜱᴛᴀᴛꜱ:')}\n"
    admin_text += f"• {to_small_caps(f'ᴛᴏᴛᴀʟ ᴅᴏᴡɴʟᴏᴀᴅꜱ: {total_downloads}')}\n"
    admin_text += f"• {to_small_caps(f'ᴅᴏᴡɴʟᴏᴀᴅꜱ ᴛᴏᴅᴀʏ: {downloads_today}')}\n"
    
    # Create keyboard with admin actions
    keyboard = [
        [
            InlineKeyboardButton("📊 Refresh Stats", callback_data="refresh_stats"),
            InlineKeyboardButton("👥 List Users", callback_data="list_users")
        ],
        [
            InlineKeyboardButton("🗑 Clean Cache", callback_data="clean_cache"),
            InlineKeyboardButton("📢 Broadcast", callback_data="broadcast")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(admin_text, reply_markup=reply_markup)
    
    # Log admin command usage
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    details = {
        "action": "admin_command_used"
    }
    await log_activity(context, "command", user_info, details)

async def set_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set user to premium (Admin only)"""
    user_id = update.effective_user.id
    
    # Check if user is admin
    if str(user_id) not in ADMINS:
        error_msg = await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ.')}")
        # Auto-delete error message after 1 minute
        asyncio.create_task(delete_message_after_delay(context, error_msg.chat_id, error_msg.message_id))
        return
    
    # Check arguments
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ᴜꜱᴀɢᴇ: /setpremium <user_id> <days>')}")
        return
    
    try:
        # Parse arguments
        target_user_id = int(args[0])
        days = int(args[1])
        
        if days <= 0:
            await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ᴅᴀʏꜱ ᴍᴜꜱᴛ ʙᴇ ᴘᴏꜱɪᴛɪᴠᴇ.')}")
            return
        
        # Check if user exists
        user_data = users_collection.find_one({"user_id": target_user_id})
        if not user_data:
            await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ᴜꜱᴇʀ ɴᴏᴛ ꜰᴏᴜɴᴅ.')}")
            return
        
        # Calculate expiry date
        premium_expires = datetime.now() + timedelta(days=days)
        
        # Update user to premium
        users_collection.update_one(
            {"user_id": target_user_id},
            {"$set": {"is_premium": True, "premium_expires": premium_expires}}
        )
        
        # Enhanced premium logging
        premium_log = {
            "action": "premium_subscription_added",
            "target_user_id": target_user_id,
            "days": days,
            "admin_id": user_id,
            "expires_at": premium_expires.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        logger.info(f"Premium subscription added: {json.dumps(premium_log)}")
        
        # Log activity in database
        premium_activity = {
            "type": "premium_added",
            "target_user_id": target_user_id,
            "admin_id": user_id,
            "days": days,
            "expires_at": premium_expires,
            "timestamp": datetime.now()
        }
        db.premium_logs.insert_one(premium_activity)
        
        # Send premium notification to log channel if configured
        if LOG_CHANNEL:
            try:
                log_text = f"⭐ {to_small_caps('ᴘʀᴇᴍɪᴜᴍ ꜱᴜʙꜱᴄʀɪᴘᴛɪᴏɴ ᴀᴅᴅᴇᴅ')}\n\n"
                log_text += f"{to_small_caps('ᴜꜱᴇʀ ɪᴅ:')} {target_user_id}\n"
                log_text += f"{to_small_caps('ᴅᴜʀᴀᴛɪᴏɴ:')} {days} days\n"
                log_text += f"{to_small_caps('ᴇxᴘɪʀᴇꜱ ᴏɴ:')} {premium_expires.strftime('%Y-%m-%d')}\n"
                log_text += f"{to_small_caps('ᴀᴅᴅᴇᴅ ʙʏ:')} Admin {user_id}"
                
                asyncio.create_task(context.bot.send_message(
                    chat_id=LOG_CHANNEL,
                    text=log_text
                ))
            except Exception as e:
                logger.error(f"Failed to send premium notification to log channel: {e}")
        
        # Notify user if possible
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"{get_emoji('premium')} {to_small_caps('ᴄᴏɴɢʀᴀᴛᴜʟᴀᴛɪᴏɴꜱ!')}\n\n"
                     f"{to_small_caps(f'ʏᴏᴜ ɴᴏᴡ ʜᴀᴠᴇ ᴘʀᴇᴍɪᴜᴍ ᴀᴄᴄᴇꜱꜱ ꜰᴏʀ {days} ᴅᴀʏꜱ!')}\n\n"
                     f"{to_small_caps('ᴇɴᴊᴏʏ ᴜɴʟɪᴍɪᴛᴇᴅ ᴅᴏᴡɴʟᴏᴀᴅꜱ, ʜɪɢʜᴇʀ ǫᴜᴀʟɪᴛʏ, ᴀɴᴅ ᴍᴏʀᴇ!')}"
            )
        except Exception as e:
            logger.error(f"Error notifying user about premium: {e}")
        
        # Respond to admin
        await update.message.reply_text(
            f"{get_emoji('success')} {to_small_caps(f'ᴀᴅᴅᴇᴅ {days} ᴅᴀʏꜱ ᴏꜰ ᴘʀᴇᴍɪᴜᴍ ᴛᴏ ᴜꜱᴇʀ {target_user_id}')}"
        )
        
    except ValueError:
        await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ɪɴᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ ᴏʀ ᴅᴀʏꜱ ᴠᴀʟᴜᴇ.')}")
    except Exception as e:
        logger.error(f"Error adding premium: {e}")
        await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ.')}")

async def rate_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle rating callback from users"""
    query = update.callback_query
    user = update.effective_user
    
    # Initialize user_info for error logging outside the try block
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    
    try:
        # Extract rating from callback data
        # Format: rate_<rating_value>_<spotify_id>
        parts = query.data.split("_")
        if len(parts) >= 2:
            rating_value = int(parts[1])
        else:
            await query.answer("Invalid rating format.")
            return
            
        if rating_value < 1 or rating_value > 5:
            await query.answer("Invalid rating value.")
            return
        
        # Log the rating
        details = {
            "action": "user_rated_bot",
            "rating": rating_value
        }
        await log_activity(context, "rating", user_info, details)
        
        # Save rating to database
        rating_data = {
            "user_id": user.id,
            "rating": rating_value,
            "timestamp": datetime.now()
        }
        
        # Insert or update rating
        db.ratings.update_one(
            {"user_id": user.id},
            {"$set": rating_data},
            upsert=True
        )
        
        # Thank the user and ask for feedback
        thank_text = f"{get_emoji('rating')} {to_small_caps('ᴛʜᴀɴᴋ ʏᴏᴜ ꜰᴏʀ ʏᴏᴜʀ ʀᴀᴛɪɴɢ!')}"
        thank_text += f"\n\n{to_small_caps('ʏᴏᴜ ʀᴀᴛᴇᴅ ᴛʜɪꜱ ʙᴏᴛ:')} "
        
        # Add stars based on rating
        for i in range(5):
            if i < rating_value:
                thank_text += "⭐"
            else:
                thank_text += "☆"
        
        thank_text += f"\n\n{to_small_caps('ᴡᴏᴜʟᴅ ʏᴏᴜ ʟɪᴋᴇ ᴛᴏ ᴘʀᴏᴠɪᴅᴇ ꜰᴇᴇᴅʙᴀᴄᴋ?')}"
        
        # Create feedback button
        keyboard = [[InlineKeyboardButton(
            f"{get_emoji('feedback')} {to_small_caps('ᴘʀᴏᴠɪᴅᴇ ꜰᴇᴇᴅʙᴀᴄᴋ')}",
            callback_data="feedback"
        )]]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Update original message with thank you
        await query.edit_message_text(thank_text, reply_markup=reply_markup)
        
        # Also answer the callback query
        await query.answer(f"You rated this bot {rating_value}/5")
        
    except Exception as e:
        logger.error(f"Error in rate_bot_callback: {e}")
        await query.answer("An error occurred. Please try again.")
        
        try:
            # Log the error
            details = {
                "message": str(e),
                "context": "rate_bot_callback",
                "callback_data": query.data
            }
            await log_activity(context, "error", user_info, details, level="ERROR")
        except Exception as log_error:
            logger.error(f"Failed to log error: {log_error}")

async def view_album_tracks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show and navigate album tracks (Callback query handler)"""
    query = update.callback_query
    user = update.effective_user
    
    # Initialize user_info for error logging outside the try block
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    
    try:
        # Extract album ID from callback data
        # Format: view_album_<spotify_id>
        spotify_id = query.data.split("_")[2]
        
        # Log album view request
        details = {
            "action": "view_album_tracks",
            "album_id": spotify_id
        }
        await log_activity(context, "request", user_info, details)
        
        # Update user's last activity time
        users_collection.update_one(
            {"user_id": user.id},
            {"$set": {"last_activity": datetime.now()}}
        )
        
        await query.answer("Loading album tracks...")
        
        # Get album details from Spotify API
        album_info = spotify.album(spotify_id)
        
        if not album_info:
            await query.edit_message_text(f"{get_emoji('error')} {to_small_caps('ᴄᴏᴜʟᴅ ɴᴏᴛ ꜰɪɴᴅ ᴀʟʙᴜᴍ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ.')}")
            return
            
        # Get album tracks
        tracks = album_info['tracks']['items']
        
        if not tracks:
            await query.edit_message_text(f"{get_emoji('error')} {to_small_caps('ɴᴏ ᴛʀᴀᴄᴋꜱ ꜰᴏᴜɴᴅ ɪɴ ᴛʜɪꜱ ᴀʟʙᴜᴍ.')}")
            return
        
        # Format album info
        album_name = album_info['name']
        artist_name = album_info['artists'][0]['name']
        total_tracks = album_info['total_tracks']
        
        # Create message
        message_text = f"{get_emoji('album')} {to_small_caps('ᴀʟʙᴜᴍ:')} {album_name}\n"
        message_text += f"{to_small_caps('ᴀʀᴛɪꜱᴛ:')} {artist_name}\n"
        message_text += f"{to_small_caps('ᴛʀᴀᴄᴋꜱ:')} {total_tracks}\n\n"
        message_text += f"{to_small_caps('ꜱᴇʟᴇᴄᴛ ᴀ ᴛʀᴀᴄᴋ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ:')}\n\n"
        
        # Add tracks to message (limit to 10 to avoid message too long)
        keyboard = []
        for i, track in enumerate(tracks[:10], 1):
            track_name = track['name']
            track_id = track['id']
            duration_ms = track['duration_ms']
            duration_min = int(duration_ms / 60000)
            duration_sec = int((duration_ms % 60000) / 1000)
            
            # Add track to message
            message_text += f"{i}. {track_name} ({duration_min}:{duration_sec:02d})\n"
            
            # Add track to keyboard
            keyboard.append([InlineKeyboardButton(
                f"{i}. {track_name[:30]}..." if len(track_name) > 30 else f"{i}. {track_name}",
                callback_data=f"dl_track_{track_id}"
            )])
        
        # Add back buttons
        keyboard.append([InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ ᴛᴏ ᴀʟʙᴜᴍ')}", callback_data=f"album_info_{spotify_id}")])
        keyboard.append([InlineKeyboardButton(f"{get_emoji('home')} {to_small_caps('ᴍᴀɪɴ ᴍᴇɴᴜ')}", callback_data="back_to_start")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send message with track list
        await query.edit_message_text(message_text, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error in view_album_tracks: {e}")
        await query.answer("An error occurred. Please try again.")
        
        try:
            # Log the error
            details = {
                "message": str(e),
                "context": "view_album_tracks",
                "callback_data": query.data
            }
            await log_activity(context, "error", user_info, details, level="ERROR")
        except Exception as log_error:
            logger.error(f"Failed to log error: {log_error}")

async def remove_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove premium from a user (Admin only)"""
    user_id = update.effective_user.id
    
    # Check if user is admin
    if str(user_id) not in ADMINS:
        error_msg = await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ.')}")
        # Auto-delete error message after 1 minute
        asyncio.create_task(delete_message_after_delay(context, error_msg.chat_id, error_msg.message_id))
        return
    
    # Check arguments
    args = context.args
    if len(args) < 1:
        await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ᴜꜱᴀɢᴇ: /removepremium <user_id>')}")
        return
    
    try:
        # Parse arguments
        target_user_id = int(args[0])
        
        # Check if user exists
        user_data = users_collection.find_one({"user_id": target_user_id})
        if not user_data:
            await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ᴜꜱᴇʀ ɴᴏᴛ ꜰᴏᴜɴᴅ.')}")
            return
        
        # Check if user is already not premium
        if not user_data.get("is_premium", False):
            await update.message.reply_text(f"{get_emoji('info')} {to_small_caps('ᴛʜɪꜱ ᴜꜱᴇʀ ɪꜱ ɴᴏᴛ ᴀ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀ.')}")
            return
        
        # Update user to remove premium
        users_collection.update_one(
            {"user_id": target_user_id},
            {"$set": {"is_premium": False}, "$unset": {"premium_expires": ""}}
        )
        
        # Enhanced premium removal logging
        premium_removal_log = {
            "action": "premium_subscription_removed",
            "target_user_id": target_user_id,
            "admin_id": user_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        logger.info(f"Premium subscription removed: {json.dumps(premium_removal_log)}")
        
        # Log activity in database
        premium_removal_activity = {
            "type": "premium_removed",
            "target_user_id": target_user_id,
            "admin_id": user_id,
            "timestamp": datetime.now()
        }
        db.premium_logs.insert_one(premium_removal_activity)
        
        # Send premium removal notification to log channel if configured
        if LOG_CHANNEL:
            try:
                log_text = f"🚫 {to_small_caps('ᴘʀᴇᴍɪᴜᴍ ꜱᴜʙꜱᴄʀɪᴘᴛɪᴏɴ ʀᴇᴍᴏᴠᴇᴅ')}\n\n"
                log_text += f"{to_small_caps('ᴜꜱᴇʀ ɪᴅ:')} {target_user_id}\n"
                log_text += f"{to_small_caps('ʀᴇᴍᴏᴠᴇᴅ ʙʏ:')} Admin {user_id}\n"
                log_text += f"{to_small_caps('ᴛɪᴍᴇ:')} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                asyncio.create_task(context.bot.send_message(
                    chat_id=LOG_CHANNEL,
                    text=log_text
                ))
            except Exception as e:
                logger.error(f"Failed to send premium removal notification to log channel: {e}")
        
        # Notify user if possible
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"{get_emoji('error')} {to_small_caps('ᴘʀᴇᴍɪᴜᴍ ꜱᴛᴀᴛᴜꜱ ʀᴇᴍᴏᴠᴇᴅ')}\n\n"
                     f"{to_small_caps('ʏᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ꜱᴛᴀᴛᴜꜱ ʜᴀꜱ ʙᴇᴇɴ ʀᴇᴍᴏᴠᴇᴅ.')}\n\n"
                     f"{to_small_caps('ʏᴏᴜ ᴀʀᴇ ɴᴏᴡ ᴀ ꜰʀᴇᴇ ᴜꜱᴇʀ ᴡɪᴛʜ ʟɪᴍɪᴛᴇᴅ ᴀᴄᴄᴇꜱꜱ.')}"
            )
        except Exception as e:
            logger.error(f"Error notifying user about premium removal: {e}")
        
        # Respond to admin
        await update.message.reply_text(
            f"{get_emoji('success')} {to_small_caps(f'ʀᴇᴍᴏᴠᴇᴅ ᴘʀᴇᴍɪᴜᴍ ꜱᴛᴀᴛᴜꜱ ꜰʀᴏᴍ ᴜꜱᴇʀ {target_user_id}')}"
        )
        
    except ValueError:
        await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ɪɴᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ.')}")
    except Exception as e:
        logger.error(f"Error removing premium: {e}")
        await update.message.reply_text(f"{get_emoji('error')} {to_small_caps('ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ.')}")

def format_youtube_playlist_id(playlist_id):
    """
    Format YouTube playlist ID properly - prepend 'PL' if not already present
    
    Args:
        playlist_id: The YouTube playlist ID to format
        
    Returns:
        Properly formatted playlist ID
    """
    # If it doesn't start with PL, it might be a shortened ID, so we prepend PL
    return f"PL{playlist_id}" if not playlist_id.startswith("PL") else playlist_id

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Spotify and YouTube links"""
    message = update.message
    link_text = message.text
    user = update.effective_user
    
    # Try to detect YouTube link first
    youtube_patterns = [
        r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]+)',  # Regular videos
        r'(?:https?://)?(?:www\.)?youtube\.com/playlist\?list=([a-zA-Z0-9_-]+)',  # Playlists
        r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]+)'  # Shorts
    ]
    
    for pattern in youtube_patterns:
        youtube_match = re.search(pattern, link_text)
        if youtube_match:
            # Handle as YouTube link
            await process_youtube_link(update, context, youtube_match, pattern)
            return
    
    # If not YouTube, try Spotify link detection
    spotify_pattern = r'https?://(?:open\.)?spotify\.com/(?:track|album|playlist)/([a-zA-Z0-9]+)(?:\?|$)'
    match = re.search(spotify_pattern, link_text)
    
    if not match:
        # Try alternative pattern for shortened links and different formats
        alt_pattern = r'spotify:(?:track|album|playlist):([a-zA-Z0-9]+)'
        match = re.search(alt_pattern, link_text)
        if not match:
            # Log failed match attempt
            logger.info(f"Failed to match link pattern: {link_text}")
            return
    
    # Extract link type and ID more robustly
    try:
        # First try to extract from URL structure
        if '/track/' in link_text:
            link_type = 'track'
        elif '/album/' in link_text:
            link_type = 'album'
        elif '/playlist/' in link_text:
            link_type = 'playlist'
        else:
            # Extract from pattern for URI format (spotify:type:id)
            parts = link_text.split(':')
            if len(parts) >= 3:
                link_type = parts[1]  # track, album, or playlist
            else:
                # Fallback to URL parsing
                link_type = link_text.split("/")[3].split("?")[0]
    except Exception as e:
        logger.error(f"Error extracting link type: {e}")
        # Create processing message just for the error
        processing_msg = await message.reply_text(f"{get_emoji('error')} {to_small_caps('ɪɴᴠᴀʟɪᴅ ꜱᴘᴏᴛɪꜰʏ ʟɪɴᴋ ꜰᴏʀᴍᴀᴛ.')}")
        return
    
    # Get Spotify ID from regex match
    spotify_id = match.group(1)
    
    # Log the extracted information for debugging
    logger.info(f"Extracted Spotify link type: {link_type}, ID: {spotify_id}")
    
    # Log the Spotify link request
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    details = {
        "action": "spotify_link_received",
        "link_type": link_type,
        "spotify_id": spotify_id,
        "full_link": link_text
    }
    await log_activity(context, "request", user_info, details)
    
    # Update user's last activity time
    users_collection.update_one(
        {"user_id": user.id},
        {"$set": {"last_activity": datetime.now()}}
    )
    
    # Send processing message
    processing_msg = await message.reply_text(f"{get_emoji('wait')} {to_small_caps('ᴘʀᴏᴄᴇꜱꜱɪɴɢ ʏᴏᴜʀ ꜱᴘᴏᴛɪꜰʏ ʟɪɴᴋ...')}")
    
    try:
        if link_type == "track":
            # Get track info from Spotify API
            track_info = spotify.track(spotify_id)
            
            if not track_info:
                await processing_msg.edit_text(f"{get_emoji('error')} {to_small_caps('ᴄᴏᴜʟᴅ ɴᴏᴛ ꜰɪɴᴅ ᴛʀᴀᴄᴋ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ.')}")
                return
                
            # Format track info
            track_name = track_info['name']
            artist_name = track_info['artists'][0]['name']
            album_name = track_info['album']['name']
            duration_ms = track_info['duration_ms']
            duration_min = int(duration_ms / 60000)
            duration_sec = int((duration_ms % 60000) / 1000)
            
            # Get album cover
            album_cover_url = None
            if track_info['album']['images']:
                album_cover_url = track_info['album']['images'][0]['url']
                
            # Check user's premium status
            user_data = users_collection.find_one({"user_id": user.id})
            is_premium = user_data and user_data.get("is_premium", False)
            
            # Check database for existing file
            existing_track = songs_collection.find_one({"spotify_id": spotify_id})
            
            # Prepare response text
            response = f"{get_emoji('track')} {to_small_caps('ꜰᴏᴜɴᴅ ᴛʀᴀᴄᴋ:')}\n\n"
            response += f"{to_small_caps('ᴀʀᴛɪꜱᴛ:')} {artist_name}\n"
            response += f"{to_small_caps('ᴛɪᴛʟᴇ:')} {track_name}\n"
            response += f"{to_small_caps('ᴀʟʙᴜᴍ:')} {album_name}\n"
            response += f"{to_small_caps('ᴅᴜʀᴀᴛɪᴏɴ:')} {duration_min}:{duration_sec:02d}"
            
            # Create quality selection buttons
            keyboard = []
            
            # Title row for quality options
            response += f"\n\n{get_emoji('download')} {to_small_caps('ꜱᴇʟᴇᴄᴛ ǫᴜᴀʟɪᴛʏ:')}"
            
            # Standard quality for all users (64kbps)
            keyboard.append([InlineKeyboardButton(
                f"{get_emoji('download')} {to_small_caps('ʟᴏᴡ ꜱɪᴢᴇ')} (64 ᴋʙᴘꜱ)",
                callback_data=f"dl_track_{spotify_id}_64"
            )])
            
            # Medium quality for all users (128kbps)
            keyboard.append([InlineKeyboardButton(
                f"{get_emoji('download')} {to_small_caps('ꜱᴛᴀɴᴅᴀʀᴅ')} (128 ᴋʙᴘꜱ)",
                callback_data=f"dl_track_{spotify_id}_128"
            )])
            
            # High quality for premium users only (320kbps)
            if is_premium:
                keyboard.append([InlineKeyboardButton(
                    f"{get_emoji('premium')} {to_small_caps('ʜɪɢʜ ǫᴜᴀʟɪᴛʏ')} (320 ᴋʙᴘꜱ)",
                    callback_data=f"dl_track_{spotify_id}_320"
                )])
            else:
                keyboard.append([InlineKeyboardButton(
                    f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ ꜰᴏʀ ʜɪɢʜ ǫᴜᴀʟɪᴛʏ')}",
                    callback_data="premium_info"
                )])
            
            # Add cache indicator if the track exists in the database
            if existing_track and DB_CHANNEL:
                response += f"\n\n{get_emoji('success')} {to_small_caps('ᴛʜɪꜱ ᴛʀᴀᴄᴋ ɪꜱ ɪɴ ᴏᴜʀ ᴄᴀᴄʜᴇ!')}"
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await processing_msg.delete()
            
            # Send with album cover if available
            if album_cover_url:
                try:
                    await message.reply_photo(photo=album_cover_url, caption=response, reply_markup=reply_markup)
                except Exception:
                    await message.reply_text(response, reply_markup=reply_markup)
            else:
                await message.reply_text(response, reply_markup=reply_markup)
                
        elif link_type == "album":
            # Get album tracks from Spotify API
            album_info = spotify.album(spotify_id)
            
            if not album_info:
                await processing_msg.edit_text(f"{get_emoji('error')} {to_small_caps('ᴄᴏᴜʟᴅ ɴᴏᴛ ꜰɪɴᴅ ᴀʟʙᴜᴍ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ.')}")
                return
                
            # Format album info
            album_name = album_info['name']
            artist_name = album_info['artists'][0]['name']
            total_tracks = album_info['total_tracks']
            
            # Get album cover
            album_cover_url = None
            if album_info['images']:
                album_cover_url = album_info['images'][0]['url']
            
            # Check if user is premium for album downloads
            user_data = users_collection.find_one({"user_id": user.id})
            is_premium = user_data and user_data.get("is_premium", False)
            
            response = f"{get_emoji('album')} {to_small_caps('ꜰᴏᴜɴᴅ ᴀʟʙᴜᴍ:')}\n\n"
            response += f"{to_small_caps('ᴀʀᴛɪꜱᴛ:')} {artist_name}\n"
            response += f"{to_small_caps('ᴀʟʙᴜᴍ:')} {album_name}\n"
            response += f"{to_small_caps('ᴛʀᴀᴄᴋꜱ:')} {total_tracks}"
            
            keyboard = []
            if is_premium:
                keyboard.append([InlineKeyboardButton(f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅ ᴀʟʙᴜᴍ')}",
                                             callback_data=f"dl_album_{spotify_id}")])
            else:
                response += f"\n\n{get_emoji('premium')} {to_small_caps('ᴀʟʙᴜᴍ ᴅᴏᴡɴʟᴏᴀᴅꜱ ᴀʀᴇ ᴀᴠᴀɪʟᴀʙʟᴇ ᴛᴏ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ ᴏɴʟʏ')}"
                keyboard.append([InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ')}",
                                             callback_data="premium_info")])
            
            # Add a button to browse tracks individually
            keyboard.append([InlineKeyboardButton(f"{get_emoji('track')} {to_small_caps('ʙʀᴏᴡꜱᴇ ᴛʀᴀᴄᴋꜱ')}",
                                         callback_data=f"view_album_{spotify_id}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await processing_msg.delete()
            
            # Send with album cover if available
            if album_cover_url:
                try:
                    await message.reply_photo(photo=album_cover_url, caption=response, reply_markup=reply_markup)
                except Exception:
                    await message.reply_text(response, reply_markup=reply_markup)
            else:
                await message.reply_text(response, reply_markup=reply_markup)
                
        elif link_type == "playlist":
            # Get playlist tracks from Spotify API
            playlist_info = spotify.playlist(spotify_id)
            
            if not playlist_info:
                await processing_msg.edit_text(f"{get_emoji('error')} {to_small_caps('ᴄᴏᴜʟᴅ ɴᴏᴛ ꜰɪɴᴅ ᴘʟᴀʏʟɪꜱᴛ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ.')}")
                return
                
            # Format playlist info
            playlist_name = playlist_info['name']
            owner_name = playlist_info['owner']['display_name']
            total_tracks = playlist_info['tracks']['total']
            
            # Get playlist cover
            playlist_cover_url = None
            if playlist_info['images']:
                playlist_cover_url = playlist_info['images'][0]['url']
            
            # Check if user is premium for playlist downloads
            user_data = users_collection.find_one({"user_id": user.id})
            is_premium = user_data and user_data.get("is_premium", False)
            
            response = f"{get_emoji('playlist')} {to_small_caps('ꜰᴏᴜɴᴅ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n"
            response += f"{to_small_caps('ɴᴀᴍᴇ:')} {playlist_name}\n"
            response += f"{to_small_caps('ᴄʀᴇᴀᴛᴏʀ:')} {owner_name}\n"
            response += f"{to_small_caps('ᴛʀᴀᴄᴋꜱ:')} {total_tracks}"
            
            keyboard = []
            if is_premium:
                keyboard.append([InlineKeyboardButton(f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅ ᴘʟᴀʏʟɪꜱᴛ')}",
                                             callback_data=f"dl_playlist_{spotify_id}")])
            else:
                response += f"\n\n{get_emoji('premium')} {to_small_caps('ᴘʟᴀʏʟɪꜱᴛ ᴅᴏᴡɴʟᴏᴀᴅꜱ ᴀʀᴇ ᴀᴠᴀɪʟᴀʙʟᴇ ᴛᴏ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ ᴏɴʟʏ')}"
                keyboard.append([InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ')}",
                                             callback_data="premium_info")])
            
            # Add a button to browse tracks individually
            keyboard.append([InlineKeyboardButton(f"{get_emoji('track')} {to_small_caps('ʙʀᴏᴡꜱᴇ ᴛʀᴀᴄᴋꜱ')}",
                                         callback_data=f"view_playlist_{spotify_id}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await processing_msg.delete()
            
            # Send with playlist cover if available
            if playlist_cover_url:
                try:
                    await message.reply_photo(photo=playlist_cover_url, caption=response, reply_markup=reply_markup)
                except Exception:
                    await message.reply_text(response, reply_markup=reply_markup)
            else:
                await message.reply_text(response, reply_markup=reply_markup)
        
        else:
            await processing_msg.edit_text(f"{get_emoji('error')} {to_small_caps('ᴜɴꜱᴜᴘᴘᴏʀᴛᴇᴅ ʟɪɴᴋ ᴛʏᴘᴇ.')}")
    
    except Exception as e:
        logger.error(f"Error processing Spotify link: {e}")
        await processing_msg.edit_text(f"{get_emoji('error')} {to_small_caps('ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ ᴡʜɪʟᴇ ᴘʀᴏᴄᴇꜱꜱɪɴɢ ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ.')}")

async def process_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE, youtube_match, pattern) -> None:
    """Process YouTube links to extract audio"""
    message = update.message
    user = update.effective_user
    youtube_id = youtube_match.group(1)
    youtube_url = message.text
    
    # Determine link type (video, playlist, shorts)
    if "playlist" in pattern:
        link_type = "playlist"
    elif "shorts" in pattern:
        link_type = "shorts"
    else:
        link_type = "video"
    
    # Log the YouTube link request
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    details = {
        "action": "youtube_link_received",
        "link_type": link_type,
        "youtube_id": youtube_id,
        "full_link": youtube_url
    }
    await log_activity(context, "request", user_info, details)
    
    # Update user's last activity time
    users_collection.update_one(
        {"user_id": user.id},
        {"$set": {"last_activity": datetime.now()}}
    )
    
    # Send processing message
    processing_msg = await message.reply_text(f"{get_emoji('wait')} {to_small_caps('ᴘʀᴏᴄᴇꜱꜱɪɴɢ ʏᴏᴜʀ ʏᴏᴜᴛᴜʙᴇ ʟɪɴᴋ...')}")
    
    try:
        # Get video title and thumbnail using yt-dlp
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True if link_type == "playlist" else False,
            'skip_download': True,
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            
            if link_type == "playlist":
                # Handle playlist
                playlist_title = info.get('title', 'Unknown Playlist')
                entries_count = len(info.get('entries', []))
                
                # Prepare response text
                response = f"{get_emoji('playlist')} {to_small_caps('ꜰᴏᴜɴᴅ ʏᴏᴜᴛᴜʙᴇ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n"
                response += f"{to_small_caps('ᴛɪᴛʟᴇ:')} {playlist_title}\n"
                response += f"{to_small_caps('ᴠɪᴅᴇᴏꜱ:')} {entries_count}\n"
                
                # Check user's premium status for playlist downloads
                user_data = users_collection.find_one({"user_id": user.id})
                is_premium = user_data and user_data.get("is_premium", False)
                
                keyboard = []
                
                # Premium users can download playlists
                if is_premium:
                    response += f"\n{get_emoji('download')} {to_small_caps('ꜱᴇʟᴇᴄᴛ ᴏᴘᴛɪᴏɴ:')}"
                    keyboard.append([InlineKeyboardButton(
                        f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅ ᴀʟʟ ᴀᴜᴅɪᴏ')}",
                        callback_data=f"dl_yt_playlist_{youtube_id}"
                    )])
                else:
                    response += f"\n\n{get_emoji('premium')} {to_small_caps('ᴘʟᴀʏʟɪꜱᴛ ᴅᴏᴡɴʟᴏᴀᴅꜱ ᴀʀᴇ ᴀᴠᴀɪʟᴀʙʟᴇ ᴛᴏ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ ᴏɴʟʏ')}"
                    keyboard.append([InlineKeyboardButton(
                        f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ')}",
                        callback_data="premium_info"
                    )])
                
                # Add button to browse videos
                keyboard.append([InlineKeyboardButton(
                    f"{get_emoji('track')} {to_small_caps('ʙʀᴏᴡꜱᴇ ᴠɪᴅᴇᴏꜱ')}",
                    callback_data=f"view_yt_playlist_{youtube_id}"
                )])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await processing_msg.delete()
                
                # Send message with playlist thumbnail if available
                thumbnail = info.get('thumbnail')
                if thumbnail:
                    try:
                        await message.reply_photo(photo=thumbnail, caption=response, reply_markup=reply_markup)
                    except Exception:
                        await message.reply_text(response, reply_markup=reply_markup)
                else:
                    await message.reply_text(response, reply_markup=reply_markup)
                
            else:
                # Handle single video/shorts
                title = info.get('title', 'Unknown Video')
                duration = info.get('duration', 0)
                duration_min = int(duration / 60)
                duration_sec = int(duration % 60)
                channel = info.get('uploader', 'Unknown')
                
                # Prepare response text
                response = f"{get_emoji('track')} {to_small_caps('ꜰᴏᴜɴᴅ ʏᴏᴜᴛᴜʙᴇ ᴠɪᴅᴇᴏ:')}\n\n"
                response += f"{to_small_caps('ᴛɪᴛʟᴇ:')} {title}\n"
                response += f"{to_small_caps('ᴄʜᴀɴɴᴇʟ:')} {channel}\n"
                response += f"{to_small_caps('ᴅᴜʀᴀᴛɪᴏɴ:')} {duration_min}:{duration_sec:02d}"
                
                # Check user's premium status
                user_data = users_collection.find_one({"user_id": user.id})
                is_premium = user_data and user_data.get("is_premium", False)
                
                # Create quality selection buttons for audio
                keyboard = []
                
                # Title row for quality options
                response += f"\n\n{get_emoji('download')} {to_small_caps('ꜱᴇʟᴇᴄᴛ ᴀᴜᴅɪᴏ ǫᴜᴀʟɪᴛʏ:')}"
                
                # Standard quality for all users (64kbps)
                keyboard.append([InlineKeyboardButton(
                    f"{get_emoji('download')} {to_small_caps('ʟᴏᴡ ꜱɪᴢᴇ')} (64 ᴋʙᴘꜱ)",
                    callback_data=f"dl_yt_{youtube_id}_64"
                )])
                
                # Medium quality for all users (128kbps)
                keyboard.append([InlineKeyboardButton(
                    f"{get_emoji('download')} {to_small_caps('ꜱᴛᴀɴᴅᴀʀᴅ')} (128 ᴋʙᴘꜱ)",
                    callback_data=f"dl_yt_{youtube_id}_128"
                )])
                
                # High quality for premium users only (320kbps)
                if is_premium:
                    keyboard.append([InlineKeyboardButton(
                        f"{get_emoji('premium')} {to_small_caps('ʜɪɢʜ ǫᴜᴀʟɪᴛʏ')} (320 ᴋʙᴘꜱ)",
                        callback_data=f"dl_yt_{youtube_id}_320"
                    )])
                else:
                    keyboard.append([InlineKeyboardButton(
                        f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ ꜰᴏʀ ʜɪɢʜ ǫᴜᴀʟɪᴛʏ')}",
                        callback_data="premium_info"
                    )])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await processing_msg.delete()
                
                # Send with video thumbnail if available
                thumbnail = info.get('thumbnail')
                if thumbnail:
                    try:
                        await message.reply_photo(photo=thumbnail, caption=response, reply_markup=reply_markup)
                    except Exception:
                        await message.reply_text(response, reply_markup=reply_markup)
                else:
                    await message.reply_text(response, reply_markup=reply_markup)
    
    except Exception as e:
        logger.error(f"Error processing YouTube link: {e}")
        await processing_msg.edit_text(f"{get_emoji('error')} {to_small_caps('ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ ᴡʜɪʟᴇ ᴘʀᴏᴄᴇꜱꜱɪɴɢ ʏᴏᴜʀ ʏᴏᴜᴛᴜʙᴇ ʟɪɴᴋ.')}")

async def ftmdl_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline music search command"""
    user = update.effective_user
    query_text = " ".join(context.args) if context.args else None
    
    if not query_text:
        # Show help if no search query
        help_msg = f"{get_emoji('search')} {to_small_caps('ᴍᴜꜱɪᴄ ꜱᴇᴀʀᴄʜ ʜᴇʟᴘ:')}\n\n"
        help_msg += f"{to_small_caps('ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ᴛᴏ ꜱᴇᴀʀᴄʜ ꜰᴏʀ ᴍᴜꜱɪᴄ ᴏɴ ꜱᴘᴏᴛɪꜰʏ')}\n\n"
        help_msg += f"{get_emoji('info')} {to_small_caps('ᴇxᴀᴍᴘʟᴇ:')}\n"
        help_msg += f"/ftmdl Imagine Dragons Thunder\n\n"
        help_msg += f"{to_small_caps('ᴛʜɪꜱ ᴡɪʟʟ ꜱᴇᴀʀᴄʜ ꜰᴏʀ ᴛʜᴇ ꜱᴏɴɢ ᴀɴᴅ ᴘʀᴏᴠɪᴅᴇ ᴅᴏᴡɴʟᴏᴀᴅ ᴏᴘᴛɪᴏɴꜱ')}"
        
        await update.message.reply_text(help_msg)
        return
    
    # Log search request
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    details = {
        "action": "search_requested",
        "query": query_text
    }
    await log_activity(context, "search", user_info, details)
    
    # Show searching message
    search_msg = await update.message.reply_text(
        f"{get_emoji('search')} {to_small_caps('ꜱᴇᴀʀᴄʜɪɴɢ ꜰᴏʀ:')} {query_text}"
    )
    
    try:
        # Search Spotify for tracks
        results = spotify.search(q=query_text, type='track', limit=5)
        tracks = results['tracks']['items']
        
        if not tracks:
            await search_msg.edit_text(f"{get_emoji('error')} {to_small_caps('ɴᴏ ʀᴇꜱᴜʟᴛꜱ ꜰᴏᴜɴᴅ. ᴛʀʏ ᴀ ᴅɪꜰꜰᴇʀᴇɴᴛ ꜱᴇᴀʀᴄʜ.')}")
            return
        
        # Create message with search results
        result_text = f"{get_emoji('search')} {to_small_caps('ꜱᴇᴀʀᴄʜ ʀᴇꜱᴜʟᴛꜱ ꜰᴏʀ:')} {query_text}\n\n"
        
        # Create keyboard with track buttons (with quality options)
        keyboard = []
        
        # Check user's premium status
        user_data = users_collection.find_one({"user_id": user.id})
        is_premium = user_data and user_data.get("is_premium", False)
        
        for i, track in enumerate(tracks):
            track_name = track['name']
            artist_name = track['artists'][0]['name']
            track_id = track['id']
            
            # Add to results text
            result_text += f"{i+1}. {track_name} - {artist_name}\n"
            
            # Create track header button (non-functional, just for display)
            keyboard.append([
                InlineKeyboardButton(
                    f"🎵 {i+1}. {track_name[:20]}{'...' if len(track_name) > 20 else ''} - {artist_name[:15]}{'...' if len(artist_name) > 15 else ''}",
                    callback_data=f"dummy_{i}"  # This won't do anything
                )
            ])
            
            # Create quality option sub-buttons
            quality_row = []
            
            # Low quality option (64kbps) for all users
            quality_row.append(
                InlineKeyboardButton(
                    f"{get_emoji('download')} 64k",
                    callback_data=f"dl_track_{track_id}_64"
                )
            )
            
            # Medium quality option (128kbps) for all users
            quality_row.append(
                InlineKeyboardButton(
                    f"{get_emoji('download')} 128k",
                    callback_data=f"dl_track_{track_id}_128"
                )
            )
            
            # High quality option (320kbps) for premium users only
            if is_premium:
                quality_row.append(
                    InlineKeyboardButton(
                        f"{get_emoji('premium')} 320k",
                        callback_data=f"dl_track_{track_id}_320"
                    )
                )
            
            keyboard.append(quality_row)
        
        # Add a search again button
        keyboard.append([
            InlineKeyboardButton(f"🔍 {to_small_caps('ꜱᴇᴀʀᴄʜ ᴀɢᴀɪɴ')}", callback_data="search_music")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Try to get album art for the first result
        try:
            album_art = tracks[0]['album']['images'][0]['url']
            await search_msg.delete()
            await update.message.reply_photo(
                photo=album_art,
                caption=result_text,
                reply_markup=reply_markup
            )
        except Exception:
            # Fallback to text-only if image fails
            await search_msg.edit_text(
                text=result_text,
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logger.error(f"Error searching: {e}")
        error_msg = await search_msg.edit_text(f"{get_emoji('error')} {to_small_caps('ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ ᴡʜɪʟᴇ ꜱᴇᴀʀᴄʜɪɴɢ.')}")
        
        # Schedule auto-deletion of error message after 1 minute
        asyncio.create_task(delete_message_after_delay(context, error_msg.chat_id, error_msg.message_id))

async def search_music_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt user to enter a search term"""
    query = update.callback_query
    await query.answer()
    
    # Send search prompt
    search_text = f"{get_emoji('search')} {to_small_caps('ᴍᴜꜱɪᴄ ꜱᴇᴀʀᴄʜ')}\n\n"
    search_text += f"{to_small_caps('ᴛᴏ ꜱᴇᴀʀᴄʜ ꜰᴏʀ ᴍᴜꜱɪᴄ, ᴜꜱᴇ ᴛʜᴇ ᴄᴏᴍᴍᴀɴᴅ:')}\n\n"
    search_text += f"/ftmdl song name artist\n\n"
    search_text += f"{to_small_caps('ᴇxᴀᴍᴘʟᴇ:')} /ftmdl Shape of You Ed Sheeran"
    
    # Create keyboard with back button
    keyboard = [
        [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Removed Markdown parsing to avoid formatting issues
    await query.message.reply_text(search_text, reply_markup=reply_markup)

async def about_dev_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show developer information through callback"""
    query = update.callback_query
    await query.answer()
    
    dev_text = f"👨‍💻 {to_small_caps('ᴅᴇᴠᴇʟᴏᴘᴇʀ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ')}\n\n"
    dev_text += f"{to_small_caps('ᴛʜɪꜱ ʙᴏᴛ ᴡᴀꜱ ᴅᴇᴠᴇʟᴏᴘᴇᴅ ʙʏ:')} @SpotifyDLBot_Admin\n\n"
    dev_text += f"{to_small_caps('ᴠᴇʀꜱɪᴏɴ:')} 2.0.0\n"
    dev_text += f"{to_small_caps('ʟᴀꜱᴛ ᴜᴘᴅᴀᴛᴇ:')} {datetime.now().strftime('%Y-%m-%d')}\n\n"
    dev_text += f"{to_small_caps('ᴛᴇᴄʜɴᴏʟᴏɢɪᴇꜱ ᴜꜱᴇᴅ:')}\n"
    dev_text += f"• Python-Telegram-Bot\n• Spotipy\n• yt-dlp\n• MongoDB\n• FFmpeg\n\n"
    dev_text += f"{to_small_caps('ꜰᴏʀ ꜱᴜᴘᴘᴏʀᴛ ᴏʀ ꜰᴇᴇᴅʙᴀᴄᴋ, ᴄᴏɴᴛᴀᴄᴛ:')} @SpotifyDLBot_Admin"
    
    # Create support and feedback buttons
    keyboard = [
        [InlineKeyboardButton("📨 Contact Developer", url="https://t.me/SpotifyDLBot_Admin")],
        [InlineKeyboardButton("⭐ Rate Bot", callback_data="rate_bot")],
        [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query.message.photo:
        # If original message has a photo, edit caption
        await query.edit_message_caption(caption=dev_text, reply_markup=reply_markup)
    else:
        # Otherwise edit text
        await query.edit_message_text(text=dev_text, reply_markup=reply_markup)

async def my_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user status through callback"""
    query = update.callback_query
    user = update.effective_user
    user_id = user.id
    await query.answer()
    
    user_data = users_collection.find_one({"user_id": user_id})
    
    if not user_data:
        # Create user if not exists
        users_collection.insert_one({
            "user_id": user_id,
            "username": user.username or "",
            "first_name": user.first_name,
            "joined_at": datetime.now(),
            "is_premium": False,
            "downloads_today": 0,
            "total_downloads": 0,
            "last_download_date": datetime.now(),
            "last_activity": datetime.now(),
        })
        user_data = users_collection.find_one({"user_id": user_id})
    
    # Check if download count should be reset (new day)
    last_download_date = user_data.get("last_download_date")
    if last_download_date and isinstance(last_download_date, datetime):
        today = datetime.now().date()
        last_date = last_download_date.date()
        
        if today > last_date:
            # Reset download count for a new day
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"downloads_today": 0, "last_download_date": datetime.now()}}
            )
            # Refresh user data
            user_data = users_collection.find_one({"user_id": user_id})
    
    status_text = f"{get_emoji('info')} {to_small_caps('ʏᴏᴜʀ ꜱᴛᴀᴛᴜꜱ:')}\n\n"
    
    if user_data.get("is_premium"):
        # Check if premium has expired
        premium_expires = user_data.get("premium_expires")
        if premium_expires and isinstance(premium_expires, datetime):
            if datetime.now() > premium_expires:
                # Premium expired, update user to free
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_premium": False}}
                )
                
                # Show free status
                downloads_today = user_data.get("downloads_today", 0)
                status_text += f"{to_small_caps('ꜰʀᴇᴇ ᴜꜱᴇʀ')} ({get_emoji('error')} {to_small_caps('ᴘʀᴇᴍɪᴜᴍ ᴇxᴘɪʀᴇᴅ')})\n"
                status_text += f"{to_small_caps(f'ᴅᴏᴡɴʟᴏᴀᴅꜱ ᴛᴏᴅᴀʏ: {downloads_today}/{FREE_DAILY_LIMIT}')}\n"
                status_text += f"{to_small_caps(f'ǫᴜᴀʟɪᴛʏ: {FREE_BITRATE}ᴋʙᴘꜱ')}"
                
                # Add premium button
                keyboard = [
                    [InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ')}", callback_data="premium_info")],
                    [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", callback_data="back_to_start")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if query.message.photo:
                    await query.edit_message_caption(caption=status_text, reply_markup=reply_markup)
                else:
                    await query.edit_message_text(text=status_text, reply_markup=reply_markup)
                return
            
            # Premium is active, show expiry date
            days_left = (premium_expires - datetime.now()).days
            expires_text = f" ({to_small_caps(f'ᴇxᴘɪʀᴇꜱ ɪɴ {days_left} ᴅᴀʏꜱ')})"
        else:
            expires_text = ""
            
        status_text += f"{get_emoji('premium')} {to_small_caps('ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀ')}{expires_text}\n"
        status_text += f"{get_emoji('success')} {to_small_caps('ᴜɴʟɪᴍɪᴛᴇᴅ ᴅᴏᴡɴʟᴏᴀᴅꜱ')}\n"
        status_text += f"{get_emoji('success')} {to_small_caps(f'ʜɪɢʜ ǫᴜᴀʟɪᴛʏ ({PREMIUM_BITRATE}ᴋʙᴘꜱ)')}"
    else:
        downloads_today = user_data.get("downloads_today", 0)
        status_text += f"{to_small_caps('ꜰʀᴇᴇ ᴜꜱᴇʀ')}\n"
        status_text += f"{to_small_caps(f'ᴅᴏᴡɴʟᴏᴀᴅꜱ ᴛᴏᴅᴀʏ: {downloads_today}/{FREE_DAILY_LIMIT}')}\n"
        status_text += f"{to_small_caps(f'ǫᴜᴀʟɪᴛʏ: {FREE_BITRATE}ᴋʙᴘꜱ')}"
    
    # Show total downloads
    total_downloads = user_data.get("total_downloads", 0)
    if total_downloads > 0:
        status_text += f"\n{get_emoji('download')} {to_small_caps(f'ᴛᴏᴛᴀʟ ᴅᴏᴡɴʟᴏᴀᴅꜱ: {total_downloads}')}"
    
    # Add back button
    keyboard = [
        [InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ')}", callback_data="premium_info")],
        [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query.message.photo:
        await query.edit_message_caption(caption=status_text, reply_markup=reply_markup)
    else:
        await query.edit_message_text(text=status_text, reply_markup=reply_markup)

async def back_to_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to start menu"""
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    
    welcome_msg = f"{get_emoji('start')} {to_small_caps('ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ꜱᴘᴏᴛɪꜰʏ ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ʙᴏᴛ!')}\n\n"
    welcome_msg += f"{get_emoji('info')} {to_small_caps('ᴀʙᴏᴜᴛ ᴛʜɪꜱ ʙᴏᴛ:')}\n"
    welcome_msg += f"• {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅ ᴀɴʏ ꜱᴘᴏᴛɪꜰʏ ᴛʀᴀᴄᴋ, ᴀʟʙᴜᴍ ᴏʀ ᴘʟᴀʏʟɪꜱᴛ')}\n"
    welcome_msg += f"• {to_small_caps('ʜɪɢʜ ǫᴜᴀʟɪᴛʏ ᴍᴘ3 ᴄᴏɴᴠᴇʀꜱɪᴏɴ')}\n"
    welcome_msg += f"• {to_small_caps('ꜱᴇᴀʀᴄʜ ꜰᴏʀ ᴍᴜꜱɪᴄ ᴜꜱɪɴɢ /ꜰᴛᴍᴅʟ ᴄᴏᴍᴍᴀɴᴅ')}\n\n"
    welcome_msg += f"{get_emoji('headphones')} {to_small_caps('ʜᴏᴡ ᴛᴏ ᴜꜱᴇ:')}\n"
    welcome_msg += f"1. {to_small_caps('ꜱᴇɴᴅ ᴀɴʏ ꜱᴘᴏᴛɪꜰʏ ʟɪɴᴋ')}\n"
    welcome_msg += f"2. {to_small_caps('ᴏʀ ᴜꜱᴇ /ꜰᴛᴍᴅʟ ꜱᴏɴɢ ɴᴀᴍᴇ ᴛᴏ ꜱᴇᴀʀᴄʜ')}\n"
    welcome_msg += f"3. {to_small_caps('ꜱᴇʟᴇᴄᴛ ᴀɴᴅ ᴅᴏᴡɴʟᴏᴀᴅ ʏᴏᴜʀ ᴍᴜꜱɪᴄ')}"
    
    # Create inline keyboard with more options
    keyboard = [
        [
            InlineKeyboardButton(f"{get_emoji('info')} Help", callback_data="help"),
            InlineKeyboardButton(f"{get_emoji('premium')} Premium", callback_data="premium_info")
        ],
        [
            InlineKeyboardButton(f"{get_emoji('stats')} My Status", callback_data="my_status"),
            InlineKeyboardButton(f"{get_emoji('developer')} About Dev", callback_data="about_dev")
        ],
        [
            InlineKeyboardButton(f"{get_emoji('search')} Search Music", callback_data="search_music")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query.message.photo:
        await query.edit_message_caption(caption=welcome_msg, reply_markup=reply_markup)
    else:
        await query.edit_message_text(text=welcome_msg, reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button callbacks"""
    query = update.callback_query
    user = update.effective_user
    
    # Common user info for logging
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    
    # Check if message exists and has text
    has_message_text = False
    if query.message and hasattr(query.message, 'text') and query.message.text:
        has_message_text = True
    
    # Prepare user info for logging
    user_info = {
        "id": user.id,
        "username": user.username or "",
        "first_name": user.first_name
    }
    
    # Log all button clicks
    details = {
        "action": "button_click",
        "callback_data": query.data,
        "message_id": query.message.message_id if query.message else "unknown"
    }
    await log_activity(context, "interaction", user_info, details)
    
    # Update user's last activity
    users_collection.update_one(
        {"user_id": user.id},
        {"$set": {"last_activity": datetime.now()}}
    )
    
    # Handle dummy buttons (used for display only in search results)
    if query.data.startswith("dummy_"):
        await query.answer("This is just a title, use the quality buttons below to download")
        return
        
    # Always answer the callback query for all other buttons
    await query.answer()
    
    try:
        if query.data == "back_to_start":
            await back_to_start(update, context)
        elif query.data == "help":
            help_text = f"{get_emoji('info')} {to_small_caps('ʜᴏᴡ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ʙᴏᴛ:')}\n\n"
            help_text += f"1️⃣ {to_small_caps('ꜱᴇɴᴅ ᴀɴʏ ꜱᴘᴏᴛɪꜰʏ ʟɪɴᴋ (ᴛʀᴀᴄᴋ, ᴀʟʙᴜᴍ ᴏʀ ᴘʟᴀʏʟɪꜱᴛ)')}\n\n"
            help_text += f"2️⃣ {to_small_caps('ᴛʜᴇ ʙᴏᴛ ᴡɪʟʟ ꜰᴇᴛᴄʜ ᴛʜᴇ ᴅᴇᴛᴀɪʟꜱ ᴀɴᴅ ꜱʜᴏᴡ ʏᴏᴜ ᴏᴘᴛɪᴏɴꜱ')}\n\n"
            help_text += f"3️⃣ {to_small_caps('ᴄʟɪᴄᴋ ᴏɴ ᴛʜᴇ ᴅᴏᴡɴʟᴏᴀᴅ ʙᴜᴛᴛᴏɴ ᴛᴏ ɢᴇᴛ ʏᴏᴜʀ ᴍᴘ3')}\n\n"
            
            # Add a back button
            keyboard = [
                [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", callback_data="back_to_start")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Edit message text if possible, otherwise send new message
            try:
                if has_message_text:
                    await query.edit_message_text(text=help_text, reply_markup=reply_markup)
                else:
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=help_text,
                        reply_markup=reply_markup
                    )
            except Exception as e:
                logger.error(f"Error updating help message: {e}")
                # Fallback to sending a new message
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=help_text,
                    reply_markup=reply_markup
                )
            
            # Log help request
            details = {
                "action": "help_viewed",
                "source": "button_click"
            }
            await log_activity(context, "help", user_info, details)
        
        # Handle My Status button
        elif query.data == "my_status":
            await my_status_callback(update, context)
            
        # Handle About Dev button
        elif query.data == "about_dev":
            await about_dev_callback(update, context)
            
        # Handle Admin button: Refresh Stats
        elif query.data == "refresh_stats":
            # Check if user is admin
            if str(user.id) not in ADMINS:
                await query.message.reply_text(f"{get_emoji('error')} {to_small_caps('ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ꜰᴇᴀᴛᴜʀᴇ.')}")
                return
            
            # Re-run the admin command to refresh stats
            temp_update = Update(update.update_id, message=query.message)
            await admin_command(temp_update, context)
            
            # Log refresh stats action
            details = {
                "action": "refresh_stats",
                "source": "button_click"
            }
            await log_activity(context, "admin", user_info, details)
            
        # Handle Admin button: List Users
        elif query.data == "list_users":
            # Check if user is admin
            if str(user.id) not in ADMINS:
                await query.message.reply_text(f"{get_emoji('error')} {to_small_caps('ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ꜰᴇᴀᴛᴜʀᴇ.')}")
                return
            
            # Create a temporary context with args to pass to users_command
            context.args = ["10", "0"]  # Default limit and skip
            temp_update = Update(update.update_id, message=query.message)
            await users_command(temp_update, context)
            
            # Log list users action
            details = {
                "action": "list_users",
                "source": "button_click"
            }
            await log_activity(context, "admin", user_info, details)
            
        # Handle Admin button: Clean Cache
        elif query.data == "clean_cache":
            # Check if user is admin
            if str(user.id) not in ADMINS:
                await query.message.reply_text(f"{get_emoji('error')} {to_small_caps('ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ꜰᴇᴀᴛᴜʀᴇ.')}")
                return
            
            # Clean the temp directory
            try:
                deleted_count = 0
                for file in os.listdir('temp'):
                    file_path = os.path.join('temp', file)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        deleted_count += 1
                        
                # Delete old entries from songs collection
                old_time = datetime.now() - timedelta(days=7)
                deleted_db = songs_collection.delete_many({"added_on": {"$lt": old_time}}).deleted_count
                
                # Send confirmation message
                await query.message.reply_text(
                    f"{get_emoji('success')} {to_small_caps('ᴄᴀᴄʜᴇ ᴄʟᴇᴀɴᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ!')}\n\n"
                    f"• {to_small_caps(f'ᴅᴇʟᴇᴛᴇᴅ ꜰɪʟᴇꜱ: {deleted_count}')}\n"
                    f"• {to_small_caps(f'ᴅᴇʟᴇᴛᴇᴅ ᴅʙ ᴇɴᴛʀɪᴇꜱ: {deleted_db}')}"
                )
                
                # Log cache clean action
                details = {
                    "action": "clean_cache",
                    "files_deleted": deleted_count,
                    "db_entries_deleted": deleted_db
                }
                await log_activity(context, "admin", user_info, details)
                
            except Exception as e:
                logger.error(f"Error cleaning cache: {e}")
                await query.message.reply_text(
                    f"{get_emoji('error')} {to_small_caps('ᴇʀʀᴏʀ ᴄʟᴇᴀɴɪɴɢ ᴄᴀᴄʜᴇ:')}\n\n{str(e)[:100]}"
                )
                
        # Handle Admin button: Broadcast
        elif query.data == "broadcast":
            # Check if user is admin
            if str(user.id) not in ADMINS:
                await query.message.reply_text(f"{get_emoji('error')} {to_small_caps('ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ꜰᴇᴀᴛᴜʀᴇ.')}")
                return
            
            # Send instructions for broadcasting
            await query.message.reply_text(
                f"{get_emoji('broadcast')} {to_small_caps('ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴍᴇꜱꜱᴀɢᴇ')}\n\n"
                f"{to_small_caps('ᴛᴏ ꜱᴇɴᴅ ᴀ ʙʀᴏᴀᴅᴄᴀꜱᴛ, ʀᴇᴘʟʏ ᴛᴏ ᴛʜɪꜱ ᴍᴇꜱꜱᴀɢᴇ ᴡɪᴛʜ ᴛʜᴇ ᴛᴇxᴛ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ꜱᴇɴᴅ ᴛᴏ ᴀʟʟ ᴜꜱᴇʀꜱ.')}"
            )
            
            # Store the message ID for handling broadcast replies
            context.user_data["broadcast_request_id"] = query.message.message_id
            
            # Log broadcast initiation
            details = {
                "action": "broadcast_initiated",
                "source": "button_click"
            }
            await log_activity(context, "admin", user_info, details)
            
        # Handle Search Music button
        elif query.data == "search_music":
            await search_music_prompt(update, context)
            
        # Spotify playlist browsing handler
        elif query.data.startswith("view_spotify_playlist_"):
            # Import asyncio for use in this function
            import asyncio
            
            # Extract playlist ID and page number
            parts = query.data.split("_")
            playlist_id = parts[3]
            page = int(parts[4]) if len(parts) > 4 else 1
            
            # Send a processing message
            status_msg = await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"{get_emoji('wait')} {to_small_caps('ʟᴏᴀᴅɪɴɢ ꜱᴘᴏᴛɪꜰʏ ᴘʟᴀʏʟɪꜱᴛ... ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ.')}"
            )
            
            try:
                # Get playlist information from Spotify API
                playlist = spotify.playlist(playlist_id)
                
                if not playlist:
                    await status_msg.edit_text(
                        f"{get_emoji('error')} {to_small_caps('ᴄᴏᴜʟᴅ ɴᴏᴛ ꜰɪɴᴅ ᴘʟᴀʏʟɪꜱᴛ')}"
                    )
                    return
                
                # Get playlist details
                playlist_name = playlist.get('name', 'Unknown Playlist')
                owner_name = playlist.get('owner', {}).get('display_name', 'Unknown')
                
                # Get tracks with pagination (Spotify API already supports pagination)
                items_per_page = 10
                offset = (page - 1) * items_per_page
                
                # Get tracks for the current page
                results = spotify.playlist_items(
                    playlist_id, 
                    offset=offset, 
                    limit=items_per_page,
                    fields='items(track(id,name,artists,album(name))),total'
                )
                
                total_tracks = results.get('total', 0)
                tracks = [item.get('track') for item in results.get('items', []) if item.get('track')]
                
                # Calculate max pages
                max_pages = (total_tracks + items_per_page - 1) // items_per_page
                
                # Validate page number
                if page < 1:
                    page = 1
                elif page > max_pages:
                    page = max_pages
                
                # Build message with track list
                message = f"{get_emoji('playlist')} {to_small_caps('ꜱᴘᴏᴛɪꜰʏ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n"
                message += f"{to_small_caps('ɴᴀᴍᴇ:')} {playlist_name}\n"
                message += f"{to_small_caps('ᴄʀᴇᴀᴛᴏʀ:')} {owner_name}\n"
                message += f"{to_small_caps('ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋꜱ:')} {total_tracks}\n\n"
                message += f"{get_emoji('track')} {to_small_caps('ᴛʀᴀᴄᴋ ʟɪꜱᴛ:')} (Page {page}/{max_pages})\n\n"
                
                # Add track list with numbers
                for i, track in enumerate(tracks, start=offset+1):
                    track_name = track.get('name', 'Unknown')
                    artist_name = track.get('artists', [{}])[0].get('name', 'Unknown')
                    
                    # Truncate long track names
                    if len(track_name) > 30:
                        track_name = track_name[:27] + "..."
                    
                    message += f"{i}. {track_name} - {artist_name}\n"
                
                # Create navigation buttons
                keyboard = []
                
                # Navigation buttons in first row
                nav_buttons = []
                if page > 1:
                    nav_buttons.append(InlineKeyboardButton(
                        f"◀️ {to_small_caps('ᴘʀᴇᴠ')}",
                        callback_data=f"view_spotify_playlist_{playlist_id}_{page-1}"
                    ))
                
                if page < max_pages:
                    nav_buttons.append(InlineKeyboardButton(
                        f"{to_small_caps('ɴᴇxᴛ')} ▶️",
                        callback_data=f"view_spotify_playlist_{playlist_id}_{page+1}"
                    ))
                
                if nav_buttons:
                    keyboard.append(nav_buttons)
                
                # Check if user is premium
                user_data = users_collection.find_one({"user_id": user.id})
                is_premium = user_data and user_data.get("is_premium", False)
                
                # Download buttons
                if is_premium:
                    # Full playlist download button for premium users (redirect to quality selection)
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅ ᴀʟʟ')}",
                            callback_data=f"quality_spotify_playlist_{playlist_id}"
                        )
                    ])
                else:
                    # Premium promo button for non-premium users
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ ꜰᴏʀ ꜰᴜʟʟ ᴘʟᴀʏʟɪꜱᴛ')}",
                            callback_data="premium_info"
                        )
                    ])
                
                # Add buttons to download individual tracks from the current page
                for i, track in enumerate(tracks, start=offset+1):
                    track_id = track.get('id', '')
                    track_name = track.get('name', 'Unknown')
                    artist_name = track.get('artists', [{}])[0].get('name', 'Unknown')
                    
                    # Truncate long track names
                    display_name = f"{track_name} - {artist_name}"
                    if len(display_name) > 25:
                        display_name = display_name[:22] + "..."
                        
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{i}. {display_name}",
                            callback_data=f"dl_track_{track_id}_128"
                        )
                    ])
                
                # Back button
                keyboard.append([
                    InlineKeyboardButton(
                        f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}",
                        callback_data="back_to_start"
                    )
                ])
                
                # Show the playlist
                await status_msg.edit_text(
                    message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
            except Exception as e:
                logger.error(f"Error loading Spotify playlist: {e}")
                await status_msg.edit_text(
                    f"{get_emoji('error')} {to_small_caps('ᴇʀʀᴏʀ ʟᴏᴀᴅɪɴɢ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n{str(e)[:100]}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                            callback_data="back_to_start")]
                    ])
                )
            
            return
            
        # YouTube playlist browsing handler
        elif query.data.startswith("yt_playlist_page_"):
            # Handle YouTube playlist pagination
            # Import asyncio for use in this function
            import asyncio
            
            parts = query.data.split("_")
            playlist_id = parts[3]
            page = int(parts[4]) if len(parts) > 4 else 1
            
            # Send a processing message
            status_msg = await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"{get_emoji('wait')} {to_small_caps('ʟᴏᴀᴅɪɴɢ ᴘʟᴀʏʟɪꜱᴛ ᴘᴀɢᴇ {page}...')}"
            )
            
            try:
                # Setup YouTube-DL to extract playlist info
                ydl_opts = {
                    'quiet': True,
                    'noplaylist': False,
                    'extract_flat': True,
                    'skip_download': True,
                    'cookiefile': 'cookies.txt'
                }
                
                youtube_url = f"https://www.youtube.com/playlist?list={format_youtube_playlist_id(playlist_id)}"
                
                # Extract playlist info
                with YoutubeDL(ydl_opts) as ydl:
                    playlist_info = ydl.extract_info(youtube_url, download=False)
                    
                if not playlist_info or not playlist_info.get('entries'):
                    await status_msg.edit_text(
                        f"{get_emoji('error')} {to_small_caps('ᴄᴏᴜʟᴅ ɴᴏᴛ ꜰɪɴᴅ ᴘʟᴀʏʟɪꜱᴛ ᴏʀ ᴘʟᴀʏʟɪꜱᴛ ɪꜱ ᴇᴍᴘᴛʏ.')}"
                    )
                    return
                
                # Get playlist details
                playlist_title = playlist_info.get('title', 'Unknown Playlist')
                playlist_entries = playlist_info.get('entries', [])
                total_tracks = len(playlist_entries)
                
                # Display the requested page of tracks
                items_per_page = 10
                max_pages = (total_tracks + items_per_page - 1) // items_per_page
                
                # Validate page number
                if page < 1:
                    page = 1
                elif page > max_pages:
                    page = max_pages
                
                start_idx = (page - 1) * items_per_page
                end_idx = min(start_idx + items_per_page, total_tracks)
                current_entries = playlist_entries[start_idx:end_idx]
                
                # Build message with track list
                message = f"{get_emoji('playlist')} {to_small_caps('ʏᴏᴜᴛᴜʙᴇ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n"
                message += f"{to_small_caps('ᴛɪᴛʟᴇ:')} {playlist_title}\n"
                message += f"{to_small_caps('ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋꜱ:')} {total_tracks}\n\n"
                message += f"{get_emoji('track')} {to_small_caps('ᴛʀᴀᴄᴋ ʟɪꜱᴛ:')} (Page {page}/{max_pages})\n\n"
                
                # Add track list
                for i, entry in enumerate(current_entries, start=start_idx+1):
                    title = entry.get('title', 'Unknown')
                    if len(title) > 40:
                        title = title[:37] + "..."
                    message += f"{i}. {title}\n"
                
                # Create navigation buttons
                keyboard = []
                
                # Navigation buttons in first row
                nav_buttons = []
                if page > 1:
                    nav_buttons.append(InlineKeyboardButton(
                        f"◀️ {to_small_caps('ᴘʀᴇᴠ')}",
                        callback_data=f"yt_playlist_page_{playlist_id}_{page-1}"
                    ))
                
                if page < max_pages:
                    nav_buttons.append(InlineKeyboardButton(
                        f"{to_small_caps('ɴᴇxᴛ')} ▶️",
                        callback_data=f"yt_playlist_page_{playlist_id}_{page+1}"
                    ))
                
                if nav_buttons:
                    keyboard.append(nav_buttons)
                
                # Check user's premium status
                user_data = users_collection.find_one({"user_id": user.id})
                is_premium = user_data and user_data.get("is_premium", False)
                
                # Download buttons
                if is_premium:
                    # Full playlist download button for premium users
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅ ᴀʟʟ')}",
                            callback_data=f"dl_yt_playlist_{playlist_id}_all"
                        )
                    ])
                else:
                    # Premium promo button for non-premium users
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ ꜰᴏʀ ꜰᴜʟʟ ᴘʟᴀʏʟɪꜱᴛ')}",
                            callback_data="premium_info"
                        )
                    ])
                
                # Add buttons to download individual tracks from the current page
                for i, entry in enumerate(current_entries, start=start_idx+1):
                    entry_id = entry.get('id', '')
                    title = entry.get('title', 'Unknown')
                    if len(title) > 20:
                        title = title[:17] + "..."
                        
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{i}. {title}",
                            callback_data=f"dl_yt_{entry_id}_128"
                        )
                    ])
                
                # Back button
                keyboard.append([
                    InlineKeyboardButton(
                        f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}",
                        callback_data="back_to_start"
                    )
                ])
                
                # Show the playlist
                await status_msg.edit_text(
                    message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
            except Exception as e:
                logger.error(f"Error loading YouTube playlist page: {e}")
                await status_msg.edit_text(
                    f"{get_emoji('error')} {to_small_caps('ᴇʀʀᴏʀ ʟᴏᴀᴅɪɴɢ ᴘʟᴀʏʟɪꜱᴛ ᴘᴀɢᴇ:')}\n\n{str(e)[:100]}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                            callback_data="back_to_start")]
                    ])
                )
            
            return
            
        # Handle Spotify playlist download
        elif query.data.startswith("dl_spotify_playlist_"):
            # Extract playlist ID
            parts = query.data.split("_")
            playlist_id = parts[3]
            user_id = query.from_user.id
            
            # Check if user is premium (only premium users can download full playlists)
            user_data = users_collection.find_one({"user_id": user_id})
            is_premium = user_data and user_data.get("is_premium", False)
            
            if not is_premium:
                premium_text = f"{get_emoji('premium')} {to_small_caps('ꜱᴘᴏᴛɪꜰʏ ᴘʟᴀʏʟɪꜱᴛ ᴅᴏᴡɴʟᴏᴀᴅꜱ ᴀʀᴇ ꜰᴏʀ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ ᴏɴʟʏ!')}"
                
                # Create premium info buttons
                keyboard = [
                    [InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ')}", 
                                         callback_data="premium_info")],
                    [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                         callback_data="back_to_start")]
                ]
                
                await query.edit_message_text(
                    premium_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
            
            # For premium users, start the download processing
            await query.edit_message_text(
                f"{get_emoji('wait')} {to_small_caps('ᴘʀᴇᴘᴀʀɪɴɢ ᴘʟᴀʏʟɪꜱᴛ ᴅᴏᴡɴʟᴏᴀᴅ...')}"
            )
            
            try:
                # Get playlist tracks from Spotify API
                results = spotify.playlist_items(
                    playlist_id,
                    fields='items(track(id,name,artists,album(name))),total'
                )
                
                total_tracks = results.get('total', 0)
                tracks = [item.get('track') for item in results.get('items', []) if item.get('track')]
                
                if not tracks:
                    await query.edit_message_text(
                        f"{get_emoji('error')} {to_small_caps('ᴘʟᴀʏʟɪꜱᴛ ɪꜱ ᴇᴍᴘᴛʏ ᴏʀ ɴᴏ ᴛʀᴀᴄᴋꜱ ᴄᴏᴜʟᴅ ʙᴇ ꜰᴏᴜɴᴅ.')}"
                    )
                    return
                
                # For large playlists, show a confirmation message
                if len(tracks) > 50:
                    # Ask for confirmation before proceeding with large playlists
                    await query.edit_message_text(
                        f"{get_emoji('info')} {to_small_caps('ᴛʜɪꜱ ɪꜱ ᴀ ʟᴀʀɢᴇ ᴘʟᴀʏʟɪꜱᴛ ᴡɪᴛʜ')} {len(tracks)} {to_small_caps('ᴛʀᴀᴄᴋꜱ.')}\n\n"
                        f"{to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴍᴀʏ ᴛᴀᴋᴇ ꜱᴏᴍᴇ ᴛɪᴍᴇ. ᴅᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ?')}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                f"{get_emoji('download')} {to_small_caps('ʏᴇꜱ, ᴅᴏᴡɴʟᴏᴀᴅ ᴀʟʟ ᴛʀᴀᴄᴋꜱ')}",
                                callback_data=f"dl_spotify_all_{playlist_id}_confirmed"
                            )],
                            [InlineKeyboardButton(
                                f"{get_emoji('track')} {to_small_caps('ʙʀᴏᴡꜱᴇ ᴛʀᴀᴄᴋꜱ ɪɴꜱᴛᴇᴀᴅ')}",
                                callback_data=f"view_spotify_playlist_{playlist_id}_1"
                            )],
                            [InlineKeyboardButton(
                                f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}",
                                callback_data="back_to_start"
                            )]
                        ])
                    )
                    return
                
                # For playlists, prepare to download all tracks
                max_tracks = len(tracks)
                download_entries = tracks[:max_tracks]
                tracks_info = []
                playlist_name = "Unknown"
                
                # Try to get the playlist name
                try:
                    playlist_info = spotify.playlist(playlist_id)
                    playlist_name = playlist_info['name']
                except Exception as e:
                    logger.error(f"Error getting playlist name: {e}")
                
                # Ask the user if they want to download individual tracks or the entire playlist
                download_msg = f"{get_emoji('playlist')} {to_small_caps('ꜱᴘᴏᴛɪꜰʏ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n"
                download_msg += f"{to_small_caps('ɴᴀᴍᴇ:')} {playlist_name}\n"
                download_msg += f"{to_small_caps('ᴛʀᴀᴄᴋꜱ:')} {len(tracks)}\n\n"
                
                if len(tracks) > 50:
                    download_msg += f"{get_emoji('info')} {to_small_caps('ᴛʜɪꜱ ɪꜱ ᴀ ʟᴀʀɢᴇ ᴘʟᴀʏʟɪꜱᴛ. ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴀʟʟ ꜱᴏɴɢꜱ ᴍᴀʏ ᴛᴀᴋᴇ ꜱᴏᴍᴇ ᴛɪᴍᴇ.')}\n\n"
                
                download_msg += f"{get_emoji('question')} {to_small_caps('ʜᴏᴡ ᴅᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ?')}"
                
                # Create keyboard with download options
                keyboard = [
                    [InlineKeyboardButton(
                        f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅ ᴀʟʟ ᴀᴛ ᴏɴᴄᴇ')}",
                        callback_data=f"dl_spotify_all_{playlist_id}"
                    )],
                    [InlineKeyboardButton(
                        f"{get_emoji('track')} {to_small_caps('ꜱᴇʟᴇᴄᴛ ɪɴᴅɪᴠɪᴅᴜᴀʟ ᴛʀᴀᴄᴋꜱ')}",
                        callback_data=f"sp_show_tracks_{playlist_id}"
                    )],
                    [InlineKeyboardButton(
                        f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}",
                        callback_data="back_to_start"
                    )]
                ]
                
                # Update message with download options
                await query.edit_message_text(
                    download_msg,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # Log the playlist browse
                details = {
                    "action": "playlist_browsed",
                    "playlist_id": playlist_id,
                    "playlist_name": playlist_name,
                    "track_count": len(tracks),
                    "source": "spotify"
                }
                await log_activity(context, "browse", user_info, details)
                
            except Exception as e:
                logger.error(f"Error processing Spotify playlist: {e}")
                await query.edit_message_text(
                    f"{get_emoji('error')} {to_small_caps('ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ ᴡʜɪʟᴇ ᴘʀᴏᴄᴇꜱꜱɪɴɢ ᴛʜᴇ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n{str(e)[:100]}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                            callback_data="back_to_start")]
                    ])
                )
            
            return
        
        # Handle YouTube playlist download
        elif query.data.startswith("dl_yt_playlist_"):
            # Import asyncio within this function scope to ensure it's available
            import asyncio
            
            # Add debug logging
            logger.info(f"YouTube playlist download request: {query.data}")
            
            # Extract playlist ID and parameters
            parts = query.data.split("_")
            youtube_id = parts[3]
            user_id = query.from_user.id
            
            # Check for quality setting, confirmation status, and download option
            download_option = "all"
            quality = None
            is_confirmed = False
            
            logger.info(f"Parsed request parts: {parts}")
            
            # Parse additional parameters
            if len(parts) > 4:
                # Could be a quality setting (number), confirmation flag, or download option
                logger.info(f"Checking parameter at position 4: {parts[4]}")
                if parts[4] == "confirmed":
                    is_confirmed = True
                    logger.info("Found confirmed flag at position 4")
                elif parts[4].isdigit():
                    quality = int(parts[4])
                    logger.info(f"Found quality setting at position 4: {quality}")
                else:
                    download_option = parts[4]
                    logger.info(f"Found download option at position 4: {download_option}")
                    
            # Check for confirmation flag in position 5
            if len(parts) > 5:
                logger.info(f"Checking parameter at position 5: {parts[5]}")
                if parts[5] == "confirmed":
                    is_confirmed = True
                    logger.info("Found confirmed flag at position 5")
                elif parts[5].isdigit() and not quality:
                    quality = int(parts[5])
                    logger.info(f"Found quality setting at position 5: {quality}")
                    
            # If quality is still None, use premium or free quality based on user status
            user_data = users_collection.find_one({"user_id": user_id})
            is_premium = user_data and user_data.get("is_premium", False)
            
            if not quality:
                quality = PREMIUM_BITRATE if is_premium else FREE_BITRATE
            
            # Check if user is premium (only premium users can download playlists)
            user_data = users_collection.find_one({"user_id": user_id})
            is_premium = user_data and user_data.get("is_premium", False)
            
            if not is_premium:
                premium_text = f"{get_emoji('premium')} {to_small_caps('ʏᴏᴜᴛᴜʙᴇ ᴘʟᴀʏʟɪꜱᴛ ᴅᴏᴡɴʟᴏᴀᴅꜱ ᴀʀᴇ ꜰᴏʀ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ ᴏɴʟʏ!')}"
                
                keyboard = [
                    [InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ')}", 
                                         callback_data="premium_info")],
                    [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                         callback_data="back_to_start")]
                ]
                
                await query.edit_message_text(
                    premium_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
            
            # For premium users, start the download processing
            progress_msg = await query.edit_message_text(
                f"{get_emoji('wait')} {to_small_caps('ᴘʀᴇᴘᴀʀɪɴɢ ᴘʟᴀʏʟɪꜱᴛ ᴅᴏᴡɴʟᴏᴀᴅ...')}"
            )
            
            try:
                # Setup YouTube-DL to extract playlist info
                ydl_opts = {
                    'quiet': True,
                    'noplaylist': False,
                    'extract_flat': True,
                    'skip_download': True,
                    'cookiefile': 'cookies.txt'
                }
                
                # Properly format the YouTube playlist ID
                full_youtube_id = format_youtube_playlist_id(youtube_id)
                
                # Add an option to skip authentication check for public playlists
                ydl_opts['extractor_args'] = {'youtubetab': {'skip': ['authcheck']}}
                
                youtube_url = f"https://www.youtube.com/playlist?list={full_youtube_id}"
                
                # Extract playlist info
                with YoutubeDL(ydl_opts) as ydl:
                    playlist_info = ydl.extract_info(youtube_url, download=False)
                
                if not playlist_info or not playlist_info.get('entries'):
                    await progress_msg.edit_text(
                        f"{get_emoji('error')} {to_small_caps('ᴄᴏᴜʟᴅ ɴᴏᴛ ꜰɪɴᴅ ᴘʟᴀʏʟɪꜱᴛ ᴏʀ ᴘʟᴀʏʟɪꜱᴛ ɪꜱ ᴇᴍᴘᴛʏ.')}"
                    )
                    return
                
                # Get playlist details
                playlist_title = playlist_info.get('title', 'Unknown Playlist')
                playlist_entries = playlist_info.get('entries', [])
                total_tracks = len(playlist_entries)
                
                # For large playlists, show a confirmation message if not already confirmed
                logger.info(f"Confirmation check - total_tracks: {total_tracks}, is_confirmed: {is_confirmed}")
                if total_tracks > 50 and not is_confirmed:
                    # Estimate download time (assume ~30 seconds per track)
                    est_minutes = (total_tracks * 30) // 60
                    est_time_msg = f"{est_minutes} {to_small_caps('ᴍɪɴᴜᴛᴇꜱ')}" if est_minutes > 0 else f"{total_tracks * 30} {to_small_caps('ꜱᴇᴄᴏɴᴅꜱ')}"
                    
                    await progress_msg.edit_text(
                        f"{get_emoji('info')} {to_small_caps('ᴛʜɪꜱ ɪꜱ ᴀ ʟᴀʀɢᴇ ᴘʟᴀʏʟɪꜱᴛ ᴡɪᴛʜ')} {total_tracks} {to_small_caps('ᴛʀᴀᴄᴋꜱ.')}\n\n"
                        f"{to_small_caps('ᴇꜱᴛɪᴍᴀᴛᴇᴅ ᴅᴏᴡɴʟᴏᴀᴅ ᴛɪᴍᴇ:')} {est_time_msg}\n"
                        f"{to_small_caps('ᴅᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ?')}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                f"{get_emoji('download')} {to_small_caps('ʏᴇꜱ, ᴅᴏᴡɴʟᴏᴀᴅ ᴀʟʟ ᴛʀᴀᴄᴋꜱ')}",
                                callback_data=f"dl_yt_playlist_{youtube_id}_{quality}_confirmed"
                            )],
                            [InlineKeyboardButton(
                                f"{get_emoji('track')} {to_small_caps('ʙʀᴏᴡꜱᴇ ᴛʀᴀᴄᴋꜱ ɪɴꜱᴛᴇᴀᴅ')}",
                                callback_data=f"yt_browse_page_{youtube_id}_1"
                            )],
                            [InlineKeyboardButton(
                                f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}",
                                callback_data="back_to_start"
                            )]
                        ])
                    )
                    return
                
                # Get all tracks for download
                download_entries = playlist_entries
                max_tracks = total_tracks
                
                # For very large playlists (>100), show an additional notice
                if total_tracks > 100:
                    # Estimate download time (assume ~30 seconds per track)
                    est_minutes = (total_tracks * 30) // 60
                    est_hours = est_minutes // 60
                    est_min_remainder = est_minutes % 60
                    
                    if est_hours > 0:
                        est_time_msg = f"{est_hours} {to_small_caps('ʜᴏᴜʀꜱ')} {est_min_remainder} {to_small_caps('ᴍɪɴᴜᴛᴇꜱ')}"
                    else:
                        est_time_msg = f"{est_minutes} {to_small_caps('ᴍɪɴᴜᴛᴇꜱ')}"
                    
                    await progress_msg.edit_text(
                        f"{get_emoji('info')} {to_small_caps('ᴛʜɪꜱ ɪꜱ ᴀ ᴠᴇʀʏ ʟᴀʀɢᴇ ᴘʟᴀʏʟɪꜱᴛ.')}\n\n"
                        f"{to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ')} {total_tracks} {to_small_caps('ᴛʀᴀᴄᴋꜱ ᴡɪʟʟ ᴛᴀᴋᴇ ᴀᴘᴘʀᴏxɪᴍᴀᴛᴇʟʏ')} {est_time_msg}.\n"
                        f"{to_small_caps('ᴘʟᴇᴀꜱᴇ ʙᴇ ᴘᴀᴛɪᴇɴᴛ ᴅᴜʀɪɴɢ ᴛʜᴇ ᴅᴏᴡɴʟᴏᴀᴅ ᴘʀᴏᴄᴇꜱꜱ.')}"
                    )
                    
                    # Give user time to read the message before starting downloads
                    await asyncio.sleep(3)
                
                # Update message with download information
                await progress_msg.edit_text(
                    f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n"
                    f"{to_small_caps('ɴᴀᴍᴇ:')} {playlist_title}\n"
                    f"{to_small_caps('ᴛʀᴀᴄᴋꜱ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ:')} {len(download_entries)}\n\n"
                    f"{get_emoji('wait')} {to_small_caps('ᴘʀᴇᴘᴀʀɪɴɢ ᴅᴏᴡɴʟᴏᴀᴅ...')}\n"
                    f"[                    ] 0/{len(download_entries)}"
                )
                
                # Make sure temp directory exists
                os.makedirs('temp', exist_ok=True)
                
                # Setup for quality based on user's premium status
                # Use the quality from the button click or set default if not specified
                if not quality:
                    quality = PREMIUM_BITRATE if is_premium else FREE_BITRATE
                
                # Process each track in the playlist
                successful_downloads = 0
                failed_downloads = 0
                download_results = []
                
                # Base yt-dlp options
                base_ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': 'temp/%(title)s.%(ext)s',
                    'quiet': True,
                    'noplaylist': True,
                    'cookiefile': 'cookies.txt',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': str(quality),
                    }],
                }
                
                # For each track in the playlist
                for i, entry in enumerate(download_entries, start=1):
                    entry_id = entry.get('id', '')
                    title = entry.get('title', 'Unknown')
                    
                    # Update progress message
                    progress_bar = "■" * int((i-1) * 20 / len(download_entries))
                    progress_bar += "□" * (20 - int((i-1) * 20 / len(download_entries)))
                    
                    # Calculate remaining time based on average of 30 seconds per track
                    remaining_tracks = len(download_entries) - (i-1)
                    est_seconds_remaining = remaining_tracks * 30
                    
                    # Format remaining time
                    if est_seconds_remaining > 3600:
                        hours = est_seconds_remaining // 3600
                        minutes = (est_seconds_remaining % 3600) // 60
                        est_time_left = f"{hours}h {minutes}m"
                    elif est_seconds_remaining > 60:
                        minutes = est_seconds_remaining // 60
                        est_time_left = f"{minutes}m"
                    else:
                        est_time_left = f"{est_seconds_remaining}s"
                    
                    await progress_msg.edit_text(
                        f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n"
                        f"{to_small_caps('ɴᴀᴍᴇ:')} {playlist_title}\n"
                        f"{to_small_caps('ᴘʀᴏɢʀᴇꜱꜱ:')} {i-1}/{len(download_entries)} • {to_small_caps('ᴇꜱᴛ. ᴛɪᴍᴇ ʟᴇꜰᴛ:')} {est_time_left}\n\n"
                        f"{get_emoji('wait')} {to_small_caps('ᴄᴜʀʀᴇɴᴛʟʏ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ:')}\n"
                        f"{title[:40] + '...' if len(title) > 40 else title}\n\n"
                        f"[{progress_bar}]"
                    )
                    
                    # Skip empty entries
                    if not entry_id:
                        failed_downloads += 1
                        download_results.append({
                            "title": title,
                            "status": "failed",
                            "error": "Missing video ID"
                        })
                        continue
                    
                    # Construct YouTube video URL
                    youtube_video_url = f"https://www.youtube.com/watch?v={entry_id}"
                    
                    try:
                        # Download this video's audio
                        with YoutubeDL(base_ydl_opts) as ydl:
                            info = ydl.extract_info(youtube_video_url, download=True)
                        
                        # Find the downloaded file
                        downloaded_file = None
                        for file in os.listdir('temp'):
                            if file.endswith('.mp3'):
                                downloaded_file = os.path.join('temp', file)
                                break
                        
                        if not downloaded_file:
                            raise FileNotFoundError("Could not find the downloaded audio file")
                        
                        # Extract metadata
                        title = info.get('title', 'Unknown')
                        artist = info.get('uploader', 'Unknown')
                        duration = info.get('duration', 0)
                        file_size = os.path.getsize(downloaded_file)
                        
                        # Prepare caption
                        caption = f"{get_emoji('track')} {to_small_caps('ᴛʀᴀᴄᴋ')} {i}/{len(download_entries)}:\n\n"
                        caption += f"{to_small_caps('ᴛɪᴛʟᴇ:')} {title}\n"
                        caption += f"{to_small_caps('ᴄʜᴀɴɴᴇʟ:')} {artist}\n"
                        caption += f"{to_small_caps('ǫᴜᴀʟɪᴛʏ:')} {quality}kbps\n"
                        caption += f"{to_small_caps('ꜱɪᴢᴇ:')} {file_size / (1024*1024):.2f} MB"
                        
                        # Send the audio file
                        with open(downloaded_file, 'rb') as audio:
                            sent_message = await context.bot.send_audio(
                                chat_id=query.message.chat_id,
                                audio=audio,
                                title=title,
                                performer=artist,
                                duration=duration,
                                caption=caption
                            )
                        
                        # Track successful download
                        successful_downloads += 1
                        download_results.append({
                            "title": title,
                            "status": "success",
                            "file_id": sent_message.audio.file_id,
                            "file_size": file_size
                        })
                        
                        # Update download counters in database
                        if user_data:
                            users_collection.update_one(
                                {"user_id": user_id},
                                {"$inc": {"downloads_today": 1, "total_downloads": 1},
                                "$set": {"last_download_date": datetime.now()}}
                            )
                            
                        # Log successful download
                        details = {
                            "action": "download_completed",
                            "youtube_id": entry_id,
                            "track_name": title,
                            "artist": artist,
                            "quality": quality,
                            "file_size_mb": file_size / (1024*1024),
                            "source": "youtube_playlist",
                            "playlist_id": youtube_id,
                            "track_position": i
                        }
                        await log_activity(context, "download", user_info, details)
                        
                        # Clean up the temporary file
                        try:
                            os.remove(downloaded_file)
                        except Exception as e:
                            logger.error(f"Failed to clean up temp file: {e}")
                            
                    except Exception as e:
                        logger.error(f"Error downloading track {entry_id}: {e}")
                        failed_downloads += 1
                        download_results.append({
                            "title": title,
                            "status": "failed",
                            "error": str(e)[:100]
                        })
                        
                        # Send error message for this track
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text=f"{get_emoji('error')} {to_small_caps('ᴇʀʀᴏʀ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴛʀᴀᴄᴋ:')} {title}\n\n{str(e)[:100]}"
                        )
                
                # Update progress message with final summary
                progress_bar = "■" * 20  # Full bar
                
                summary = f"{get_emoji('success')} {to_small_caps('ᴘʟᴀʏʟɪꜱᴛ ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ:')}\n\n"
                summary += f"{to_small_caps('ɴᴀᴍᴇ:')} {playlist_title}\n"
                summary += f"{to_small_caps('ᴛʀᴀᴄᴋꜱ ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ:')} {successful_downloads}/{len(download_entries)}\n"
                
                if failed_downloads > 0:
                    summary += f"{to_small_caps('ꜰᴀɪʟᴇᴅ ᴅᴏᴡɴʟᴏᴀᴅꜱ:')} {failed_downloads}\n"
                
                summary += f"\n[{progress_bar}]"
                
                # Create return to menu button
                keyboard = [
                    [InlineKeyboardButton(f"{get_emoji('playlist')} {to_small_caps('ʙʀᴏᴡꜱᴇ ᴍᴏʀᴇ ᴘʟᴀʏʟɪꜱᴛꜱ')}", 
                                         callback_data="back_to_start")]
                ]
                
                await progress_msg.edit_text(
                    summary,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # Log the playlist download completion
                details = {
                    "action": "playlist_download_completed",
                    "playlist_id": youtube_id,
                    "playlist_name": playlist_title,
                    "total_tracks": len(download_entries),
                    "successful_downloads": successful_downloads,
                    "failed_downloads": failed_downloads,
                    "source": "youtube"
                }
                await log_activity(context, "download", user_info, details)
                
            except Exception as e:
                logger.error(f"Error processing YouTube playlist: {e}")
                await progress_msg.edit_text(
                    f"{get_emoji('error')} {to_small_caps('ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ ᴡʜɪʟᴇ ᴘʀᴏᴄᴇꜱꜱɪɴɢ ᴛʜᴇ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n{str(e)[:100]}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                            callback_data="back_to_start")]
                    ])
                )
                
                # Log the error
                error_details = {
                    "action": "playlist_download_failed",
                    "playlist_id": youtube_id,
                    "error": str(e),
                    "source": "youtube"
                }
                await log_activity(context, "error", user_info, error_details, level="ERROR")
            
            return
            
        elif query.data.startswith("yt_browse_page_"):
            # Import asyncio for use in this function
            import asyncio
            parts = query.data.split("_")
            playlist_id = parts[3]
            page = int(parts[4]) if len(parts) > 4 else 1
            
            # Send a processing message
            status_msg = await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"{get_emoji('wait')} {to_small_caps('ʟᴏᴀᴅɪɴɢ ᴘʟᴀʏʟɪꜱᴛ ᴘᴀɢᴇ {page}...')}"
            )
            
            try:
                # Setup YouTube-DL to extract playlist info
                ydl_opts = {
                    'quiet': True,
                    'noplaylist': False,
                    'extract_flat': True,
                    'skip_download': True,
                    'cookiefile': 'cookies.txt'
                }
                
                youtube_url = f"https://www.youtube.com/playlist?list={format_youtube_playlist_id(playlist_id)}"
                
                # Extract playlist info
                with YoutubeDL(ydl_opts) as ydl:
                    playlist_info = ydl.extract_info(youtube_url, download=False)
                    
                if not playlist_info or not playlist_info.get('entries'):
                    await status_msg.edit_text(
                        f"{get_emoji('error')} {to_small_caps('ᴄᴏᴜʟᴅ ɴᴏᴛ ꜰɪɴᴅ ᴘʟᴀʏʟɪꜱᴛ ᴏʀ ᴘʟᴀʏʟɪꜱᴛ ɪꜱ ᴇᴍᴘᴛʏ.')}"
                    )
                    return
                
                # Get playlist details
                playlist_title = playlist_info.get('title', 'Unknown Playlist')
                playlist_entries = playlist_info.get('entries', [])
                total_tracks = len(playlist_entries)
                
                # Display the requested page of tracks
                items_per_page = 10
                max_pages = (total_tracks + items_per_page - 1) // items_per_page
                
                # Validate page number
                if page < 1:
                    page = 1
                elif page > max_pages:
                    page = max_pages
                
                start_idx = (page - 1) * items_per_page
                end_idx = min(start_idx + items_per_page, total_tracks)
                current_entries = playlist_entries[start_idx:end_idx]
                
                # Build message with track list
                message = f"{get_emoji('playlist')} {to_small_caps('ʏᴏᴜᴛᴜʙᴇ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n"
                message += f"{to_small_caps('ᴛɪᴛʟᴇ:')} {playlist_title}\n"
                message += f"{to_small_caps('ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋꜱ:')} {total_tracks}\n\n"
                message += f"{get_emoji('track')} {to_small_caps('ᴛʀᴀᴄᴋ ʟɪꜱᴛ:')} (Page {page}/{max_pages})\n\n"
                
                # Add track list
                for i, entry in enumerate(current_entries, start=start_idx+1):
                    title = entry.get('title', 'Unknown')
                    if len(title) > 40:
                        title = title[:37] + "..."
                    message += f"{i}. {title}\n"
                
                # Create navigation buttons
                keyboard = []
                
                # Navigation buttons in first row
                nav_buttons = []
                if page > 1:
                    nav_buttons.append(InlineKeyboardButton(
                        f"◀️ {to_small_caps('ᴘʀᴇᴠ')}",
                        callback_data=f"yt_playlist_page_{playlist_id}_{page-1}"
                    ))
                
                if page < max_pages:
                    nav_buttons.append(InlineKeyboardButton(
                        f"{to_small_caps('ɴᴇxᴛ')} ▶️",
                        callback_data=f"yt_playlist_page_{playlist_id}_{page+1}"
                    ))
                
                if nav_buttons:
                    keyboard.append(nav_buttons)
                
                # Check user's premium status
                user_data = users_collection.find_one({"user_id": user.id})
                is_premium = user_data and user_data.get("is_premium", False)
                
                # Download buttons
                if is_premium:
                    # Full playlist download button for premium users
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅ ᴀʟʟ')}",
                            callback_data=f"dl_yt_playlist_{playlist_id}_all"
                        )
                    ])
                else:
                    # Premium promo button for non-premium users
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ ꜰᴏʀ ꜰᴜʟʟ ᴘʟᴀʏʟɪꜱᴛ')}",
                            callback_data="premium_info"
                        )
                    ])
                
                # Add buttons to download individual tracks from the current page
                for i, entry in enumerate(current_entries, start=start_idx+1):
                    entry_id = entry.get('id', '')
                    title = entry.get('title', 'Unknown')
                    if len(title) > 20:
                        title = title[:17] + "..."
                        
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{i}. {title}",
                            callback_data=f"dl_yt_{entry_id}_128"
                        )
                    ])
                
                # Back button
                keyboard.append([
                    InlineKeyboardButton(
                        f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}",
                        callback_data="back_to_start"
                    )
                ])
                
                # Show the playlist
                await status_msg.edit_text(
                    message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
            except Exception as e:
                logger.error(f"Error loading YouTube playlist page: {e}")
                await status_msg.edit_text(
                    f"{get_emoji('error')} {to_small_caps('ᴇʀʀᴏʀ ʟᴏᴀᴅɪɴɢ ᴘʟᴀʏʟɪꜱᴛ ᴘᴀɢᴇ:')}\n\n{str(e)[:100]}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                            callback_data="back_to_start")]
                    ])
                )
            
            return
            
        elif query.data.startswith("view_yt_playlist_"):
            # Extract YouTube playlist ID
            playlist_id = query.data.split("_")[3]
            # Show a message that this feature is coming soon
            await query.edit_message_text(
                f"{get_emoji('info')} {to_small_caps('ʏᴏᴜᴛᴜʙᴇ ᴘʟᴀʏʟɪꜱᴛ ʙʀᴏᴡꜱɪɴɢ ɪꜱ ᴄᴏᴍɪɴɢ ꜱᴏᴏɴ!')}\n\n"
                f"{to_small_caps('ꜰᴏʀ ɴᴏᴡ, ᴘʟᴇᴀꜱᴇ ᴜꜱᴇ ᴛʜᴇ ᴅᴏᴡɴʟᴏᴀᴅ ʙᴜᴛᴛᴏɴ ᴛᴏ ᴏʙᴛᴀɪɴ ᴛʜᴇ ᴇɴᴛɪʀᴇ ᴘʟᴀʏʟɪꜱᴛ.')}\n\n"
                f"{to_small_caps('ᴡᴇ ᴀʀᴇ ᴡᴏʀᴋɪɴɢ ᴏɴ ᴇɴʜᴀɴᴄɪɴɢ ᴛʜᴇꜱᴇ ꜰᴇᴀᴛᴜʀᴇꜱ!')}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", callback_data="back_to_start")]
                ])
            )
            
        elif query.data.startswith("view_album_"):
            await view_album_tracks(update, context)
        
        # Album info display handler
        elif query.data.startswith("album_info_"):
            album_id = query.data.split("_")[2]
            # This will re-fetch the album info and display it
            try:
                album_info = spotify.album(album_id)
                if not album_info:
                    await query.answer("Could not find album information")
                    return
                    
                # Format album info as in handle_spotify_link
                album_name = album_info['name']
                artist_name = album_info['artists'][0]['name']
                total_tracks = album_info['total_tracks']
                
                # Get album cover
                album_cover_url = None
                if album_info['images']:
                    album_cover_url = album_info['images'][0]['url']
                
                # Check if user is premium for album downloads
                user_data = users_collection.find_one({"user_id": user.id})
                is_premium = user_data and user_data.get("is_premium", False)
                
                response = f"{get_emoji('album')} {to_small_caps('ꜰᴏᴜɴᴅ ᴀʟʙᴜᴍ:')}\n\n"
                response += f"{to_small_caps('ᴀʀᴛɪꜱᴛ:')} {artist_name}\n"
                response += f"{to_small_caps('ᴀʟʙᴜᴍ:')} {album_name}\n"
                response += f"{to_small_caps('ᴛʀᴀᴄᴋꜱ:')} {total_tracks}"
                
                keyboard = []
                if is_premium:
                    keyboard.append([InlineKeyboardButton(f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅ ᴀʟʙᴜᴍ')}",
                                                 callback_data=f"dl_album_{album_id}")])
                else:
                    response += f"\n\n{get_emoji('premium')} {to_small_caps('ᴀʟʙᴜᴍ ᴅᴏᴡɴʟᴏᴀᴅꜱ ᴀʀᴇ ᴀᴠᴀɪʟᴀʙʟᴇ ᴛᴏ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ ᴏɴʟʏ')}"
                    keyboard.append([InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ')}",
                                                 callback_data="premium_info")])
                
                # Add a button to browse tracks individually
                keyboard.append([InlineKeyboardButton(f"{get_emoji('track')} {to_small_caps('ʙʀᴏᴡꜱᴇ ᴛʀᴀᴄᴋꜱ')}",
                                             callback_data=f"view_album_{album_id}")])
                                             
                # Add back to main menu button
                keyboard.append([InlineKeyboardButton(f"{get_emoji('home')} {to_small_caps('ᴍᴀɪɴ ᴍᴇɴᴜ')}", callback_data="back_to_start")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Edit message to show album info
                await query.edit_message_text(text=response, reply_markup=reply_markup)
                
            except Exception as e:
                logger.error(f"Error showing album info: {e}")
                await query.answer("An error occurred while loading album information")
        
        # Rating system handlers
        elif query.data == "rate_bot":
            await rate_bot_callback(update, context)
        
        elif query.data.startswith("rate_"):
            try:
                rating_parts = query.data.split("_")
                rating = int(rating_parts[1])
                
                # Log the rating
                details = {
                    "action": "bot_rated",
                    "rating": rating
                }
                await log_activity(context, "feedback", user_info, details)
                
                # Thank the user for rating
                thank_text = f"{get_emoji('success')} {to_small_caps('ᴛʜᴀɴᴋ ʏᴏᴜ ꜰᴏʀ ʏᴏᴜʀ ꜰᴇᴇᴅʙᴀᴄᴋ!')}\n\n"
                thank_text += f"{to_small_caps('ʏᴏᴜʀ ʀᴀᴛɪɴɢ:')} {'⭐' * rating}\n\n"
                thank_text += f"{to_small_caps('ᴡᴇ ᴀᴘᴘʀᴇᴄɪᴀᴛᴇ ʏᴏᴜʀ ꜰᴇᴇᴅʙᴀᴄᴋ ᴀɴᴅ ᴡɪʟʟ ᴄᴏɴᴛɪɴᴜᴇ ᴛᴏ ɪᴍᴘʀᴏᴠᴇ ᴛʜᴇ ʙᴏᴛ!')}"
                
                # Button to go back to main menu
                keyboard = [[InlineKeyboardButton(f"{get_emoji('home')} {to_small_caps('ᴍᴀɪɴ ᴍᴇɴᴜ')}", callback_data="back_to_start")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Send as a new message instead of editing the audio message
                await query.answer("Thank you for your rating!")
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=thank_text,
                    reply_markup=reply_markup
                )
                
            except Exception as e:
                logger.error(f"Error processing rating: {e}")
                await query.answer("An error occurred while processing your rating")
        
        elif query.data == "cancel_rating":
            # User cancelled rating
            keyboard = [[InlineKeyboardButton(f"{get_emoji('home')} {to_small_caps('ᴍᴀɪɴ ᴍᴇɴᴜ')}", callback_data="back_to_start")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            cancel_text = f"{get_emoji('info')} {to_small_caps('ʀᴀᴛɪɴɢ ᴄᴀɴᴄᴇʟʟᴇᴅ. ꜰᴇᴇʟ ꜰʀᴇᴇ ᴛᴏ ʀᴀᴛᴇ ᴛʜᴇ ʙᴏᴛ ᴀɴʏᴛɪᴍᴇ!')}"
            
            # Try to edit the message if possible, otherwise send a new one
            try:
                if has_message_text:
                    await query.edit_message_text(text=cancel_text, reply_markup=reply_markup)
                else:
                    await query.answer("Rating cancelled")
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=cancel_text,
                        reply_markup=reply_markup
                    )
            except Exception as e:
                logger.error(f"Error updating cancel rating message: {e}")
                # Fallback to sending a new message
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=cancel_text,
                    reply_markup=reply_markup
                )
        
        elif query.data == "premium_info":
            premium_text = f"{get_emoji('premium')} {to_small_caps('ᴘʀᴇᴍɪᴜᴍ ꜰᴇᴀᴛᴜʀᴇꜱ:')}\n\n"
            premium_text += f"✅ {to_small_caps('ᴜɴʟɪᴍɪᴛᴇᴅ ᴅᴏᴡɴʟᴏᴀᴅꜱ')}\n"
            premium_text += f"✅ {to_small_caps('ʜɪɢʜᴇʀ ǫᴜᴀʟɪᴛʏ')} ({PREMIUM_BITRATE}kbps)\n"
            premium_text += f"✅ {to_small_caps('ᴀʟʙᴜᴍ & ᴘʟᴀʏʟɪꜱᴛ ᴅᴏᴡɴʟᴏᴀᴅꜱ')}\n"
            premium_text += f"✅ {to_small_caps('ᴢɪᴘ ꜰɪʟᴇ ᴅᴏᴡɴʟᴏᴀᴅꜱ')}\n\n"
            premium_text += f"{get_emoji('info')} {to_small_caps('ᴄᴏɴᴛᴀᴄᴛ ᴛʜᴇ ʙᴏᴛ ᴀᴅᴍɪɴ ᴛᴏ ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ!')}"
            
            keyboard = [
                [InlineKeyboardButton(f"{get_emoji('premium')} Contact Admin", url="https://t.me/SpotifyDLBot_Admin")],
                [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", callback_data="back_to_start")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Edit message text if possible, otherwise send new message
            try:
                if has_message_text:
                    await query.edit_message_text(text=premium_text, reply_markup=reply_markup)
                else:
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=premium_text,
                        reply_markup=reply_markup
                    )
            except Exception as e:
                logger.error(f"Error updating premium info message: {e}")
                # Fallback to sending a new message
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=premium_text,
                    reply_markup=reply_markup
                )
            
            # Log premium info viewed
            details = {
                "action": "premium_info_viewed",
                "source": "button_click"
            }
            await log_activity(context, "premium", user_info, details)
        
        # Handle YouTube video download request
        elif query.data.startswith("dl_yt_"):
            # Extract YouTube ID and quality parameter
            parts = query.data.split("_")
            
            # Check if it's a playlist or single video
            if parts[1] == "playlist":
                # Handle playlist download
                youtube_id = parts[2]
                user_id = query.from_user.id
                user = query.from_user
                
                # Log the download request
                details = {
                    "action": "download_requested",
                    "youtube_id": youtube_id,
                    "track_type": "youtube_playlist",
                    "source": "youtube"
                }
                await log_activity(context, "download", user_info, details)
                
                # Check if user is premium (only premium users can download playlists)
                user_data = users_collection.find_one({"user_id": user_id})
                is_premium = user_data and user_data.get("is_premium", False)
                
                if not is_premium:
                    premium_text = f"{get_emoji('premium')} {to_small_caps('ʏᴏᴜᴛᴜʙᴇ ᴘʟᴀʏʟɪꜱᴛ ᴅᴏᴡɴʟᴏᴀᴅꜱ ᴀʀᴇ ꜰᴏʀ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ ᴏɴʟʏ!')}"
                    
                    await query.edit_message_text(
                        premium_text,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ')}", 
                                                 callback_data="premium_info")],
                            [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                                 callback_data="back_to_start")]
                        ])
                    )
                    return
                
                # Send a processing message
                status_msg = await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"{get_emoji('wait')} {to_small_caps('ʟᴏᴀᴅɪɴɢ ᴘʟᴀʏʟɪꜱᴛ... ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ.')}"
                )
                
                try:
                    # Setup YouTube-DL to extract playlist info
                    ydl_opts = {
                        'quiet': True,
                        'noplaylist': False,
                        'extract_flat': True,
                        'skip_download': True,
                        'cookiefile': 'cookies.txt'
                    }
                    
                    youtube_url = f"https://www.youtube.com/playlist?list={format_youtube_playlist_id(youtube_id)}"
                    
                    # Extract playlist info
                    with YoutubeDL(ydl_opts) as ydl:
                        playlist_info = ydl.extract_info(youtube_url, download=False)
                        
                    if not playlist_info or not playlist_info.get('entries'):
                        await status_msg.edit_text(
                            f"{get_emoji('error')} {to_small_caps('ᴄᴏᴜʟᴅ ɴᴏᴛ ꜰɪɴᴅ ᴘʟᴀʏʟɪꜱᴛ ᴏʀ ᴘʟᴀʏʟɪꜱᴛ ɪꜱ ᴇᴍᴘᴛʏ.')}"
                        )
                        return
                    
                    # Get playlist details
                    playlist_title = playlist_info.get('title', 'Unknown Playlist')
                    playlist_entries = playlist_info.get('entries', [])
                    total_tracks = len(playlist_entries)
                    
                    # Display first page of tracks (10 items per page)
                    page = 1
                    items_per_page = 10
                    max_pages = (total_tracks + items_per_page - 1) // items_per_page
                    
                    start_idx = (page - 1) * items_per_page
                    end_idx = min(start_idx + items_per_page, total_tracks)
                    current_entries = playlist_entries[start_idx:end_idx]
                    
                    # Build message with track list
                    message = f"{get_emoji('playlist')} {to_small_caps('ʏᴏᴜᴛᴜʙᴇ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n"
                    message += f"{to_small_caps('ᴛɪᴛʟᴇ:')} {playlist_title}\n"
                    message += f"{to_small_caps('ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋꜱ:')} {total_tracks}\n\n"
                    message += f"{get_emoji('track')} {to_small_caps('ᴛʀᴀᴄᴋ ʟɪꜱᴛ:')} (Page {page}/{max_pages})\n\n"
                    
                    # Add track list
                    for i, entry in enumerate(current_entries, start=start_idx+1):
                        title = entry.get('title', 'Unknown')
                        if len(title) > 40:
                            title = title[:37] + "..."
                        message += f"{i}. {title}\n"
                    
                    # Create navigation buttons
                    keyboard = []
                    
                    # Navigation buttons in first row
                    nav_buttons = []
                    if page > 1:
                        nav_buttons.append(InlineKeyboardButton(
                            f"◀️ {to_small_caps('ᴘʀᴇᴠ')}",
                            callback_data=f"yt_playlist_page_{youtube_id}_{page-1}"
                        ))
                    
                    if page < max_pages:
                        nav_buttons.append(InlineKeyboardButton(
                            f"{to_small_caps('ɴᴇxᴛ')} ▶️",
                            callback_data=f"yt_playlist_page_{youtube_id}_{page+1}"
                        ))
                    
                    if nav_buttons:
                        keyboard.append(nav_buttons)
                    
                    # Download buttons
                    if is_premium:
                        # Full playlist download button for premium users
                        keyboard.append([
                            InlineKeyboardButton(
                                f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅ ᴀʟʟ')}",
                                callback_data=f"dl_yt_playlist_{youtube_id}_all"
                            )
                        ])
                    else:
                        # Premium promo button for non-premium users
                        keyboard.append([
                            InlineKeyboardButton(
                                f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ ꜰᴏʀ ꜰᴜʟʟ ᴘʟᴀʏʟɪꜱᴛ')}",
                                callback_data="premium_info"
                            )
                        ])
                    
                    # Add buttons to download individual tracks from the current page
                    for i, entry in enumerate(current_entries, start=start_idx+1):
                        entry_id = entry.get('id', '')
                        title = entry.get('title', 'Unknown')
                        if len(title) > 20:
                            title = title[:17] + "..."
                            
                        keyboard.append([
                            InlineKeyboardButton(
                                f"{i}. {title}",
                                callback_data=f"dl_yt_{entry_id}_128"
                            )
                        ])
                    
                    # Back button
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}",
                            callback_data="back_to_start"
                        )
                    ])
                    
                    # Show the playlist
                    await status_msg.edit_text(
                        message,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    
                except Exception as e:
                    logger.error(f"Error loading YouTube playlist: {e}")
                    await status_msg.edit_text(
                        f"{get_emoji('error')} {to_small_caps('ᴇʀʀᴏʀ ʟᴏᴀᴅɪɴɢ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n{str(e)[:100]}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                                callback_data="back_to_start")]
                        ])
                    )
                
                return
            
            else:
                # Handle single video download
                youtube_id = parts[2]
                user_id = query.from_user.id
                user = query.from_user
                
                # Extract quality if specified
                quality = None
                if len(parts) >= 4:
                    try:
                        quality = int(parts[3])
                    except ValueError:
                        quality = 128  # Default quality
                
                # Always send a new message rather than editing to avoid type issues
                status_msg = await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"{get_emoji('wait')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ʏᴏᴜᴛᴜʙᴇ ᴀᴜᴅɪᴏ...')}"
                )
                
                # Log the download request
                details = {
                    "action": "download_requested",
                    "youtube_id": youtube_id,
                    "track_type": "youtube_video",
                    "requested_quality": quality,
                    "source": "youtube"
                }
                await log_activity(context, "download", user_info, details)
                
                # Check if user can download (free users have daily limits)
                user_data = users_collection.find_one({"user_id": user_id})
                if user_data:
                    is_premium = user_data.get("is_premium", False)
                    downloads_today = user_data.get("downloads_today", 0)
                    
                    # Check if free user has reached limit
                    if not is_premium and downloads_today >= FREE_DAILY_LIMIT:
                        premium_text = f"{get_emoji('error')} {to_small_caps('ʏᴏᴜ ʜᴀᴠᴇ ʀᴇᴀᴄʜᴇᴅ ʏᴏᴜʀ ᴅᴀɪʟʏ ᴅᴏᴡɴʟᴏᴀᴅ ʟɪᴍɪᴛ!')}\n\n"
                        premium_text += f"{get_emoji('premium')} {to_small_caps('ᴜᴘɢʀᴀᴅᴇ ᴛᴏ ᴘʀᴇᴍɪᴜᴍ ꜰᴏʀ ᴜɴʟɪᴍɪᴛᴇᴅ ᴅᴏᴡɴʟᴏᴀᴅꜱ!')}"
                        
                        keyboard = [
                            [InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ')}",
                                                callback_data="premium_info")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        await status_msg.edit_text(premium_text, reply_markup=reply_markup)
                        return
                
                # Process the YouTube download
                try:
                    # Setup YouTube-DL with appropriate quality options
                    ydl_opts = {
                        'format': 'bestaudio/best',
                        'outtmpl': 'temp/%(title)s.%(ext)s',
                        'quiet': True,
                        'noplaylist': True,
                        'cookiefile': 'cookies.txt',  # Use cookies to avoid restrictions
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': str(quality),
                        }],
                    }
                    
                    youtube_url = f"https://www.youtube.com/playlist?list={format_youtube_playlist_id(youtube_id)}"
                    
                    # Send a processing message
                    await status_msg.edit_text(f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴀᴜᴅɪᴏ... ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ.')}")
                    
                    # Make sure temp directory exists
                    os.makedirs('temp', exist_ok=True)
                    
                    # Download the audio
                    with YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(youtube_url, download=True)
                    
                    # Get downloaded file path and metadata
                    title = info.get('title', 'Unknown')
                    artist = info.get('uploader', 'Unknown')
                    duration = info.get('duration', 0)
                    
                    # Find the downloaded file
                    downloaded_file = None
                    for file in os.listdir('temp'):
                        if file.endswith('.mp3'):
                            downloaded_file = os.path.join('temp', file)
                            break
                    
                    if not downloaded_file:
                        raise FileNotFoundError("Could not find the downloaded audio file")
                    
                    # Update download counters in database
                    if user_data:
                        users_collection.update_one(
                            {"user_id": user_id},
                            {"$inc": {"downloads_today": 1, "total_downloads": 1},
                             "$set": {"last_download_date": datetime.now()}}
                        )
                    
                    # Get file size
                    file_size = os.path.getsize(downloaded_file)
                    
                    # Prepare caption
                    caption = f"{get_emoji('track')} {to_small_caps('ʏᴏᴜᴛᴜʙᴇ ᴀᴜᴅɪᴏ:')}\n\n"
                    caption += f"{to_small_caps('ᴛɪᴛʟᴇ:')} {title}\n"
                    caption += f"{to_small_caps('ᴄʜᴀɴɴᴇʟ:')} {artist}\n"
                    caption += f"{to_small_caps('ǫᴜᴀʟɪᴛʏ:')} {quality}kbps\n"
                    caption += f"{to_small_caps('ꜱɪᴢᴇ:')} {file_size / (1024*1024):.2f} MB"
                    
                    # Create inline keyboard with rating and menu buttons
                    keyboard = [
                        [InlineKeyboardButton(f"⭐ 1", callback_data=f"rate_1"),
                         InlineKeyboardButton(f"⭐ 2", callback_data=f"rate_2"),
                         InlineKeyboardButton(f"⭐ 3", callback_data=f"rate_3"),
                         InlineKeyboardButton(f"⭐ 4", callback_data=f"rate_4"),
                         InlineKeyboardButton(f"⭐ 5", callback_data=f"rate_5")],
                        [InlineKeyboardButton(f"{get_emoji('home')} {to_small_caps('ᴍᴀɪɴ ᴍᴇɴᴜ')}", callback_data="back_to_start")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    # Delete status message and send the file
                    await status_msg.delete()
                    
                    # Send the audio file
                    with open(downloaded_file, 'rb') as audio:
                        sent_message = await context.bot.send_audio(
                            chat_id=query.message.chat_id,
                            audio=audio,
                            title=title,
                            performer=artist,
                            duration=duration,
                            caption=caption,
                            reply_markup=reply_markup
                        )
                    
                    # Clean up the temporary file
                    try:
                        os.remove(downloaded_file)
                    except Exception as e:
                        logger.error(f"Failed to clean up temp file: {e}")
                    
                    # Log successful download
                    details = {
                        "action": "download_completed",
                        "youtube_id": youtube_id,
                        "track_name": title,
                        "artist": artist,
                        "quality": quality,
                        "file_size_mb": file_size / (1024*1024),
                        "source": "youtube"
                    }
                    await log_activity(context, "download", user_info, details)
                    
                except Exception as e:
                    logger.error(f"Error in YouTube download handler: {e}")
                    
                    # Show error message
                    error_message = f"{get_emoji('error')} {to_small_caps('ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ ᴡʜɪʟᴇ ᴘʀᴏᴄᴇꜱꜱɪɴɢ ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ:')}\n\n"
                    error_message += f"{str(e)[:100]}..." if len(str(e)) > 100 else str(e)
                    
                    # Add retry button
                    keyboard = [
                        [InlineKeyboardButton(f"{get_emoji('download')} {to_small_caps('ᴛʀʏ ᴀɢᴀɪɴ')}",
                                            callback_data=query.data)],
                        [InlineKeyboardButton(f"{get_emoji('home')} {to_small_caps('ᴍᴀɪɴ ᴍᴇɴᴜ')}",
                                            callback_data="back_to_start")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await status_msg.edit_text(error_message, reply_markup=reply_markup)
                    
                    # Log error details
                    error_details = {
                        "action": "download_failed",
                        "youtube_id": youtube_id,
                        "error": str(e),
                        "source": "youtube"
                    }
                    await log_activity(context, "error", user_info, error_details, level="ERROR")
        
        # Handle quality selection for YouTube playlist download
        elif query.data.startswith("quality_yt_playlist_"):
            parts = query.data.split("_")
            playlist_id = parts[3]
            user_id = query.from_user.id
            user_data = users_collection.find_one({"user_id": user_id})
            is_premium = user_data and user_data.get("is_premium", False)
            
            # Create quality selection keyboard
            keyboard = []
            
            # For premium users, offer all qualities
            if is_premium:
                keyboard = [
                    [InlineKeyboardButton(f"{get_emoji('high_quality')} {to_small_caps('ʜɪɢʜ ǫᴜᴀʟɪᴛʏ')} (320 ᴋʙᴘs)", 
                                         callback_data=f"dl_yt_playlist_{playlist_id}_320_confirmed")],
                    [InlineKeyboardButton(f"{get_emoji('medium_quality')} {to_small_caps('ᴍᴇᴅɪᴜᴍ ǫᴜᴀʟɪᴛʏ')} (256 ᴋʙᴘs)", 
                                         callback_data=f"dl_yt_playlist_{playlist_id}_256_confirmed")],
                    [InlineKeyboardButton(f"{get_emoji('low_quality')} {to_small_caps('ꜱᴛᴀɴᴅᴀʀᴅ ǫᴜᴀʟɪᴛʏ')} (128 ᴋʙᴘs)", 
                                         callback_data=f"dl_yt_playlist_{playlist_id}_128_confirmed")],
                    [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                         callback_data=f"yt_playlist_page_{playlist_id}_1")]
                ]
            else:
                # Free users only get lower qualities
                keyboard = [
                    [InlineKeyboardButton(f"{get_emoji('low_quality')} {to_small_caps('ꜱᴛᴀɴᴅᴀʀᴅ ǫᴜᴀʟɪᴛʏ')} (128 ᴋʙᴘs)", 
                                         callback_data=f"dl_yt_playlist_{playlist_id}_128_confirmed")],
                    [InlineKeyboardButton(f"{get_emoji('very_low_quality')} {to_small_caps('ʟᴏᴡ ǫᴜᴀʟɪᴛʏ')} (64 ᴋʙᴘs)", 
                                         callback_data=f"dl_yt_playlist_{playlist_id}_64_confirmed")],
                    [InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ ꜰᴏʀ ʜɪɢʜᴇʀ ǫᴜᴀʟɪᴛʏ')}", 
                                         callback_data="premium_info")],
                    [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                         callback_data=f"yt_playlist_page_{playlist_id}_1")]
                ]
            
            await query.edit_message_text(
                f"{get_emoji('quality')} {to_small_caps('ꜱᴇʟᴇᴄᴛ ᴀᴜᴅɪᴏ ǫᴜᴀʟɪᴛʏ ꜰᴏʀ ʏᴏᴜᴛᴜʙᴇ ᴘʟᴀʏʟɪꜱᴛ:')}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
            
        # Handle quality selection for Spotify playlist download
        elif query.data.startswith("quality_spotify_playlist_"):
            parts = query.data.split("_")
            playlist_id = parts[3]
            user_id = query.from_user.id
            user_data = users_collection.find_one({"user_id": user_id})
            is_premium = user_data and user_data.get("is_premium", False)
            
            # Create quality selection keyboard
            keyboard = []
            
            # For premium users, offer all qualities
            if is_premium:
                keyboard = [
                    [InlineKeyboardButton(f"{get_emoji('high_quality')} {to_small_caps('ʜɪɢʜ ǫᴜᴀʟɪᴛʏ')} (320 ᴋʙᴘs)", 
                                         callback_data=f"dl_spotify_all_{playlist_id}_320_confirmed")],
                    [InlineKeyboardButton(f"{get_emoji('medium_quality')} {to_small_caps('ᴍᴇᴅɪᴜᴍ ǫᴜᴀʟɪᴛʏ')} (256 ᴋʙᴘs)", 
                                         callback_data=f"dl_spotify_all_{playlist_id}_256_confirmed")],
                    [InlineKeyboardButton(f"{get_emoji('low_quality')} {to_small_caps('ꜱᴛᴀɴᴅᴀʀᴅ ǫᴜᴀʟɪᴛʏ')} (128 ᴋʙᴘs)", 
                                         callback_data=f"dl_spotify_all_{playlist_id}_128_confirmed")],
                    [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                         callback_data=f"view_spotify_playlist_{playlist_id}_1")]
                ]
            else:
                # Free users only get lower qualities
                keyboard = [
                    [InlineKeyboardButton(f"{get_emoji('low_quality')} {to_small_caps('ꜱᴛᴀɴᴅᴀʀᴅ ǫᴜᴀʟɪᴛʏ')} (128 ᴋʙᴘs)", 
                                         callback_data=f"dl_spotify_all_{playlist_id}_128_confirmed")],
                    [InlineKeyboardButton(f"{get_emoji('very_low_quality')} {to_small_caps('ʟᴏᴡ ǫᴜᴀʟɪᴛʏ')} (64 ᴋʙᴘs)", 
                                         callback_data=f"dl_spotify_all_{playlist_id}_64_confirmed")],
                    [InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ ꜰᴏʀ ʜɪɢʜᴇʀ ǫᴜᴀʟɪᴛʏ')}", 
                                         callback_data="premium_info")],
                    [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                         callback_data=f"view_spotify_playlist_{playlist_id}_1")]
                ]
            
            await query.edit_message_text(
                f"{get_emoji('quality')} {to_small_caps('ꜱᴇʟᴇᴄᴛ ᴀᴜᴅɪᴏ ǫᴜᴀʟɪᴛʏ ꜰᴏʀ ꜱᴘᴏᴛɪꜰʏ ᴘʟᴀʏʟɪꜱᴛ:')}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
            
        # Handle Spotify playlist download requests
        elif query.data.startswith("dl_spotify_all_"):
            # Import asyncio for use in this function
            import asyncio
            
            # Extract playlist ID, confirmation status, and quality if present
            parts = query.data.split("_")
            playlist_id = parts[3]
            user_id = query.from_user.id
            user = query.from_user
            
            # Check for confirmation and quality settings
            is_confirmed = False
            selected_quality = None
            
            if len(parts) > 4:
                if parts[4] == "confirmed":
                    is_confirmed = True
                elif parts[4].isdigit():
                    selected_quality = int(parts[4])
                    
            if len(parts) > 5 and parts[5] == "confirmed":
                is_confirmed = True
            
            # Create user info for logging
            user_info = {
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name
            }
            
            # Check if user is premium (only premium users can download full playlists)
            user_data = users_collection.find_one({"user_id": user_id})
            is_premium = user_data and user_data.get("is_premium", False)
            
            if not is_premium:
                premium_text = f"{get_emoji('premium')} {to_small_caps('ꜱᴘᴏᴛɪꜰʏ ᴘʟᴀʏʟɪꜱᴛ ᴅᴏᴡɴʟᴏᴀᴅꜱ ᴀʀᴇ ꜰᴏʀ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ ᴏɴʟʏ!')}"
                
                # Create premium info buttons
                keyboard = [
                    [InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ')}", 
                                         callback_data="premium_info")],
                    [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                         callback_data="back_to_start")]
                ]
                
                await query.edit_message_text(
                    premium_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
            
            # For premium users, start the download processing
            progress_msg = await query.edit_message_text(
                f"{get_emoji('wait')} {to_small_caps('ᴘʀᴇᴘᴀʀɪɴɢ ꜱᴘᴏᴛɪꜰʏ ᴘʟᴀʏʟɪꜱᴛ ᴅᴏᴡɴʟᴏᴀᴅ...')}"
            )
            
            try:
                # Get playlist tracks from Spotify API
                results = spotify.playlist_items(
                    playlist_id,
                    fields='items(track(id,name,artists,album(name))),total',
                    limit=100  # Get up to 100 tracks per request
                )
                
                total_tracks = results.get('total', 0)
                tracks = []
                
                # First batch of tracks
                items = results.get('items', [])
                tracks.extend([item.get('track') for item in items if item.get('track')])
                
                # If there are more tracks, fetch them with pagination
                if total_tracks > 100:
                    for offset in range(100, total_tracks, 100):
                        more_results = spotify.playlist_items(
                            playlist_id,
                            fields='items(track(id,name,artists,album(name)))',
                            limit=100,
                            offset=offset
                        )
                        more_items = more_results.get('items', [])
                        tracks.extend([item.get('track') for item in more_items if item.get('track')])
                
                if not tracks:
                    await progress_msg.edit_text(
                        f"{get_emoji('error')} {to_small_caps('ᴘʟᴀʏʟɪꜱᴛ ɪꜱ ᴇᴍᴘᴛʏ ᴏʀ ɴᴏ ᴛʀᴀᴄᴋꜱ ᴄᴏᴜʟᴅ ʙᴇ ꜰᴏᴜɴᴅ.')}"
                    )
                    return
                
                # For large playlists, show a confirmation message if not already confirmed
                if len(tracks) > 50 and not is_confirmed:
                    # Estimate download time (assume ~30 seconds per track)
                    est_minutes = (len(tracks) * 30) // 60
                    est_hours = est_minutes // 60
                    est_min_remainder = est_minutes % 60
                    
                    if est_hours > 0:
                        est_time_msg = f"{est_hours} {to_small_caps('ʜᴏᴜʀꜱ')} {est_min_remainder} {to_small_caps('ᴍɪɴᴜᴛᴇꜱ')}"
                    else:
                        est_time_msg = f"{est_minutes} {to_small_caps('ᴍɪɴᴜᴛᴇꜱ')}"
                    
                    await progress_msg.edit_text(
                        f"{get_emoji('info')} {to_small_caps('ᴛʜɪꜱ ɪꜱ ᴀ ʟᴀʀɢᴇ ᴘʟᴀʏʟɪꜱᴛ ᴡɪᴛʜ')} {len(tracks)} {to_small_caps('ᴛʀᴀᴄᴋꜱ.')}\n\n"
                        f"{to_small_caps('ᴇꜱᴛɪᴍᴀᴛᴇᴅ ᴅᴏᴡɴʟᴏᴀᴅ ᴛɪᴍᴇ:')} {est_time_msg}\n"
                        f"{to_small_caps('ᴅᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ?')}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                f"{get_emoji('download')} {to_small_caps('ʏᴇꜱ, ᴅᴏᴡɴʟᴏᴀᴅ ᴀʟʟ ᴛʀᴀᴄᴋꜱ')}",
                                callback_data=f"dl_spotify_all_{playlist_id}_confirmed"
                            )],
                            [InlineKeyboardButton(
                                f"{get_emoji('track')} {to_small_caps('ʙʀᴏᴡꜱᴇ ᴛʀᴀᴄᴋꜱ ɪɴꜱᴛᴇᴀᴅ')}",
                                callback_data=f"view_spotify_playlist_{playlist_id}_1"
                            )],
                            [InlineKeyboardButton(
                                f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}",
                                callback_data="back_to_start"
                            )]
                        ])
                    )
                    return
                
                # For very large playlists (>100), show an additional notice
                if len(tracks) > 100:
                    # Estimate download time (assume ~30 seconds per track)
                    est_minutes = (len(tracks) * 30) // 60
                    est_hours = est_minutes // 60
                    est_min_remainder = est_minutes % 60
                    
                    if est_hours > 0:
                        est_time_msg = f"{est_hours} {to_small_caps('ʜᴏᴜʀꜱ')} {est_min_remainder} {to_small_caps('ᴍɪɴᴜᴛᴇꜱ')}"
                    else:
                        est_time_msg = f"{est_minutes} {to_small_caps('ᴍɪɴᴜᴛᴇꜱ')}"
                    
                    await progress_msg.edit_text(
                        f"{get_emoji('info')} {to_small_caps('ᴛʜɪꜱ ɪꜱ ᴀ ᴠᴇʀʏ ʟᴀʀɢᴇ ᴘʟᴀʏʟɪꜱᴛ.')}\n\n"
                        f"{to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ')} {len(tracks)} {to_small_caps('ᴛʀᴀᴄᴋꜱ ᴡɪʟʟ ᴛᴀᴋᴇ ᴀᴘᴘʀᴏxɪᴍᴀᴛᴇʟʏ')} {est_time_msg}.\n"
                        f"{to_small_caps('ᴘʟᴇᴀꜱᴇ ʙᴇ ᴘᴀᴛɪᴇɴᴛ ᴅᴜʀɪɴɢ ᴛʜᴇ ᴅᴏᴡɴʟᴏᴀᴅ ᴘʀᴏᴄᴇꜱꜱ.')}"
                    )
                    
                    # Give user time to read the message before starting downloads
                    await asyncio.sleep(3)
                
                # Try to get the playlist name
                playlist_name = "Unknown Playlist"
                try:
                    playlist_info = spotify.playlist(playlist_id)
                    playlist_name = playlist_info['name']
                except Exception as e:
                    logger.error(f"Error getting playlist name: {e}")
                
                # Update message with download information
                await progress_msg.edit_text(
                    f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ꜱᴘᴏᴛɪꜰʏ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n"
                    f"{to_small_caps('ɴᴀᴍᴇ:')} {playlist_name}\n"
                    f"{to_small_caps('ᴛʀᴀᴄᴋꜱ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ:')} {len(tracks)}\n\n"
                    f"{get_emoji('wait')} {to_small_caps('ᴘʀᴇᴘᴀʀɪɴɢ ᴅᴏᴡɴʟᴏᴀᴅ...')}\n"
                    f"[                    ] 0/{len(tracks)}"
                )
                
                # Make sure temp directory exists
                os.makedirs('temp', exist_ok=True)
                
                # Setup for quality based on user's premium status
                quality = PREMIUM_BITRATE if is_premium else FREE_BITRATE
                
                # Process each track in the playlist
                successful_downloads = 0
                failed_downloads = 0
                download_results = []
                
                # For each track in the playlist
                for i, track in enumerate(tracks, start=1):
                    if not track:
                        continue
                        
                    track_id = track.get('id', '')
                    track_name = track.get('name', 'Unknown')
                    artist_name = track.get('artists', [{}])[0].get('name', 'Unknown')
                    album_name = track.get('album', {}).get('name', 'Unknown')
                    
                    # Update progress message
                    progress_bar = "■" * int((i-1) * 20 / len(tracks))
                    progress_bar += "□" * (20 - int((i-1) * 20 / len(tracks)))
                    
                    # Calculate remaining time based on average of 30 seconds per track
                    remaining_tracks = len(tracks) - (i-1)
                    est_seconds_remaining = remaining_tracks * 30
                    
                    # Format remaining time
                    if est_seconds_remaining > 3600:
                        hours = est_seconds_remaining // 3600
                        minutes = (est_seconds_remaining % 3600) // 60
                        est_time_left = f"{hours}h {minutes}m"
                    elif est_seconds_remaining > 60:
                        minutes = est_seconds_remaining // 60
                        est_time_left = f"{minutes}m"
                    else:
                        est_time_left = f"{est_seconds_remaining}s"
                    
                    await progress_msg.edit_text(
                        f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n"
                        f"{to_small_caps('ɴᴀᴍᴇ:')} {playlist_name}\n"
                        f"{to_small_caps('ᴘʀᴏɢʀᴇꜱꜱ:')} {i-1}/{len(tracks)} • {to_small_caps('ᴇꜱᴛ. ᴛɪᴍᴇ ʟᴇꜰᴛ:')} {est_time_left}\n\n"
                        f"{get_emoji('wait')} {to_small_caps('ᴄᴜʀʀᴇɴᴛʟʏ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ:')}\n"
                        f"{track_name[:30] + '...' if len(track_name) > 30 else track_name} - {artist_name[:20]}\n\n"
                        f"[{progress_bar}]"
                    )
                    
                    # Skip tracks without IDs
                    if not track_id:
                        failed_downloads += 1
                        download_results.append({
                            "title": track_name,
                            "artist": artist_name,
                            "status": "failed",
                            "error": "Missing track ID"
                        })
                        continue
                    
                    # Search for the track on YouTube
                    search_query = f"{track_name} {artist_name} audio"
                    
                    try:
                        # Setup YouTube-DL options
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'temp/{track_name} - {artist_name}.%(ext)s',
                            'quiet': True,
                            'noplaylist': True,
                            'cookiefile': 'cookies.txt',
                            'default_search': 'ytsearch',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': str(quality),
                            }],
                        }
                        
                        # Download the track
                        with YoutubeDL(ydl_opts) as ydl:
                            # Search for the track on YouTube
                            info = ydl.extract_info(f"ytsearch:{search_query}", download=True)
                            # We're only downloading the first search result
                            entries = info.get('entries', [])
                            if not entries:
                                raise ValueError("No search results found")
                            
                            video_info = entries[0]
                        
                        # Find the downloaded file
                        downloaded_file = None
                        expected_file = f'temp/{track_name} - {artist_name}.mp3'
                        expected_file = expected_file.replace('/', '_').replace('\\', '_')
                        
                        if os.path.exists(expected_file):
                            downloaded_file = expected_file
                        else:
                            for file in os.listdir('temp'):
                                if file.endswith('.mp3'):
                                    downloaded_file = os.path.join('temp', file)
                                    break
                        
                        if not downloaded_file:
                            raise FileNotFoundError("Could not find the downloaded audio file")
                        
                        # Extract metadata
                        youtube_title = video_info.get('title', 'Unknown')
                        youtube_uploader = video_info.get('uploader', 'Unknown')
                        duration = video_info.get('duration', 0)
                        file_size = os.path.getsize(downloaded_file)
                        
                        # Prepare caption
                        caption = f"{get_emoji('track')} {to_small_caps('ᴛʀᴀᴄᴋ')} {i}/{len(tracks)}:\n\n"
                        caption += f"{to_small_caps('ᴛɪᴛʟᴇ:')} {track_name}\n"
                        caption += f"{to_small_caps('ᴀʀᴛɪꜱᴛ:')} {artist_name}\n"
                        caption += f"{to_small_caps('ᴀʟʙᴜᴍ:')} {album_name}\n"
                        caption += f"{to_small_caps('ǫᴜᴀʟɪᴛʏ:')} {quality}kbps\n"
                        caption += f"{to_small_caps('ꜱɪᴢᴇ:')} {file_size / (1024*1024):.2f} MB"
                        
                        # Send the audio file
                        with open(downloaded_file, 'rb') as audio:
                            sent_message = await context.bot.send_audio(
                                chat_id=query.message.chat_id,
                                audio=audio,
                                title=track_name,
                                performer=artist_name,
                                duration=duration,
                                caption=caption
                            )
                        
                        # Track successful download
                        successful_downloads += 1
                        download_results.append({
                            "title": track_name,
                            "artist": artist_name,
                            "status": "success",
                            "file_id": sent_message.audio.file_id,
                            "file_size": file_size
                        })
                        
                        # Update download counters in database
                        if user_data:
                            users_collection.update_one(
                                {"user_id": user_id},
                                {"$inc": {"downloads_today": 1, "total_downloads": 1},
                                "$set": {"last_download_date": datetime.now()}}
                            )
                            
                        # Log successful download
                        details = {
                            "action": "download_completed",
                            "spotify_id": track_id,
                            "track_name": track_name,
                            "artist": artist_name,
                            "quality": quality,
                            "file_size_mb": file_size / (1024*1024),
                            "source": "spotify_playlist",
                            "playlist_id": playlist_id,
                            "track_position": i
                        }
                        await log_activity(context, "download", user_info, details)
                        
                        # Clean up the temporary file
                        try:
                            os.remove(downloaded_file)
                        except Exception as e:
                            logger.error(f"Failed to clean up temp file: {e}")
                            
                    except Exception as e:
                        logger.error(f"Error downloading track {track_id}: {e}")
                        failed_downloads += 1
                        download_results.append({
                            "title": track_name,
                            "artist": artist_name,
                            "status": "failed",
                            "error": str(e)[:100]
                        })
                        
                        # Send error message for this track
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text=f"{get_emoji('error')} {to_small_caps('ᴇʀʀᴏʀ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴛʀᴀᴄᴋ:')} {track_name} - {artist_name}\n\n{str(e)[:100]}"
                        )
                
                # Update progress message with final summary
                progress_bar = "■" * 20  # Full bar
                
                summary = f"{get_emoji('success')} {to_small_caps('ᴘʟᴀʏʟɪꜱᴛ ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ:')}\n\n"
                summary += f"{to_small_caps('ɴᴀᴍᴇ:')} {playlist_name}\n"
                summary += f"{to_small_caps('ᴛʀᴀᴄᴋꜱ ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ:')} {successful_downloads}/{len(tracks)}\n"
                
                if failed_downloads > 0:
                    summary += f"{to_small_caps('ꜰᴀɪʟᴇᴅ ᴅᴏᴡɴʟᴏᴀᴅꜱ:')} {failed_downloads}\n"
                
                summary += f"\n[{progress_bar}]"
                
                # Create return to menu button
                keyboard = [
                    [InlineKeyboardButton(f"{get_emoji('playlist')} {to_small_caps('ʙʀᴏᴡꜱᴇ ᴍᴏʀᴇ ᴘʟᴀʏʟɪꜱᴛꜱ')}", 
                                         callback_data="back_to_start")]
                ]
                
                await progress_msg.edit_text(
                    summary,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # Log the playlist download completion
                details = {
                    "action": "playlist_download_completed",
                    "playlist_id": playlist_id,
                    "playlist_name": playlist_name,
                    "total_tracks": len(tracks),
                    "successful_downloads": successful_downloads,
                    "failed_downloads": failed_downloads,
                    "source": "spotify"
                }
                await log_activity(context, "download", user_info, details)
                
            except Exception as e:
                logger.error(f"Error processing Spotify playlist download: {e}")
                await progress_msg.edit_text(
                    f"{get_emoji('error')} {to_small_caps('ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ ᴡʜɪʟᴇ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴛʜᴇ ᴘʟᴀʏʟɪꜱᴛ:')}\n\n{str(e)[:100]}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"{get_emoji('back')} {to_small_caps('ʙᴀᴄᴋ')}", 
                                            callback_data="back_to_start")]
                    ])
                )
                
                error_details = {
                    "action": "playlist_download_failed",
                    "playlist_id": playlist_id,
                    "error": str(e),
                    "source": "spotify"
                }
                await log_activity(context, "error", user_info, error_details, level="ERROR")
            
            return
            
        # Handle Spotify track download requests
        elif query.data.startswith("dl_track_"):
            # Extract Spotify track ID and quality parameter if present
            parts = query.data.split("_")
            spotify_id = parts[2]
            user_id = query.from_user.id
            user = query.from_user
            
            # Extract quality if specified
            quality = None
            if len(parts) >= 4:
                try:
                    quality = int(parts[3])
                except ValueError:
                    pass
            
            # Log the download request
            details = {
                "action": "download_requested",
                "spotify_id": spotify_id,
                "track_type": "single_track",
                "requested_quality": quality,
                "source": "spotify"
            }
            await log_activity(context, "download", user_info, details)
            
            # Always send a new message rather than editing to avoid type issues
            status_msg = await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"{get_emoji('wait')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴛʀᴀᴄᴋ...')}"
            )
            
            # Check if user can download (free users have daily limits)
            user_data = users_collection.find_one({"user_id": user_id})
            if user_data:
                is_premium = user_data.get("is_premium", False)
                downloads_today = user_data.get("downloads_today", 0)
                
                # Check if free user has reached limit
                if not is_premium and downloads_today >= FREE_DAILY_LIMIT:
                    premium_text = f"{get_emoji('error')} {to_small_caps('ʏᴏᴜ ʜᴀᴠᴇ ʀᴇᴀᴄʜᴇᴅ ʏᴏᴜʀ ᴅᴀɪʟʏ ᴅᴏᴡɴʟᴏᴀᴅ ʟɪᴍɪᴛ!')}\n\n"
                    premium_text += f"{get_emoji('premium')} {to_small_caps('ᴜᴘɢʀᴀᴅᴇ ᴛᴏ ᴘʀᴇᴍɪᴜᴍ ꜰᴏʀ ᴜɴʟɪᴍɪᴛᴇᴅ ᴅᴏᴡɴʟᴏᴀᴅꜱ!')}"
                    
                    keyboard = [
                        [InlineKeyboardButton(f"{get_emoji('premium')} {to_small_caps('ɢᴇᴛ ᴘʀᴇᴍɪᴜᴍ')}",
                                            callback_data="premium_info")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    # Use a new message instead of editing
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=premium_text,
                        reply_markup=reply_markup
                    )
                    
                    # Log download limit reached
                    details = {
                        "action": "download_limit_reached",
                        "daily_limit": FREE_DAILY_LIMIT,
                        "downloads_today": downloads_today
                    }
                    await log_activity(context, "limit", user_info, details, level="WARNING")
                    return
            
            # Check if song is already in database
            existing_track = songs_collection.find_one({"spotify_id": spotify_id})
            if existing_track and DB_CHANNEL:
                # If we have the file_id, we can directly send it
                file_id = existing_track.get("file_id")
                if file_id:
                    try:
                        # Get details from existing track
                        title = existing_track.get("title", "Unknown Title")
                        artist = existing_track.get("artist", "Unknown Artist")
                        
                        # Send audio file
                        await context.bot.send_audio(
                            chat_id=query.message.chat_id,
                            audio=file_id,
                            title=title,
                            performer=artist,
                            caption=f"{get_emoji('success')} {to_small_caps('ᴇɴᴊᴏʏ ʏᴏᴜʀ ᴛʀᴀᴄᴋ!')}"
                        )
                        
                        # Update user's download count
                        if user_data:
                            users_collection.update_one(
                                {"user_id": user_id},
                                {"$inc": {"downloads_today": 1, "total_downloads": 1}}
                            )
                        
                        # Log the successful download from cache
                        is_premium = user_data and user_data.get("is_premium", False)
                        details = {
                            "action": "download_completed",
                            "track_name": title,
                            "artist": artist,
                            "source": "cache",
                            "quality": PREMIUM_BITRATE if is_premium else FREE_BITRATE
                        }
                        await log_activity(context, "download", user_info, details)
                        
                        # Update message to show download completed
                        feedback_msg = f"{get_emoji('success')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇᴅ!')}"
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text=feedback_msg
                        )
                        return
                    except Exception as e:
                        logger.error(f"Error sending cached file: {e}")
                        # Log the error
                        details = {
                            "message": str(e),
                            "context": "sending_cached_file",
                            "spotify_id": spotify_id
                        }
                        await log_activity(context, "error", user_info, details, level="ERROR")
                        # Continue with regular download if cached file fails
                
            # Get track info from Spotify
            try:
                track_info = spotify.track(spotify_id)
                if not track_info:
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=f"{get_emoji('error')} {to_small_caps('ᴄᴏᴜʟᴅ ɴᴏᴛ ꜰɪɴᴅ ᴛʀᴀᴄᴋ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ.')}"
                    )
                    
                    # Log Spotify API error
                    details = {
                        "message": "Could not find track information",
                        "context": "spotify_api_lookup",
                        "spotify_id": spotify_id
                    }
                    await log_activity(context, "error", user_info, details, level="ERROR")
                    return
                    
                # Format track info
                track_name = track_info['name']
                artist_name = track_info['artists'][0]['name']
                search_query = f"{artist_name} - {track_name}"
                
                # Search for track on YouTube
                search_msg = await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"{get_emoji('wait')} {to_small_caps('ꜱᴇᴀʀᴄʜɪɴɢ ꜰᴏʀ ᴛʀᴀᴄᴋ...')}"
                )
                
                # Check for quality selection in callback data
                # Format: dl_track_SPOTIFYID_QUALITY
                selected_quality = None
                parts = query.data.split('_')
                if len(parts) >= 4:
                    try:
                        quality_param = parts[3]
                        if quality_param in ['64', '128', '320']:
                            selected_quality = int(quality_param)
                    except (IndexError, ValueError):
                        pass
                
                # Determine quality
                is_premium = user_data and user_data.get("is_premium", False)
                
                # Use specified quality if provided and user is eligible
                if selected_quality:
                    # Premium users can select any quality
                    if is_premium:
                        bitrate = selected_quality
                    # Free users are limited to lower quality options
                    else:
                        # Cap at FREE_BITRATE for free users
                        bitrate = min(selected_quality, FREE_BITRATE)
                else:
                    # Default to highest allowed quality for user tier
                    bitrate = PREMIUM_BITRATE if is_premium else FREE_BITRATE
                
                # Set up yt-dlp options using cookies.txt
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'cookiefile': './cookies.txt',  # Use the cookies file
                    'noplaylist': True,
                    'quiet': True,
                    'no_warnings': True,
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': str(bitrate),
                    }],
                    'outtmpl': f'./temp/%(title)s.%(ext)s'
                }
                
                try:
                    # Use yt-dlp to search for the track
                    status_msg = await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=f"{get_emoji('wait')} {to_small_caps('ꜱᴇᴀʀᴄʜɪɴɢ ʏᴏᴜᴛᴜʙᴇ...')}"
                    )
                    
                    # Log the YouTube search request
                    details = {
                        "action": "youtube_search",
                        "search_query": search_query,
                        "spotify_id": spotify_id
                    }
                    await log_activity(context, "youtube", user_info, details)
                    
                    with YoutubeDL(ydl_opts) as ydl:
                        # In a real implementation, you would:
                        # 1. Search YouTube for the track
                        # 2. Download the audio
                        # 3. Send the audio file
                        
                        # Real implementation for searching and downloading from YouTube
                        search_url = f"ytsearch1:{search_query}"
                        
                        # First search for the track
                        search_status = f"{get_emoji('search')} {to_small_caps('ꜱᴇᴀʀᴄʜɪɴɢ ꜰᴏʀ ʙᴇꜱᴛ ᴍᴀᴛᴄʜ...')}"
                        await status_msg.edit_text(search_status)
                        
                        try:
                            # Find the best match on YouTube
                            with YoutubeDL({'quiet': True, 'no_warnings': True}) as search_ydl:
                                info = search_ydl.extract_info(search_url, download=False)
                                if 'entries' in info and info['entries']:
                                    video = info['entries'][0]
                                    video_url = video['webpage_url']
                                    video_title = video['title']
                                    
                                    # Show the found track
                                    found_text = f"{get_emoji('success')} {to_small_caps('ꜰᴏᴜɴᴅ ᴛʀᴀᴄᴋ:')}\n\n"
                                    found_text += f"{to_small_caps('ʏᴏᴜᴛᴜʙᴇ ᴛɪᴛʟᴇ:')} {video_title}\n"
                                    found_text += f"{to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ɴᴏᴡ...')}"
                                    await status_msg.edit_text(found_text)
                                    
                                    # Set filename
                                    filename = f"./temp/{track_name} - {artist_name}.mp3"
                                    ydl_opts['outtmpl'] = f"./temp/{track_name} - {artist_name}.%(ext)s"
                                    
                                    # Create a hook to update progress
                                    def progress_hook(d):
                                        if d['status'] == 'downloading':
                                            # Extract progress info
                                            try:
                                                downloaded = d.get('downloaded_bytes', 0)
                                                total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
                                                speed = d.get('speed', 0)
                                                eta = d.get('eta', 0)
                                                
                                                if total > 0:
                                                    percent = int(downloaded * 100 / total)
                                                    bar_length = 20
                                                    filled_length = int(bar_length * percent / 100)
                                                    bar = '■' * filled_length + '□' * (bar_length - filled_length)
                                                    
                                                    # Convert bytes to MB
                                                    downloaded_mb = downloaded / 1024 / 1024
                                                    total_mb = total / 1024 / 1024
                                                    speed_mb = speed / 1024 / 1024 if speed else 0
                                                    
                                                    # Format time
                                                    if eta:
                                                        mins = eta // 60
                                                        secs = eta % 60
                                                        eta_str = f"{mins}𝚖𝚒𝚗, {secs}𝚜𝚎𝚌"
                                                    else:
                                                        eta_str = "calculating..."
                                                        
                                                    # Update the global progress_data directly
                                                    nonlocal progress_data
                                                    progress_data['percent'] = percent
                                                    progress_data['bar'] = bar
                                                    progress_data['downloaded_mb'] = downloaded_mb
                                                    progress_data['total_mb'] = total_mb
                                                    progress_data['speed_mb'] = speed_mb
                                                    progress_data['eta'] = eta_str
                                                    
                                                    # Log progress for debugging
                                                    logger.debug(f"Download progress: {percent}% - {downloaded_mb:.2f}MB / {total_mb:.2f}MB")
                                            except Exception as e:
                                                logger.error(f"Error in progress_hook: {e}")  # Log any errors
                                    
                                    # Add progress hook to options
                                    ydl_opts['progress_hooks'] = [progress_hook]
                                    
                                    # Set up a task to update the progress bar
                                    progress_data = {
                                        'percent': 0,
                                        'bar': '□' * 20,
                                        'downloaded_mb': 0,
                                        'total_mb': 0,
                                        'speed_mb': 0,
                                        'eta': 'calculating...'
                                    }
                                    
                                    # Create a function to update the progress message
                                    async def update_progress():
                                        import asyncio
                                        import time
                                        
                                        # For tracking update frequency
                                        last_update_time = time.time()
                                        update_count = 0
                                        download_complete = False
                                        
                                        # Add a flag to track if we should continue updating
                                        active = True
                                        
                                        # Log that we've started the update task
                                        logger.info("Progress update task started")
                                        
                                        while active:
                                            try:
                                                # Calculate progress percentage
                                                percent = progress_data['percent']
                                                downloaded_mb = progress_data['downloaded_mb']
                                                total_mb = progress_data['total_mb']
                                                speed_mb = progress_data['speed_mb']
                                                
                                                # Check if download reached 100%
                                                if percent >= 100:
                                                    download_complete = True
                                                
                                                # Create a simple progress bar
                                                bar_length = 20
                                                filled_length = int(bar_length * percent / 100)
                                                bar = '█' * filled_length + '▒' * (bar_length - filled_length)
                                                
                                                # Build a simpler progress text
                                                progress_text = f"{get_emoji('download')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴛʀᴀᴄᴋ...')}\n\n"
                                                progress_text += f"{bar}  {percent}%\n\n"
                                                progress_text += f"{to_small_caps('ꜱɪᴢᴇ')}: {downloaded_mb:.2f}MB / {total_mb:.2f}MB\n"
                                                progress_text += f"{to_small_caps('ꜱᴘᴇᴇᴅ')}: {speed_mb:.2f} MB/s\n"
                                                
                                                # Update the status message (max 1 update per 1 second to prevent rate limiting)
                                                current_time = time.time()
                                                if current_time - last_update_time >= 1.0:
                                                    await status_msg.edit_text(progress_text)
                                                    last_update_time = current_time
                                                    update_count += 1
                                                    logger.info(f"Progress update #{update_count}: {percent}% - {downloaded_mb:.2f}MB / {total_mb:.2f}MB")
                                                
                                                # Longer sleep interval to reduce API load
                                                await asyncio.sleep(1.0)
                                            except asyncio.CancelledError:
                                                logger.info("Progress update task was cancelled")
                                                # Exit the task gracefully
                                                active = False
                                                break
                                            except Exception as e:
                                                logger.error(f"Error updating progress: {e}")
                                                # Wait longer if we hit errors
                                                await asyncio.sleep(2.0)
                                    
                                    # Start the progress updater in the background
                                    import asyncio
                                    
                                    # Make sure to use a global loop
                                    loop = asyncio.get_event_loop()
                                    progress_task = loop.create_task(update_progress())
                                    logger.info("Started progress update task")
                                    
                                    try:
                                        # Download the audio
                                        with YoutubeDL(ydl_opts) as ydl:
                                            # This will run the progress_hook during download
                                            ydl.download([video_url])
                                            
                                            # After each hook call, our progress_data is already updated
                                            # by the progress_hook function directly
                                    except Exception as e:
                                        logger.error(f"Download error: {e}")
                                        raise
                                    finally:
                                        # Stop the progress updater
                                        logger.info("Cancelling progress update task")
                                        progress_task.cancel()
                                        
                                        # Wait for the task to be cancelled properly (optional)
                                        try:
                                            # Wait for a short time to let the task exit gracefully
                                            await asyncio.wait_for(progress_task, timeout=1.0)
                                        except (asyncio.TimeoutError, asyncio.CancelledError):
                                            # This is expected, task was cancelled
                                            pass
                                        except Exception as e:
                                            logger.error(f"Error waiting for task to complete: {e}")
                                    
                                    # Show completed status
                                    await status_msg.edit_text(f"{get_emoji('success')} {to_small_caps('ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇᴅ!')}")
                                else:
                                    # No results found
                                    await status_msg.edit_text(f"{get_emoji('error')} {to_small_caps('ɴᴏ ᴍᴀᴛᴄʜɪɴɢ ᴛʀᴀᴄᴋ ꜰᴏᴜɴᴅ!')}")
                                    return
                        except Exception as e:
                            logger.error(f"Error searching YouTube: {e}")
                            await status_msg.edit_text(f"{get_emoji('error')} {to_small_caps('ᴇʀʀᴏʀ ꜱᴇᴀʀᴄʜɪɴɢ ʏᴏᴜᴛᴜʙᴇ!')}")
                            raise
                        
                        # Update user's download count
                        if user_data:
                            users_collection.update_one(
                                {"user_id": user_id},
                                {"$inc": {"downloads_today": 1, "total_downloads": 1}}
                            )
                        
                        # Send the actual audio file
                        caption = f"{get_emoji('success')} {to_small_caps('ʜᴇʀᴇ ɪꜱ ʏᴏᴜʀ ᴛʀᴀᴄᴋ!')}\n\n"
                        caption += f"{to_small_caps('ᴛɪᴛʟᴇ:')} {track_name}\n"
                        caption += f"{to_small_caps('ᴀʀᴛɪꜱᴛ:')} {artist_name}\n"
                        caption += f"{to_small_caps('ʙɪᴛʀᴀᴛᴇ:')} {bitrate} kbps"
                        
                        # Create a rating keyboard
                        keyboard = [
                            [
                                InlineKeyboardButton(f"⭐", callback_data=f"rate_1_{spotify_id}"),
                                InlineKeyboardButton(f"⭐⭐", callback_data=f"rate_2_{spotify_id}"),
                                InlineKeyboardButton(f"⭐⭐⭐", callback_data=f"rate_3_{spotify_id}"),
                                InlineKeyboardButton(f"⭐⭐⭐⭐", callback_data=f"rate_4_{spotify_id}"),
                                InlineKeyboardButton(f"⭐⭐⭐⭐⭐", callback_data=f"rate_5_{spotify_id}")
                            ]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        # Send the audio file
                        try:
                            with open(filename, 'rb') as audio_file:
                                message = await context.bot.send_audio(
                                    chat_id=query.message.chat_id,
                                    audio=audio_file,
                                    title=track_name,
                                    performer=artist_name,
                                    caption=caption,
                                    reply_markup=reply_markup
                                )
                                
                                # If we have a DB_CHANNEL, save the file_id for future use
                                if DB_CHANNEL:
                                    # Get the file_id for future reuse
                                    file_id = message.audio.file_id
                                    
                                    # Save to database
                                    songs_collection.update_one(
                                        {"spotify_id": spotify_id},
                                        {
                                            "$set": {
                                                "file_id": file_id,
                                                "title": track_name,
                                                "artist": artist_name,
                                                "spotify_id": spotify_id,
                                                "youtube_title": video_title,
                                                "bitrate": bitrate
                                            }
                                        },
                                        upsert=True
                                    )
                                    
                                    # Forward to the database channel
                                    try:
                                        await context.bot.forward_message(
                                            chat_id=DB_CHANNEL,
                                            from_chat_id=query.message.chat_id,
                                            message_id=message.message_id
                                        )
                                    except Exception as e:
                                        logger.error(f"Failed to forward to DB channel: {e}")
                        except Exception as e:
                            logger.error(f"Failed to send audio: {e}")
                            # Send a fallback message if sending audio fails
                            await query.message.reply_text(f"{get_emoji('error')} {to_small_caps('ᴇʀʀᴏʀ ꜱᴇɴᴅɪɴɢ ᴀᴜᴅɪᴏ ꜰɪʟᴇ.')}")
                        
                        # Log the successful download from YouTube
                        details = {
                            "action": "download_completed",
                            "track_name": track_name,
                            "artist": artist_name,
                            "source": "youtube", 
                            "quality": bitrate
                        }
                        await log_activity(context, "download", user_info, details)
                    
                except Exception as e:
                    logger.error(f"Error downloading track: {e}")
                    await query.edit_message_text(f"{get_emoji('error')} {to_small_caps('ᴇʀʀᴏʀ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴛʀᴀᴄᴋ.')}")
                    
                    # Log the error
                    details = {
                        "message": str(e),
                        "context": "youtube_download",
                        "search_query": search_query,
                        "spotify_id": spotify_id
                    }
                    await log_activity(context, "error", user_info, details, level="ERROR")
                    
            except Exception as e:
                logger.error(f"Error processing track: {e}")
                await query.edit_message_text(f"{get_emoji('error')} {to_small_caps('ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ ᴡʜɪʟᴇ ᴘʀᴏᴄᴇꜱꜱɪɴɢ ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ.')}")
                
                # Log the error
                details = {
                    "message": str(e),
                    "context": "track_processing",
                    "spotify_id": spotify_id
                }
                await log_activity(context, "error", user_info, details, level="ERROR")
    
    except Exception as e:
        # General error handling for button callbacks
        logger.error(f"Error in button callback: {e}")
        
        try:
            # Try to notify user with a new message instead of editing
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"{get_emoji('error')} {to_small_caps('ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ. ᴘʟᴇᴀꜱᴇ ᴛʀʏ ᴀɢᴀɪɴ.')}"
            )
        except Exception as msg_error:
            # If even that fails, log it
            logger.error(f"Failed to send error message: {msg_error}")
        
        # Try to answer the callback query to stop the loading indicator
        try:
            await query.answer("An error occurred.")
        except Exception:
            pass
            
        try:
            # Log the error
            details = {
                "message": str(e),
                "context": "button_callback",
                "query_data": query.data
            }
            await log_activity(context, "error", user_info, details, level="ERROR")
        except Exception as log_error:
            logger.error(f"Failed to log error: {log_error}")
            
        # Return to prevent further processing
        return

def main() -> None:
    """Start the bot."""
    # Print welcome message
    print("🎵 Starting Spotify Downloader Bot...")
    
    # Log detailed startup information
    startup_info = {
        "version": "2.0.0",
        "environment": "production",
        "start_time": bot_start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "admins_count": len(ADMINS),
        "free_daily_limit": FREE_DAILY_LIMIT,
        "free_bitrate": FREE_BITRATE,
        "premium_bitrate": PREMIUM_BITRATE,
        "python_version": os.environ.get("PYTHON_VERSION", "3.x")
    }
    logger.info(f"Bot starting up with configuration: {json.dumps(startup_info)}")
    
    # Build application
    application = Application.builder().token(os.environ.get("BOT_TOKEN", "")).build()
    
    # Define shutdown handler
    async def shutdown_handler(update=None, context=None):
        """Handle graceful shutdown"""
        shutdown_time = datetime.now()
        
        # Log shutdown
        uptime_seconds = (shutdown_time - bot_start_time).total_seconds()
        days, remainder = divmod(uptime_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_text = f"{int(days)}d {int(hours)}h {int(minutes)}m {int(seconds)}s"
        
        shutdown_log = {
            "action": "bot_shutdown",
            "shutdown_time": shutdown_time.strftime("%Y-%m-%d %H:%M:%S"),
            "uptime": uptime_text,
            "shutdown_reason": "Signal received" if context else "Manual shutdown"
        }
        logger.info(f"Bot shutting down: {json.dumps(shutdown_log)}")
        
        # Try to send a shutdown message to log channel
        if LOG_CHANNEL:
            try:
                shutdown_message = f"🔴 {to_small_caps('ʙᴏᴛ ꜱʜᴜᴛᴅᴏᴡɴ')}\n\n"
                shutdown_message += f"{to_small_caps('ᴛɪᴍᴇ:')} {shutdown_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                shutdown_message += f"{to_small_caps('ᴜᴘᴛɪᴍᴇ:')} {uptime_text}"
                
                await application.bot.send_message(chat_id=LOG_CHANNEL, text=shutdown_message)
            except Exception as e:
                print(f"Failed to send shutdown message: {e}")

    # Register signal handlers for graceful shutdown
    application.add_error_handler(shutdown_handler)
    
    # Add command handlers with descriptions
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ping", ping_command))
    application.add_handler(CommandHandler("ftmdl", ftmdl_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("id", id_command))
    application.add_handler(CommandHandler("setpremium", set_premium_command))
    application.add_handler(CommandHandler("removepremium", remove_premium_command))
    application.add_handler(CommandHandler("checkpremium", check_premium_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("developer", developer_command))
    
    # Add message handlers for link detection
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    
    # Add callback query handler
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Log to admin channel if available - using non-async method to start
    if LOG_CHANNEL:
        def send_startup_message(context):
            try:
                startup_message = f"🚀 {to_small_caps('ʙᴏᴛ ꜱᴛᴀʀᴛᴇᴅ!')}\n\n"
                startup_message += f"{to_small_caps('ᴛɪᴍᴇ:')} {bot_start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                startup_message += f"{to_small_caps('ᴠᴇʀꜱɪᴏɴ:')} 2.0.0\n"
                startup_message += f"{to_small_caps('ᴍᴏᴅᴇ:')} Production\n"
                
                context.bot.send_message(chat_id=LOG_CHANNEL, text=startup_message)
            except Exception as e:
                logger.error(f"Failed to send startup message to log channel: {e}")
        
        application.job_queue.run_once(send_startup_message, 10)
        
    # Run the application
    application.run_polling()

if __name__ == '__main__':
    main()
