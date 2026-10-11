import os
from pathlib import Path
from dotenv import dotenv_values
from paths import DATA
ENV_FILE=Path(os.environ.get('LISTEN_LATER_ENV',str(DATA/'.env'))).expanduser()
KEYS=('ARK_API_KEY','ARK_CHAT_MODEL','VOLC_SPEECH_API_KEY','VOLC_VOICE_HOST_A','VOLC_VOICE_HOST_B')
def refresh():
    values=dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
    for key in KEYS:globals()[key]=os.environ.get(key,values.get(key) or '')
refresh()
OUTPUT_DIR=Path(os.environ.get('AI_DIGEST_OUTPUT_DIR',str(DATA/'output'))).expanduser().resolve()
OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
EPISODE_PATH=OUTPUT_DIR/'episode.mp3'
class ConfigurationError(ValueError):pass

def require(value,name,hint=''):
    if not value:raise ConfigurationError(f'缺少 {name}。请在本机 .env 中配置，运行 doctor 查看位置；不要在聊天里发送密钥。')
    return value

def check_text():
    refresh()
    require(ARK_API_KEY,'ARK_API_KEY');require(ARK_CHAT_MODEL,'ARK_CHAT_MODEL')

def check_audio():
    refresh()
    import shutil
    for k in ('VOLC_SPEECH_API_KEY','VOLC_VOICE_HOST_A','VOLC_VOICE_HOST_B'):require(globals()[k],k)
    if VOLC_VOICE_HOST_A==VOLC_VOICE_HOST_B:raise ConfigurationError('两位主持人需要不同的音色 ID。')
    if not shutil.which('ffmpeg'):raise ConfigurationError('未找到 ffmpeg，请安装并加入 PATH 后再合成。')
