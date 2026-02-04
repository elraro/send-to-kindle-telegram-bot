import telebot
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.policy import SMTP
from email.mime.base import MIMEBase
from email import encoders
import argparse
import webhook
import os

from persistence.loggerfactory import LoggerFactory

LOG = LoggerFactory('EpubBot').get_logger()

_ENV_TELEGRAM_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
_ENV_TELEGRAM_USER_ALIAS = "TELEGRAM_USER_ALIAS"
_ENV_SMTP_SERVER = "SMTP_SERVER"
_ENV_SMTP_PORT = "SMTP_PORT"
_ENV_SMTP_USER = "SMTP_USER"
_ENV_SMTP_PASSWORD = "SMTP_PASSWORD"

_ENV_LOGGING_FILE = 'LOGFILE'
_ENV_WEBHOOK_HOST = 'WEBHOOK_HOST'
_ENV_WEBHOOK_PORT = 'WEBHOOK_PORT'
_ENV_WEBHOOK_LISTEN = 'WEBHOOK_LISTEN'
_ENV_WEBHOOK_LISTEN_PORT = 'WEBHOOK_LISTEN_PORT'

parser = argparse.ArgumentParser()
parser.add_argument("-v", "--verbosity", help="Defines log verbosity",
                    choices=['CRITICAL', 'ERROR', 'WARN', 'INFO', 'DEBUG'], default='INFO')
parser.add_argument("--token", type=str, help="Telegram API token given by @botfather.")
parser.add_argument("--users", type=str, help="Comma-separated list of authorized users with emails (format: alias:email,alias2:email2).")
parser.add_argument("--logfile", type=str, help="Log to defined file.")
parser.add_argument("--webhook-host", type=str, help="Sets a webhook to the specified host.")
parser.add_argument("--webhook-port", type=str, help="Webhook port. Default is 443.", default="443")
parser.add_argument("--webhook-listening", type=str, help="Webhook local listening IP. Default is 0.0.0.0",
                    default="0.0.0.0")
parser.add_argument("--webhook-listening-port", type=str, help="Webhook local listening port. Default is 8080",
                    default="8080")
parser.add_argument("--smtp-server", type=str, help="SMTP server host. Default is smtp.gmail.com", default="smtp.gmail.com")
parser.add_argument("--smtp-port", type=str, help="SMTP server port. Default is 465.", default="465")
parser.add_argument("--smtp-user", type=str, help="SMTP username")
parser.add_argument("--smtp-password", type=str, help="SMTP password")

args = parser.parse_args()

# Parse users configuration
authorized_users = {}  # {username: email}

def parse_users_config(users_str):
    """
    Parse users configuration from string format (alias:email,alias2:email2).
    Returns a dictionary of {username: email}
    """
    users = {}
    
    if users_str:
        try:
            user_pairs = users_str.split(',')
            for pair in user_pairs:
                if ':' in pair:
                    alias, email = pair.split(':', 1)
                    users[alias.strip()] = email.strip()
            LOG.debug(f'Successfully parsed {len(users)} user(s) from configuration')
        except Exception as e:
            LOG.warning('Error parsing users configuration: %s', e)
    
    return users

try:
    args.logfile = os.environ[_ENV_LOGGING_FILE]
except KeyError:
    pass

try:
    args.token = os.environ[_ENV_TELEGRAM_BOT_TOKEN]
    LOG.debug('Telegram bot token loaded from environment variable')
except KeyError as key_error:
    if not args.token:
        LOG.critical(
            'No telegram bot token provided. Please do so using --token argument or %s environment variable.',
            _ENV_TELEGRAM_BOT_TOKEN)
        sys.exit(1)
    LOG.debug('Telegram bot token loaded from command line argument')

# Try to get users from environment variable first, then from command line argument
users_config = os.environ.get(_ENV_TELEGRAM_USER_ALIAS) or args.users
if users_config:
    LOG.debug('Users configuration found')
authorized_users = parse_users_config(users_config) if users_config else {}

if not authorized_users:
    LOG.warning(
        'No authorized users specified. Please do so using --users argument (format: alias:email,alias2:email2) or %s environment variable.',
        _ENV_TELEGRAM_USER_ALIAS)
else:
    LOG.info(f'Loaded {len(authorized_users)} authorized user(s)')

try:
    args.webhook_host = os.environ[_ENV_WEBHOOK_HOST]
    args.webhook_port = int(os.environ[_ENV_WEBHOOK_PORT])
    args.webhook_listening = os.environ[_ENV_WEBHOOK_LISTEN]
    args.webhook_listening_port = int(os.environ[_ENV_WEBHOOK_LISTEN_PORT])
    LOG.info(f'Webhook configured: {args.webhook_host}:{args.webhook_port}')
except KeyError:
    LOG.critical('No webhook configuration provided.')
    sys.exit(1)

try:
    args.smtp_server = os.environ[_ENV_SMTP_SERVER]
    args.smtp_port= int(os.environ[_ENV_SMTP_PORT])
    args.smtp_user = os.environ[_ENV_SMTP_USER]
    args.smtp_password = os.environ[_ENV_SMTP_PASSWORD]
    LOG.info(f'SMTP server configured: {args.smtp_server}:{args.smtp_port}')
except KeyError:
    LOG.critical('No mail configuration provided.')
    sys.exit(1)

# ADMIN COMMANDS
def message_is_from_authorized_user(message):
    """Check if message is from an authorized user"""
    from_user = message.from_user
    return from_user.username in authorized_users

def get_user_email(message):
    """Get the email associated with the message sender"""
    from_user = message.from_user
    return authorized_users.get(from_user.username)

LOG.info('Starting up bot...')
LOG.info(f'Authorized users: {", ".join(authorized_users.keys()) if authorized_users else "none"}')
bot = telebot.TeleBot(args.token)
LOG.info('Bot initialized successfully')

@bot.message_handler(content_types=['document'], func=lambda message: message_is_from_authorized_user(message))
def handle_document(message):
    from_user = message.from_user
    doc = message.document
    LOG.info(f'Document received from @{from_user.username}: {doc.file_name}')
    
    if not doc.file_name.endswith('.epub'):
        LOG.warning(f'Invalid file format from @{from_user.username}: {doc.file_name}')
        bot.reply_to(message, "Solo se aceptan archivos .epub.")
        return

    try:
        # Descarga el archivo
        LOG.debug(f'Downloading file: {doc.file_id}')
        file_info = bot.get_file(doc.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        LOG.debug(f'File downloaded successfully, size: {len(downloaded_file)} bytes')
        
        bot.reply_to(message, f"Archivo recibido: {doc.file_name}. Enviando por correo...")

        # Enviar por correo
        user_email = get_user_email(message)
        LOG.info(f'Sending {doc.file_name} to {user_email} for @{from_user.username}')
        send_email_with_attachment(downloaded_file, doc.file_name, user_email)
        LOG.info(f'Email sent successfully to {user_email}')
        bot.send_message(message.chat.id, "✅ Archivo enviado por correo correctamente.")
    except Exception as e:
        LOG.error(f'Error processing document from @{from_user.username}: {str(e)}', exc_info=True)
        bot.send_message(message.chat.id, f"❌ Error al enviar correo: {e}")

def send_email_with_attachment(downloaded_file, file_name, recipient_email):
    try:
        LOG.debug(f'Preparing email for {file_name} to {recipient_email}')
        msg = MIMEMultipart()
        msg['Subject'] = 'Send to Kindle'
        msg['From'] = args.smtp_user
        msg['To'] = recipient_email

        part = MIMEBase("application", "octet-stream")
        part.set_payload(downloaded_file)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{file_name}"',
        )
        msg.attach(part)

        # Enviar el correo
        LOG.debug(f'Connecting to SMTP server {args.smtp_server}:{args.smtp_port}')
        with smtplib.SMTP_SSL(args.smtp_server, args.smtp_port) as smtp:
            smtp.login(args.smtp_user, args.smtp_password)
            LOG.debug('Authenticated with SMTP server')
            smtp.send_message(msg)
            LOG.debug('Email sent via SMTP')
    except smtplib.SMTPException as e:
        LOG.error(f'SMTP error while sending email to {recipient_email}: {str(e)}', exc_info=True)
        raise
    except Exception as e:
        LOG.error(f'Unexpected error while sending email to {recipient_email}: {str(e)}', exc_info=True)
        raise

LOG.info(f'Starting webhook listener on {args.webhook_listening}:{args.webhook_listening_port}')
webhook.start_webhook(bot, args.webhook_host, args.webhook_port, args.webhook_listening,
                          args.webhook_listening_port)
LOG.info('Bot is now running')