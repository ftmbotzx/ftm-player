# Spotify Downloader Telegram Bot
### Copyright © ftmdeveloperz - #ftmdeveloperz

A Telegram bot for downloading music from Spotify via YouTube with premium features.

## Features

- Download tracks from Spotify
- Premium features for unlimited downloads and higher quality
- Support for albums and playlists (premium only)
- Caching to speed up repeat downloads
- Daily download limits for free users (10 tracks per day)
- Audio quality: 128kbps for free users, 320kbps for premium users
- All bot text in small caps with emojis
- YouTube cookies integration to avoid anti-bot measures

## Requirements

- Python 3.7 or higher
- FFmpeg
- MongoDB
- Telegram Bot Token
- Spotify API credentials
- YouTube cookies.txt file

## Configuration

The bot is configured through environment variables:

- `BOT_TOKEN`: Your Telegram Bot token (from BotFather)
- `SPOTIFY_CLIENT_ID`: Your Spotify API client ID
- `SPOTIFY_CLIENT_SECRET`: Your Spotify API client secret
- `MONGODB_URI`: MongoDB connection string
- `DB_CHANNEL`: Telegram channel ID for caching downloaded files
- `LOG_CHANNEL`: Telegram channel ID for logging bot activities
- `ADMINS`: Comma-separated list of admin user IDs

## Running the Bot

1. Make sure Python, FFmpeg, and other dependencies are installed
2. Configure the environment variables in Replit Secrets
3. Make sure your cookies.txt file is in the project root
4. Run the bot:

```bash
python bot.py
```

Or use the configured Replit workflow "run-bot" which will automatically run the bot.

## Bot Commands

- `/start` - Start the bot
- `/help` - Show help message
- `/ping` - Check bot response time
- `/status` - Check your account status
- `/stats` - Show bot statistics (admin only)
- `/subscribe` - Get premium subscription
- `/about` - Show information about the bot
- `/add_premium [user_id] [days]` - Add premium for a user (admin only)
- `/remove_premium [user_id]` - Remove premium from a user (admin only)

## Premium Features

- Unlimited downloads (no daily limit)
- Higher audio quality (320kbps)
- Album & playlist downloads
- ZIP file downloads for multiple tracks

## License

This project is licensed under the MIT License - see the LICENSE file for details.

Copyright © ftmdeveloperz - #ftmdeveloperz