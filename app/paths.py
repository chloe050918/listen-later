import hashlib, json, os
from pathlib import Path
DATA=Path(os.environ.get('LISTEN_LATER_DATA',str(Path.home()/'.listen-later'))).expanduser().resolve()
MEDIA=DATA/'media'
INSTANCE=hashlib.sha256(str(DATA).encode()).hexdigest()[:20]
try: saved=json.loads((DATA/'runtime.json').read_text())
except (OSError,ValueError):saved={}
PORT=int(os.environ.get('LISTEN_LATER_PORT',saved.get('port',8770)))
BASE=f'http://127.0.0.1:{PORT}'
