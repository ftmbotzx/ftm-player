# ###############################################################
# #                                                             #
# #                  Spotify Downloader Bot                     #
# #                  Copyright © ftmdeveloperz                  #
# #                       #ftmdeveloperz                        #
# #                                                             #
# ###############################################################

from flask import Flask, render_template_string

app = Flask(__name__)

@app.route('/')
def home():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Spotify Downloader Bot</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                line-height: 1.6;
                background-color: #121212;
                color: #ffffff;
                text-align: center;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
            }
            h1 {
                color: #1DB954; /* Spotify green */
            }
            p {
                margin-bottom: 20px;
            }
            .button {
                display: inline-block;
                background-color: #1DB954;
                color: white;
                padding: 10px 20px;
                text-decoration: none;
                border-radius: 30px;
                font-weight: bold;
                margin-top: 20px;
            }
            .logo {
                font-size: 48px;
                margin-bottom: 20px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">🎵</div>
            <h1>Spotify Downloader Bot</h1>
            <p>This is a Telegram bot for downloading music from Spotify.</p>
            <p>The bot itself is running separately and this web interface is just informational.</p>
            <p>To use the bot, search for it on Telegram and start downloading your favorite music!</p>
            <a href="https://t.me/SpotifyDownloaderBot" class="button">Open Bot on Telegram</a>
            <p style="margin-top: 30px; font-size: 12px; color: #888;">Copyright © ftmdeveloperz - #ftmdeveloperz</p>
        </div>
    </body>
    </html>
    """
    return render_template_string(html)

if __name__ == '__main__':
    print("This file is not used but is needed to avoid a Flask/Gunicorn error.")
    app.run(host='0.0.0.0', port=5000, debug=True)