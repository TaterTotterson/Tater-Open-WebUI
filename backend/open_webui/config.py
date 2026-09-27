from __future__ import annotations

import base64
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse

import redis
import requests
from authlib.integrations.starlette_client import OAuth
from pydantic import BaseModel

from open_webui.env import (
    DATA_DIR,
    ENABLE_ADMIN_CHAT_ACCESS,
    ENABLE_DB_MIGRATIONS,
    ENV,
    FRONTEND_BUILD_DIR,
    OFFLINE_MODE,
    OPEN_WEBUI_DIR,
    REDIS_KEY_PREFIX,
    REDIS_SENTINEL_HOSTS,
    REDIS_SENTINEL_PORT,
    REDIS_URL,
    WEBUI_AUTH,
    WEBUI_FAVICON_URL,
    WEBUI_NAME,
    log,
)
from open_webui.models.config import Config
from open_webui.utils.json_codec import JSONCodec
from open_webui.utils.tater_profile import (
    DEFAULT_TATER_API_BASE_URL,
    DEFAULT_TATER_BASE_MODEL,
    DEFAULT_TATER_CONTEXT_WINDOW,
    DEFAULT_TATER_HYDRA_MODEL,
    normalize_tater_api_base_url,
    normalize_tater_context_window,
)


async def seed_registered_defaults():
    await Config.repair_config_rows()
    await Config.seed_defaults(DEFAULT_CONFIG)


async def async_reset_config():
    await Config.clear()


class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find('/health') == -1


logging.getLogger('uvicorn.access').addFilter(EndpointFilter())

####################################
# Initialization
####################################


def run_migrations():
    log.info('Running migrations')
    try:
        from alembic import command
        from alembic.config import Config as AlembicConfig

        alembic_cfg = AlembicConfig(OPEN_WEBUI_DIR / 'alembic.ini')

        migrations_path = OPEN_WEBUI_DIR / 'migrations'
        alembic_cfg.set_main_option('script_location', str(migrations_path))

        command.upgrade(alembic_cfg, 'head')
    except Exception as e:
        log.exception(f'Error running migrations: {e}')
        raise


if ENABLE_DB_MIGRATIONS:
    run_migrations()


async def import_legacy_config_json():
    """Migrate legacy config.json → database on first run."""
    if not os.path.exists(f'{DATA_DIR}/config.json'):
        return
    with open(f'{DATA_DIR}/config.json', 'r') as _f:
        await Config.upsert(JSONCodec.loads(_f.read()))
    os.rename(f'{DATA_DIR}/config.json', f'{DATA_DIR}/old_config.json')


####################################
# Static DIR
####################################

STATIC_DIR = Path(os.getenv('STATIC_DIR', OPEN_WEBUI_DIR / 'static')).resolve()

try:
    if STATIC_DIR.exists():
        for item in STATIC_DIR.iterdir():
            if item.is_file() or item.is_symlink():
                try:
                    item.unlink()
                except Exception as e:
                    pass
except Exception as e:
    pass

for file_path in (FRONTEND_BUILD_DIR / 'static').glob('**/*'):
    if file_path.is_file():
        target_path = STATIC_DIR / file_path.relative_to((FRONTEND_BUILD_DIR / 'static'))
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(file_path, target_path)
        except Exception as e:
            logging.error(f'An error occurred: {e}')

# LICENSE covers copied Open WebUI logo/favicon assets.
# Do not alter, remove, obscure, or replace them except as LICENSE permits:
# https://docs.openwebui.com/license.
frontend_favicon = FRONTEND_BUILD_DIR / 'static' / 'favicon.png'

if frontend_favicon.exists():
    try:
        shutil.copyfile(frontend_favicon, STATIC_DIR / 'favicon.png')
    except Exception as e:
        logging.error(f'An error occurred: {e}')

frontend_splash = FRONTEND_BUILD_DIR / 'static' / 'splash.png'

if frontend_splash.exists():
    try:
        shutil.copyfile(frontend_splash, STATIC_DIR / 'splash.png')
    except Exception as e:
        logging.error(f'An error occurred: {e}')

frontend_loader = FRONTEND_BUILD_DIR / 'static' / 'loader.js'

if frontend_loader.exists():
    try:
        shutil.copyfile(frontend_loader, STATIC_DIR / 'loader.js')
    except Exception as e:
        logging.error(f'An error occurred: {e}')


# --- Storage Provider ---

STORAGE_PROVIDER = os.getenv('STORAGE_PROVIDER', 'local')  # defaults to local, s3
STORAGE_LOCAL_CACHE = os.getenv('STORAGE_LOCAL_CACHE', 'true').lower() == 'true'

S3_ACCESS_KEY_ID = os.getenv('S3_ACCESS_KEY_ID', None)
S3_SECRET_ACCESS_KEY = os.getenv('S3_SECRET_ACCESS_KEY', None)
S3_REGION_NAME = os.getenv('S3_REGION_NAME', None)
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', None)
S3_KEY_PREFIX = os.getenv('S3_KEY_PREFIX', None)
S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL', None)
S3_USE_ACCELERATE_ENDPOINT = os.getenv('S3_USE_ACCELERATE_ENDPOINT', 'false').lower() == 'true'
S3_ADDRESSING_STYLE = os.getenv('S3_ADDRESSING_STYLE', None)
S3_ENABLE_TAGGING = os.getenv('S3_ENABLE_TAGGING', 'false').lower() == 'true'

GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', None)
GOOGLE_APPLICATION_CREDENTIALS_JSON = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON', None)

AZURE_STORAGE_ENDPOINT = os.getenv('AZURE_STORAGE_ENDPOINT', None)
AZURE_STORAGE_CONTAINER_NAME = os.getenv('AZURE_STORAGE_CONTAINER_NAME', None)
AZURE_STORAGE_KEY = os.getenv('AZURE_STORAGE_KEY', None)

####################################
# File Upload DIR
####################################

UPLOAD_DIR = DATA_DIR / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


####################################
# Cache DIR
####################################

CACHE_DIR = DATA_DIR / 'cache'
CACHE_DIR.mkdir(parents=True, exist_ok=True)


####################################
# CUSTOM_NAME (Legacy)
####################################

# LICENSE covers this legacy Open WebUI branding path.
# Do not alter, remove, obscure, or replace it except as LICENSE permits:
# https://docs.openwebui.com/license.
CUSTOM_NAME = os.getenv('CUSTOM_NAME', '')

if CUSTOM_NAME:
    try:
        r = requests.get(f'https://api.openwebui.com/api/v1/custom/{CUSTOM_NAME}')
        data = r.json()
        if r.ok:
            if 'logo' in data:
                WEBUI_FAVICON_URL = url = (
                    f'https://api.openwebui.com{data["logo"]}' if data['logo'][0] == '/' else data['logo']
                )

                r = requests.get(url, stream=True)
                if r.status_code == 200:
                    with open(f'{STATIC_DIR}/favicon.png', 'wb') as f:
                        r.raw.decode_content = True
                        shutil.copyfileobj(r.raw, f)

            if 'splash' in data:
                url = f'https://api.openwebui.com{data["splash"]}' if data['splash'][0] == '/' else data['splash']

                r = requests.get(url, stream=True)
                if r.status_code == 200:
                    with open(f'{STATIC_DIR}/splash.png', 'wb') as f:
                        r.raw.decode_content = True
                        shutil.copyfileobj(r.raw, f)

            WEBUI_NAME = data['name']
    except Exception as e:
        log.exception(e)
        pass


####################################
# OPENAI_API
####################################


ENABLE_OPENAI_API = os.getenv('ENABLE_OPENAI_API', 'True').lower() == 'true'


OPENAI_API_KEY = os.getenv('TATER_API_KEY', '')
OPENAI_API_BASE_URL = normalize_tater_api_base_url(
    os.getenv('TATER_API_BASE_URL', DEFAULT_TATER_API_BASE_URL)
)

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_API_BASE_URL = os.getenv('GEMINI_API_BASE_URL', '')


OPENAI_API_KEYS = [OPENAI_API_KEY]
OPENAI_API_BASE_URLS = [OPENAI_API_BASE_URL]
OPENAI_API_CONFIGS = {
    '0': {
        'enable': True,
        'provider': 'tater',
        'connection_type': 'external',
    }
}

# Get the actual OpenAI API key based on the base URL
OPENAI_API_KEY = ''
try:
    OPENAI_API_KEY = OPENAI_API_KEYS[OPENAI_API_BASE_URLS.index('https://api.openai.com/v1')]
except Exception:
    pass
OPENAI_API_BASE_URL = 'https://api.openai.com/v1'


####################################
# MODELS
####################################

ENABLE_BASE_MODELS_CACHE = os.getenv('ENABLE_BASE_MODELS_CACHE', 'False').lower() == 'true'


####################################
# TOOL_SERVERS
####################################

try:
    tool_server_connections = JSONCodec.loads(os.getenv('TOOL_SERVER_CONNECTIONS', '[]'))
except Exception as e:
    log.exception(f'Error loading TOOL_SERVER_CONNECTIONS: {e}')
    tool_server_connections = []


TOOL_SERVER_CONNECTIONS = tool_server_connections

OAUTH_CLIENT_TIMEOUT = os.getenv('OAUTH_CLIENT_TIMEOUT', '')

####################################
# TERMINAL_SERVER
####################################

terminal_server_connections = JSONCodec.loads(os.getenv('TERMINAL_SERVER_CONNECTIONS', '[]'))

TERMINAL_SERVER_CONNECTIONS = terminal_server_connections

try:
    TERMINAL_PROXY_HEADERS = JSONCodec.loads(os.getenv('TERMINAL_PROXY_HEADERS', '{}'))
except Exception:
    TERMINAL_PROXY_HEADERS = {}

####################################
# Code Interpreter
####################################

ENABLE_CODE_EXECUTION = os.getenv('ENABLE_CODE_EXECUTION', 'False').lower() == 'true'

CODE_EXECUTION_ENGINE = os.getenv('CODE_EXECUTION_ENGINE', 'pyodide')

CODE_EXECUTION_JUPYTER_URL = os.getenv('CODE_EXECUTION_JUPYTER_URL', '')

CODE_EXECUTION_JUPYTER_AUTH = os.getenv('CODE_EXECUTION_JUPYTER_AUTH', '')

CODE_EXECUTION_JUPYTER_AUTH_TOKEN = os.getenv('CODE_EXECUTION_JUPYTER_AUTH_TOKEN', '')


CODE_EXECUTION_JUPYTER_AUTH_PASSWORD = os.getenv('CODE_EXECUTION_JUPYTER_AUTH_PASSWORD', '')

CODE_EXECUTION_JUPYTER_TIMEOUT = int(os.getenv('CODE_EXECUTION_JUPYTER_TIMEOUT', '60'))

ENABLE_CODE_INTERPRETER = os.getenv('ENABLE_CODE_INTERPRETER', 'False').lower() == 'true'

CODE_INTERPRETER_ENGINE = os.getenv('CODE_INTERPRETER_ENGINE', 'pyodide')

CODE_INTERPRETER_PROMPT_TEMPLATE = os.getenv('CODE_INTERPRETER_PROMPT_TEMPLATE', '')

CODE_INTERPRETER_JUPYTER_URL = os.getenv('CODE_INTERPRETER_JUPYTER_URL', os.getenv('CODE_EXECUTION_JUPYTER_URL', ''))

CODE_INTERPRETER_JUPYTER_AUTH = os.getenv(
    'CODE_INTERPRETER_JUPYTER_AUTH',
    os.getenv('CODE_EXECUTION_JUPYTER_AUTH', ''),
)

CODE_INTERPRETER_JUPYTER_AUTH_TOKEN = os.getenv(
    'CODE_INTERPRETER_JUPYTER_AUTH_TOKEN',
    os.getenv('CODE_EXECUTION_JUPYTER_AUTH_TOKEN', ''),
)


CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD = os.getenv(
    'CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD',
    os.getenv('CODE_EXECUTION_JUPYTER_AUTH_PASSWORD', ''),
)

CODE_INTERPRETER_JUPYTER_TIMEOUT = int(
    os.getenv(
        'CODE_INTERPRETER_JUPYTER_TIMEOUT',
        os.getenv('CODE_EXECUTION_JUPYTER_TIMEOUT', '60'),
    )
)

CODE_INTERPRETER_BLOCKED_MODULES = [
    library.strip() for library in os.getenv('CODE_INTERPRETER_BLOCKED_MODULES', '').split(',') if library.strip()
]

DEFAULT_CODE_INTERPRETER_PROMPT = """
#### Code Interpreter

You have access to a Python code interpreter via: `<code_interpreter type="code" lang="python"></code_interpreter>`

- The Python shell runs directly in the user's browser for fast execution of analysis, calculations, or problem-solving. Use it in this response.
- You can use a wide array of libraries for data manipulation, visualization, API calls, or any computational task. Think outside the box and harness Python's full potential.
- **You must enclose your code within `<code_interpreter type="code" lang="python">` XML tags** and stop right away. If you don't, the code won't execute.
- Do NOT use triple backticks (```py ... ```) inside the XML tags — that is markdown formatting, not executable Python code.
- **Always print meaningful outputs** (results, tables, summaries, visuals). Avoid implicit outputs; use explicit print statements.
- After obtaining output, **provide a concise analysis, interpretation, or next steps** to help the user understand the findings.
- If results are unclear or unexpected, refine the code and re-execute. Iterate until you deliver meaningful insights.
- **If a link to an image, audio, or any file appears in the output, display it exactly as-is** in your response so the user can access it. Do not modify the link.
- Respond in the chat's primary language. Default to English if multilingual.

Ensure the code interpreter is effectively utilized to achieve the highest-quality analysis for the user."""

# Appended to the code interpreter prompt only when engine is pyodide (not jupyter)
CODE_INTERPRETER_PYODIDE_PROMPT = """

##### Pyodide Environment

- This Python environment runs via Pyodide in the browser. **Do not install packages** — `pip install`, `subprocess`, and `micropip.install()` are not available.
- If a required library is unavailable, use an alternative approach with available modules. Do not attempt to install anything.

##### Persistent File System

- User-uploaded files are available at `/mnt/uploads/`. When the user asks you to work with their files, read from this directory.
- You can also write output files to `/mnt/uploads/` so the user can access and download them from the file browser.
- The file system persists across code executions within the same session.
- Use `import os; os.listdir('/mnt/uploads')` to discover available files."""


####################################
# Document Attachments
####################################


# If configured, Google Drive will be available as an upload option.
ENABLE_GOOGLE_DRIVE_INTEGRATION = os.getenv('ENABLE_GOOGLE_DRIVE_INTEGRATION', 'False').lower() == 'true'

GOOGLE_DRIVE_CLIENT_ID = os.getenv('GOOGLE_DRIVE_CLIENT_ID', '')

GOOGLE_DRIVE_API_KEY = os.getenv('GOOGLE_DRIVE_API_KEY', '')

ENABLE_ONEDRIVE_INTEGRATION = os.getenv('ENABLE_ONEDRIVE_INTEGRATION', 'False').lower() == 'true'


ONEDRIVE_CLIENT_ID = os.getenv('ONEDRIVE_CLIENT_ID', '')
ONEDRIVE_CLIENT_ID_PERSONAL = os.getenv('ONEDRIVE_CLIENT_ID_PERSONAL', ONEDRIVE_CLIENT_ID)
ONEDRIVE_CLIENT_ID_BUSINESS = os.getenv('ONEDRIVE_CLIENT_ID_BUSINESS', ONEDRIVE_CLIENT_ID)

ENABLE_ONEDRIVE_PERSONAL = os.getenv('ENABLE_ONEDRIVE_PERSONAL', 'True').lower() == 'true' and bool(
    ONEDRIVE_CLIENT_ID_PERSONAL
)
ENABLE_ONEDRIVE_BUSINESS = os.getenv('ENABLE_ONEDRIVE_BUSINESS', 'True').lower() == 'true' and bool(
    ONEDRIVE_CLIENT_ID_BUSINESS
)

ONEDRIVE_SHAREPOINT_URL = os.getenv('ONEDRIVE_SHAREPOINT_URL', '')

ONEDRIVE_SHAREPOINT_TENANT_ID = os.getenv('ONEDRIVE_SHAREPOINT_TENANT_ID', '')

# RAG Content Extraction
CONTENT_EXTRACTION_ENGINE = os.getenv('CONTENT_EXTRACTION_ENGINE', '').lower()

content_extraction_supported_media_mime_types = os.getenv('CONTENT_EXTRACTION_SUPPORTED_MEDIA_MIME_TYPES')
CONTENT_EXTRACTION_SUPPORTED_MEDIA_MIME_TYPES = (
    [mime_type.strip() for mime_type in content_extraction_supported_media_mime_types.split(',') if mime_type.strip()]
    if content_extraction_supported_media_mime_types is not None
    else None
)

DATALAB_MARKER_API_KEY = os.getenv('DATALAB_MARKER_API_KEY', '')

DATALAB_MARKER_API_BASE_URL = os.getenv('DATALAB_MARKER_API_BASE_URL', '')

DATALAB_MARKER_ADDITIONAL_CONFIG = os.getenv('DATALAB_MARKER_ADDITIONAL_CONFIG', '')

DATALAB_MARKER_USE_LLM = os.getenv('DATALAB_MARKER_USE_LLM', 'false').lower() == 'true'

DATALAB_MARKER_SKIP_CACHE = os.getenv('DATALAB_MARKER_SKIP_CACHE', 'false').lower() == 'true'

DATALAB_MARKER_FORCE_OCR = os.getenv('DATALAB_MARKER_FORCE_OCR', 'false').lower() == 'true'

DATALAB_MARKER_PAGINATE = os.getenv('DATALAB_MARKER_PAGINATE', 'false').lower() == 'true'

DATALAB_MARKER_STRIP_EXISTING_OCR = os.getenv('DATALAB_MARKER_STRIP_EXISTING_OCR', 'false').lower() == 'true'

DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION = (
    os.getenv('DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION', 'false').lower() == 'true'
)

DATALAB_MARKER_FORMAT_LINES = os.getenv('DATALAB_MARKER_FORMAT_LINES', 'false').lower() == 'true'

DATALAB_MARKER_OUTPUT_FORMAT = os.getenv('DATALAB_MARKER_OUTPUT_FORMAT', 'markdown')

MINERU_API_MODE = os.getenv('MINERU_API_MODE', 'local')

MINERU_API_URL = os.getenv('MINERU_API_URL', 'http://localhost:8000')

MINERU_API_TIMEOUT = os.getenv('MINERU_API_TIMEOUT', '300')

MINERU_API_KEY = os.getenv('MINERU_API_KEY', '')

mineru_params = os.getenv('MINERU_PARAMS', '')
try:
    mineru_params = JSONCodec.loads(mineru_params)
except JSONCodec.JSONDecodeError:
    mineru_params = {}

MINERU_PARAMS = mineru_params

MINERU_FILE_EXTENSIONS = [ext.strip() for ext in os.getenv('MINERU_FILE_EXTENSIONS', 'pdf').split(',') if ext.strip()]

EXTERNAL_DOCUMENT_LOADER_URL = os.getenv('EXTERNAL_DOCUMENT_LOADER_URL', '')

EXTERNAL_DOCUMENT_LOADER_API_KEY = os.getenv('EXTERNAL_DOCUMENT_LOADER_API_KEY', '')

external_document_loader_headers = os.getenv('EXTERNAL_DOCUMENT_LOADER_HEADERS', '')
try:
    external_document_loader_headers = JSONCodec.loads(external_document_loader_headers)
except JSONCodec.JSONDecodeError:
    external_document_loader_headers = {}
if not isinstance(external_document_loader_headers, dict):
    external_document_loader_headers = {}

EXTERNAL_DOCUMENT_LOADER_HEADERS = external_document_loader_headers

TIKA_SERVER_URL = os.getenv('TIKA_SERVER_URL', 'http://tika:9998')

TIKA_SERVER_VERSION = os.getenv('TIKA_SERVER_VERSION', '3')

DOCLING_SERVER_URL = os.getenv('DOCLING_SERVER_URL', 'http://docling:5001')

DOCLING_API_KEY = os.getenv('DOCLING_API_KEY', '')

docling_params = os.getenv('DOCLING_PARAMS', '')
try:
    docling_params = JSONCodec.loads(docling_params)
except JSONCodec.JSONDecodeError:
    docling_params = {}

DOCLING_PARAMS = docling_params

DOCUMENT_INTELLIGENCE_ENDPOINT = os.getenv('DOCUMENT_INTELLIGENCE_ENDPOINT', '')

DOCUMENT_INTELLIGENCE_KEY = os.getenv('DOCUMENT_INTELLIGENCE_KEY', '')

DOCUMENT_INTELLIGENCE_MODEL = os.getenv('DOCUMENT_INTELLIGENCE_MODEL', 'prebuilt-layout')

MISTRAL_OCR_API_BASE_URL = os.getenv('MISTRAL_OCR_API_BASE_URL', 'https://api.mistral.ai/v1')

MISTRAL_OCR_API_KEY = os.getenv('MISTRAL_OCR_API_KEY', '')

MISTRAL_OCR_USE_BASE64 = os.getenv('MISTRAL_OCR_USE_BASE64', 'False').lower() == 'true'

PADDLEOCR_VL_BASE_URL = os.getenv('PADDLEOCR_VL_BASE_URL', 'http://localhost:8080')

PADDLEOCR_VL_TOKEN = os.getenv('PADDLEOCR_VL_TOKEN', '')

RAG_FILE_MAX_COUNT = int(os.getenv('RAG_FILE_MAX_COUNT')) if os.getenv('RAG_FILE_MAX_COUNT') else None

RAG_FILE_MAX_SIZE = int(os.getenv('RAG_FILE_MAX_SIZE')) if os.getenv('RAG_FILE_MAX_SIZE') else None

RAG_FILE_CONTENT_SEARCH_MAX_CHARS = int(os.getenv('RAG_FILE_CONTENT_SEARCH_MAX_CHARS', str(64 * 1024 * 1024)))

FILE_IMAGE_COMPRESSION_WIDTH = (
    int(os.getenv('FILE_IMAGE_COMPRESSION_WIDTH')) if os.getenv('FILE_IMAGE_COMPRESSION_WIDTH') else None
)

FILE_IMAGE_COMPRESSION_HEIGHT = (
    int(os.getenv('FILE_IMAGE_COMPRESSION_HEIGHT')) if os.getenv('FILE_IMAGE_COMPRESSION_HEIGHT') else None
)


RAG_ALLOWED_FILE_EXTENSIONS = [
    ext.strip() for ext in os.getenv('RAG_ALLOWED_FILE_EXTENSIONS', '').split(',') if ext.strip()
]

PDF_EXTRACT_IMAGES = os.getenv('PDF_EXTRACT_IMAGES', 'False').lower() == 'true'

PDF_LOADER_MODE = os.getenv('PDF_LOADER_MODE', 'page')

ENABLE_LOCAL_WEB_FETCH = (
    os.getenv(
        'ENABLE_LOCAL_WEB_FETCH',
        os.getenv('ENABLE_RAG_LOCAL_WEB_FETCH', 'False'),
    ).lower()
    == 'true'
)
# Deprecated compatibility alias; use ENABLE_LOCAL_WEB_FETCH for new deployments.
ENABLE_RAG_LOCAL_WEB_FETCH = ENABLE_LOCAL_WEB_FETCH


# Operators extend this through WEB_FETCH_FILTER_LIST.
DEFAULT_WEB_FETCH_FILTER_LIST = [
    '!169.254.169.254',
    '!fd00:ec2::254',
    '!metadata.google.internal',
    '!metadata.azure.com',
    '!100.100.100.200',
    '!168.63.129.16',  # Azure platform channel, reachable from every Azure VM
    '!192.88.99.0/24',  # 6to4 relay anycast, deprecated by RFC 7526
    '!224.0.0.0/4',  # IPv4 multicast
    '!::ffff:0:0:0/96',  # IPv4-translated (SIIT, RFC 2765), never routed
    '!64:ff9b:1::/48',  # NAT64 local-use prefix, RFC 8215, not a public destination
    '!100:0:0:1::/64',  # dummy prefix, RFC 9780
    '!2001:1::1',  # PCP anycast, RFC 7723, answered by the local network's own edge device
    '!2001:1::2',  # TURN anycast, RFC 8155, likewise
    '!2001:20::/28',  # ORCHIDv2, RFC 7343, never routed
    '!2001:30::/28',  # DRIP, RFC 9374, never routed
    '!5f00::/16',  # SRv6 SIDs, RFC 9602, internal to one segment routing domain
    '!fec0::/10',  # IPv6 site-local, deprecated by RFC 3879
    '!ff00::/8',  # IPv6 multicast
]

web_fetch_filter_list = os.getenv('WEB_FETCH_FILTER_LIST', '')
if web_fetch_filter_list == '':
    web_fetch_filter_list = []
else:
    web_fetch_filter_list = [item.strip() for item in web_fetch_filter_list.split(',') if item.strip()]

WEB_FETCH_FILTER_LIST = list(set(DEFAULT_WEB_FETCH_FILTER_LIST + web_fetch_filter_list))


####################################
# Images
####################################

ENABLE_IMAGE_GENERATION = os.getenv('ENABLE_IMAGE_GENERATION', '').lower() == 'true'

IMAGE_GENERATION_ENGINE = os.getenv('IMAGE_GENERATION_ENGINE', 'openai')

IMAGE_GENERATION_MODEL = os.getenv('IMAGE_GENERATION_MODEL', '')

# Regex pattern for models that support IMAGE_SIZE = "auto".
IMAGE_AUTO_SIZE_MODELS_REGEX_PATTERN = os.getenv('IMAGE_AUTO_SIZE_MODELS_REGEX_PATTERN', '^gpt-image')

# Regex pattern for models that return URLs instead of base64 data.
IMAGE_URL_RESPONSE_MODELS_REGEX_PATTERN = os.getenv('IMAGE_URL_RESPONSE_MODELS_REGEX_PATTERN', '^gpt-image')

IMAGE_SIZE = os.getenv('IMAGE_SIZE', '512x512')

IMAGE_STEPS = int(os.getenv('IMAGE_STEPS', 50))

ENABLE_IMAGE_PROMPT_GENERATION = os.getenv('ENABLE_IMAGE_PROMPT_GENERATION', 'true').lower() == 'true'

AUTOMATIC1111_BASE_URL = os.getenv('AUTOMATIC1111_BASE_URL', '')
AUTOMATIC1111_API_AUTH = os.getenv('AUTOMATIC1111_API_AUTH', '')

automatic1111_params = os.getenv('AUTOMATIC1111_PARAMS', '')
try:
    automatic1111_params = JSONCodec.loads(automatic1111_params)
except JSONCodec.JSONDecodeError:
    automatic1111_params = {}

AUTOMATIC1111_PARAMS = automatic1111_params

COMFYUI_BASE_URL = os.getenv('COMFYUI_BASE_URL', '')

COMFYUI_API_KEY = os.getenv('COMFYUI_API_KEY', '')

COMFYUI_DEFAULT_WORKFLOW = """
{
  "3": {
    "inputs": {
      "seed": 0,
      "steps": 20,
      "cfg": 8,
      "sampler_name": "euler",
      "scheduler": "normal",
      "denoise": 1,
      "model": [
        "4",
        0
      ],
      "positive": [
        "6",
        0
      ],
      "negative": [
        "7",
        0
      ],
      "latent_image": [
        "5",
        0
      ]
    },
    "class_type": "KSampler",
    "_meta": {
      "title": "KSampler"
    }
  },
  "4": {
    "inputs": {
      "ckpt_name": "model.safetensors"
    },
    "class_type": "CheckpointLoaderSimple",
    "_meta": {
      "title": "Load Checkpoint"
    }
  },
  "5": {
    "inputs": {
      "width": 512,
      "height": 512,
      "batch_size": 1
    },
    "class_type": "EmptyLatentImage",
    "_meta": {
      "title": "Empty Latent Image"
    }
  },
  "6": {
    "inputs": {
      "text": "Prompt",
      "clip": [
        "4",
        1
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "CLIP Text Encode (Prompt)"
    }
  },
  "7": {
    "inputs": {
      "text": "",
      "clip": [
        "4",
        1
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "CLIP Text Encode (Prompt)"
    }
  },
  "8": {
    "inputs": {
      "samples": [
        "3",
        0
      ],
      "vae": [
        "4",
        2
      ]
    },
    "class_type": "VAEDecode",
    "_meta": {
      "title": "VAE Decode"
    }
  },
  "9": {
    "inputs": {
      "filename_prefix": "ComfyUI",
      "images": [
        "8",
        0
      ]
    },
    "class_type": "SaveImage",
    "_meta": {
      "title": "Save Image"
    }
  }
}
"""


COMFYUI_WORKFLOW = os.getenv('COMFYUI_WORKFLOW', COMFYUI_DEFAULT_WORKFLOW)

comfyui_workflow_nodes = os.getenv('COMFYUI_WORKFLOW_NODES', '')
try:
    comfyui_workflow_nodes = JSONCodec.loads(comfyui_workflow_nodes)
except JSONCodec.JSONDecodeError:
    comfyui_workflow_nodes = []

COMFYUI_WORKFLOW_NODES = comfyui_workflow_nodes

IMAGES_OPENAI_API_BASE_URL = os.getenv('IMAGES_OPENAI_API_BASE_URL', OPENAI_API_BASE_URL)
IMAGES_OPENAI_API_VERSION = os.getenv('IMAGES_OPENAI_API_VERSION', '')

IMAGES_OPENAI_API_KEY = os.getenv('IMAGES_OPENAI_API_KEY', OPENAI_API_KEY)

images_openai_params = os.getenv('IMAGES_OPENAI_PARAMS', '')
try:
    images_openai_params = JSONCodec.loads(images_openai_params)
except JSONCodec.JSONDecodeError:
    images_openai_params = {}


IMAGES_OPENAI_API_PARAMS = images_openai_params


IMAGES_GEMINI_API_BASE_URL = os.getenv('IMAGES_GEMINI_API_BASE_URL', GEMINI_API_BASE_URL)
IMAGES_GEMINI_API_KEY = os.getenv('IMAGES_GEMINI_API_KEY', GEMINI_API_KEY)

IMAGES_GEMINI_ENDPOINT_METHOD = os.getenv('IMAGES_GEMINI_ENDPOINT_METHOD', '')

ENABLE_IMAGE_EDIT = os.getenv('ENABLE_IMAGE_EDIT', '').lower() == 'true'

IMAGE_EDIT_ENGINE = os.getenv('IMAGE_EDIT_ENGINE', 'openai')

IMAGE_EDIT_MODEL = os.getenv('IMAGE_EDIT_MODEL', '')

IMAGE_EDIT_SIZE = os.getenv('IMAGE_EDIT_SIZE', '')

ENABLE_OPENAI_IMAGE_EDIT_NORMALIZATION = os.getenv('ENABLE_OPENAI_IMAGE_EDIT_NORMALIZATION', 'true').lower() == 'true'

IMAGES_EDIT_OPENAI_API_BASE_URL = os.getenv('IMAGES_EDIT_OPENAI_API_BASE_URL', OPENAI_API_BASE_URL)
IMAGES_EDIT_OPENAI_API_VERSION = os.getenv('IMAGES_EDIT_OPENAI_API_VERSION', '')

IMAGES_EDIT_OPENAI_API_KEY = os.getenv('IMAGES_EDIT_OPENAI_API_KEY', OPENAI_API_KEY)

IMAGES_EDIT_GEMINI_API_BASE_URL = os.getenv('IMAGES_EDIT_GEMINI_API_BASE_URL', GEMINI_API_BASE_URL)
IMAGES_EDIT_GEMINI_API_KEY = os.getenv('IMAGES_EDIT_GEMINI_API_KEY', GEMINI_API_KEY)


IMAGES_EDIT_COMFYUI_BASE_URL = os.getenv('IMAGES_EDIT_COMFYUI_BASE_URL', '')
IMAGES_EDIT_COMFYUI_API_KEY = os.getenv('IMAGES_EDIT_COMFYUI_API_KEY', '')

IMAGES_EDIT_COMFYUI_WORKFLOW = os.getenv('IMAGES_EDIT_COMFYUI_WORKFLOW', '')

images_edit_comfyui_workflow_nodes = os.getenv('IMAGES_EDIT_COMFYUI_WORKFLOW_NODES', '')
try:
    images_edit_comfyui_workflow_nodes = JSONCodec.loads(images_edit_comfyui_workflow_nodes)
except JSONCodec.JSONDecodeError:
    images_edit_comfyui_workflow_nodes = []

IMAGES_EDIT_COMFYUI_WORKFLOW_NODES = images_edit_comfyui_workflow_nodes

####################################
# Audio
####################################

# Transcription
WHISPER_MODEL = os.getenv('WHISPER_MODEL', 'base')

WHISPER_COMPUTE_TYPE = os.getenv('WHISPER_COMPUTE_TYPE', 'int8')
WHISPER_MODEL_DIR = os.getenv('WHISPER_MODEL_DIR', f'{CACHE_DIR}/whisper/models')
WHISPER_MODEL_AUTO_UPDATE = not OFFLINE_MODE and os.getenv('WHISPER_MODEL_AUTO_UPDATE', '').lower() == 'true'

WHISPER_VAD_FILTER = os.getenv('WHISPER_VAD_FILTER', 'False').lower() == 'true'

WHISPER_MULTILINGUAL = os.getenv('WHISPER_MULTILINGUAL', 'False').lower() == 'true'

WHISPER_LANGUAGE = os.getenv('WHISPER_LANGUAGE', '').lower() or None

# Add Deepgram configuration
DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY', '')

# ElevenLabs configuration
ELEVENLABS_API_BASE_URL = os.getenv('ELEVENLABS_API_BASE_URL', 'https://api.elevenlabs.io')

AUDIO_STT_OPENAI_API_BASE_URL = os.getenv('AUDIO_STT_OPENAI_API_BASE_URL', OPENAI_API_BASE_URL)

AUDIO_STT_OPENAI_API_KEY = os.getenv('AUDIO_STT_OPENAI_API_KEY', OPENAI_API_KEY)

AUDIO_STT_OPENAI_API_REQUEST_FORMAT = os.getenv('AUDIO_STT_OPENAI_API_REQUEST_FORMAT', 'multipart')

AUDIO_STT_ENGINE = os.getenv('AUDIO_STT_ENGINE', '')

AUDIO_STT_MODEL = os.getenv('AUDIO_STT_MODEL', '')

AUDIO_STT_SUPPORTED_CONTENT_TYPES = [
    content_type.strip()
    for content_type in os.getenv('AUDIO_STT_SUPPORTED_CONTENT_TYPES', '').split(',')
    if content_type.strip()
]

AUDIO_STT_ALLOWED_EXTENSIONS = [
    ext.strip()
    for ext in os.getenv(
        'AUDIO_STT_ALLOWED_EXTENSIONS',
        'mp3,wav,m4a,webm,ogg,flac,mp4,mpga,mpeg',
    ).split(',')
    if ext.strip()
]

AUDIO_STT_AZURE_API_KEY = os.getenv('AUDIO_STT_AZURE_API_KEY', '')

AUDIO_STT_AZURE_REGION = os.getenv('AUDIO_STT_AZURE_REGION', '')

AUDIO_STT_AZURE_LOCALES = os.getenv('AUDIO_STT_AZURE_LOCALES', '')

AUDIO_STT_AZURE_BASE_URL = os.getenv('AUDIO_STT_AZURE_BASE_URL', '')

AUDIO_STT_AZURE_MAX_SPEAKERS = os.getenv('AUDIO_STT_AZURE_MAX_SPEAKERS', '')

AUDIO_STT_MISTRAL_API_KEY = os.getenv('AUDIO_STT_MISTRAL_API_KEY', '')

AUDIO_STT_MISTRAL_API_BASE_URL = os.getenv('AUDIO_STT_MISTRAL_API_BASE_URL', 'https://api.mistral.ai/v1')

AUDIO_STT_MISTRAL_USE_CHAT_COMPLETIONS = os.getenv('AUDIO_STT_MISTRAL_USE_CHAT_COMPLETIONS', 'false').lower() == 'true'

AUDIO_TTS_OPENAI_API_BASE_URL = os.getenv('AUDIO_TTS_OPENAI_API_BASE_URL', OPENAI_API_BASE_URL)
AUDIO_TTS_OPENAI_API_KEY = os.getenv('AUDIO_TTS_OPENAI_API_KEY', OPENAI_API_KEY)

audio_tts_openai_params = os.getenv('AUDIO_TTS_OPENAI_PARAMS', '')
try:
    audio_tts_openai_params = JSONCodec.loads(audio_tts_openai_params)
except JSONCodec.JSONDecodeError:
    audio_tts_openai_params = {}

AUDIO_TTS_OPENAI_PARAMS = audio_tts_openai_params


AUDIO_TTS_API_KEY = os.getenv('AUDIO_TTS_API_KEY', '')

AUDIO_TTS_ENGINE = os.getenv('AUDIO_TTS_ENGINE', '')


AUDIO_TTS_MODEL = os.getenv('AUDIO_TTS_MODEL', 'tts-1')

AUDIO_TTS_VOICE = os.getenv('AUDIO_TTS_VOICE', 'alloy')

AUDIO_TTS_SPLIT_ON = os.getenv('AUDIO_TTS_SPLIT_ON', 'punctuation')

AUDIO_TTS_AZURE_SPEECH_REGION = os.getenv('AUDIO_TTS_AZURE_SPEECH_REGION', '')

AUDIO_TTS_AZURE_SPEECH_BASE_URL = os.getenv('AUDIO_TTS_AZURE_SPEECH_BASE_URL', '')

AUDIO_TTS_AZURE_SPEECH_OUTPUT_FORMAT = os.getenv(
    'AUDIO_TTS_AZURE_SPEECH_OUTPUT_FORMAT', 'audio-24khz-160kbitrate-mono-mp3'
)

AUDIO_TTS_MISTRAL_API_KEY = os.getenv('AUDIO_TTS_MISTRAL_API_KEY', '')

AUDIO_TTS_MISTRAL_API_BASE_URL = os.getenv('AUDIO_TTS_MISTRAL_API_BASE_URL', 'https://api.mistral.ai/v1')

####################################
# WEBUI
####################################


WEBUI_URL = os.getenv('WEBUI_URL', '')


ENABLE_SIGNUP = False if not WEBUI_AUTH else os.getenv('ENABLE_SIGNUP', 'True').lower() == 'true'

ENABLE_LOGIN_FORM = os.getenv('ENABLE_LOGIN_FORM', 'True').lower() == 'true'

ENABLE_PASSWORD_CHANGE_FORM = os.getenv('ENABLE_PASSWORD_CHANGE_FORM', 'True').lower() == 'true'

ENABLE_PASSWORD_AUTH = os.getenv('ENABLE_PASSWORD_AUTH', 'True').lower() == 'true'

DEFAULT_LOCALE = os.getenv('DEFAULT_LOCALE', '')

DEFAULT_MODELS = os.getenv('TATER_BASE_MODEL', DEFAULT_TATER_BASE_MODEL)

DEFAULT_PINNED_MODELS = DEFAULT_MODELS

# None uses the frontend's localized defaults; an empty list disables suggestions.
try:
    DEFAULT_PROMPT_SUGGESTIONS = JSONCodec.loads(os.getenv('DEFAULT_PROMPT_SUGGESTIONS', 'null'))
except Exception as e:
    log.exception(f'Error loading DEFAULT_PROMPT_SUGGESTIONS: {e}')
    DEFAULT_PROMPT_SUGGESTIONS = None

DEFAULT_PROMPT_SUGGESTIONS_I18N = {}

try:
    model_order_list = JSONCodec.loads(os.getenv('MODEL_ORDER_LIST', '[]'))
except Exception as e:
    log.exception(f'Error loading MODEL_ORDER_LIST: {e}')
    model_order_list = []

MODEL_ORDER_LIST = model_order_list

try:
    default_model_metadata = JSONCodec.loads(os.getenv('DEFAULT_MODEL_METADATA', '{}'))
except Exception as e:
    log.exception(f'Error loading DEFAULT_MODEL_METADATA: {e}')
    default_model_metadata = {}

DEFAULT_MODEL_METADATA = default_model_metadata

try:
    default_model_params = JSONCodec.loads(os.getenv('DEFAULT_MODEL_PARAMS', '{}'))
except Exception as e:
    log.exception(f'Error loading DEFAULT_MODEL_PARAMS: {e}')
    default_model_params = {}

# Tater's current text-only base endpoint does not preserve native OpenAI tool
# calls. Use Open WebUI's structured tool planner until that contract changes.
default_model_params['function_calling'] = 'legacy'
DEFAULT_MODEL_PARAMS = default_model_params


try:
    default_interface_settings = JSONCodec.loads(os.getenv('DEFAULT_INTERFACE_SETTINGS', '{}'))
except Exception as e:
    log.exception(f'Error loading DEFAULT_INTERFACE_SETTINGS: {e}')
    default_interface_settings = {}

DEFAULT_INTERFACE_SETTINGS = default_interface_settings if isinstance(default_interface_settings, dict) else {}

DEFAULT_USER_ROLE = os.getenv('DEFAULT_USER_ROLE', 'pending')

DEFAULT_GROUP_ID = os.getenv('DEFAULT_GROUP_ID', '')

PENDING_USER_OVERLAY_TITLE = os.getenv('PENDING_USER_OVERLAY_TITLE', '')

PENDING_USER_OVERLAY_CONTENT = os.getenv('PENDING_USER_OVERLAY_CONTENT', '')


RESPONSE_WATERMARK = os.getenv('RESPONSE_WATERMARK', '')

IFRAME_CSP = os.getenv('IFRAME_CSP', '')

USER_PERMISSIONS_WORKSPACE_MODELS_ACCESS = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_MODELS_ACCESS', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ACCESS = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ACCESS', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_PROMPTS_ACCESS = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_PROMPTS_ACCESS', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_TOOLS_ACCESS = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_TOOLS_ACCESS', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_SKILLS_ACCESS = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_SKILLS_ACCESS', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_MODELS_IMPORT = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_MODELS_IMPORT', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_MODELS_EXPORT = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_MODELS_EXPORT', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_PROMPTS_IMPORT = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_PROMPTS_IMPORT', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_PROMPTS_EXPORT = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_PROMPTS_EXPORT', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_TOOLS_IMPORT = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_TOOLS_IMPORT', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_TOOLS_EXPORT = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_TOOLS_EXPORT', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_SKILLS_IMPORT = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_SKILLS_IMPORT', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_SKILLS_EXPORT = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_SKILLS_EXPORT', 'False').lower() == 'true'
)


USER_PERMISSIONS_WORKSPACE_MODELS_ALLOW_SHARING = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_MODELS_ALLOW_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_MODELS_ALLOW_PUBLIC_SHARING = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_MODELS_ALLOW_PUBLIC_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ALLOW_SHARING = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ALLOW_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ALLOW_PUBLIC_SHARING = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ALLOW_PUBLIC_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_SHARING = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_PUBLIC_SHARING = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_PUBLIC_SHARING', 'False').lower() == 'true'
)


USER_PERMISSIONS_WORKSPACE_TOOLS_ALLOW_SHARING = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_TOOLS_ALLOW_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_TOOLS_ALLOW_PUBLIC_SHARING = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_TOOLS_ALLOW_PUBLIC_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_SKILLS_ALLOW_SHARING = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_SKILLS_ALLOW_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_SKILLS_ALLOW_PUBLIC_SHARING = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_SKILLS_ALLOW_PUBLIC_SHARING', 'False').lower() == 'true'
)


USER_PERMISSIONS_FOLDERS_ALLOW_SHARING = os.getenv('USER_PERMISSIONS_FOLDERS_ALLOW_SHARING', 'False').lower() == 'true'

USER_PERMISSIONS_ACCESS_GRANTS_ALLOW_USERS = (
    os.getenv('USER_PERMISSIONS_ACCESS_GRANTS_ALLOW_USERS', 'True').lower() == 'true'
)
USER_PERMISSIONS_ACCESS_GRANTS_ALLOW_GROUPS = (
    os.getenv('USER_PERMISSIONS_ACCESS_GRANTS_ALLOW_GROUPS', 'True').lower() == 'true'
)


USER_PERMISSIONS_CHAT_CONTROLS = os.getenv('USER_PERMISSIONS_CHAT_CONTROLS', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_VALVES = os.getenv('USER_PERMISSIONS_CHAT_VALVES', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_SYSTEM_PROMPT = os.getenv('USER_PERMISSIONS_CHAT_SYSTEM_PROMPT', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_PARAMS = os.getenv('USER_PERMISSIONS_CHAT_PARAMS', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_FILE_UPLOAD = os.getenv('USER_PERMISSIONS_CHAT_FILE_UPLOAD', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_DELETE = os.getenv('USER_PERMISSIONS_CHAT_DELETE', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_DELETE_MESSAGE = os.getenv('USER_PERMISSIONS_CHAT_DELETE_MESSAGE', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_CONTINUE_RESPONSE = os.getenv('USER_PERMISSIONS_CHAT_CONTINUE_RESPONSE', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_REGENERATE_RESPONSE = (
    os.getenv('USER_PERMISSIONS_CHAT_REGENERATE_RESPONSE', 'True').lower() == 'true'
)

USER_PERMISSIONS_CHAT_RATE_RESPONSE = os.getenv('USER_PERMISSIONS_CHAT_RATE_RESPONSE', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_EDIT = os.getenv('USER_PERMISSIONS_CHAT_EDIT', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_SHARE = os.getenv('USER_PERMISSIONS_CHAT_SHARE', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_ALLOW_PUBLIC_SHARING = (
    os.getenv('USER_PERMISSIONS_CHAT_ALLOW_PUBLIC_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_CHAT_ALLOW_OPEN_SHARING = (
    os.getenv('USER_PERMISSIONS_CHAT_ALLOW_OPEN_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_CHAT_EXPORT = os.getenv('USER_PERMISSIONS_CHAT_EXPORT', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_IMPORT = os.getenv('USER_PERMISSIONS_CHAT_IMPORT', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_STT = os.getenv('USER_PERMISSIONS_CHAT_STT', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_TTS = os.getenv('USER_PERMISSIONS_CHAT_TTS', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_CALL = os.getenv('USER_PERMISSIONS_CHAT_CALL', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_MULTIPLE_MODELS = os.getenv('USER_PERMISSIONS_CHAT_MULTIPLE_MODELS', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_TEMPORARY = os.getenv('USER_PERMISSIONS_CHAT_TEMPORARY', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_TEMPORARY_ENFORCED = (
    os.getenv('USER_PERMISSIONS_CHAT_TEMPORARY_ENFORCED', 'False').lower() == 'true'
)


USER_PERMISSIONS_FEATURES_DIRECT_TOOL_SERVERS = (
    os.getenv('USER_PERMISSIONS_FEATURES_DIRECT_TOOL_SERVERS', 'False').lower() == 'true'
)

USER_PERMISSIONS_FEATURES_IMAGE_GENERATION = (
    os.getenv('USER_PERMISSIONS_FEATURES_IMAGE_GENERATION', 'True').lower() == 'true'
)

USER_PERMISSIONS_FEATURES_CODE_INTERPRETER = (
    os.getenv('USER_PERMISSIONS_FEATURES_CODE_INTERPRETER', 'True').lower() == 'true'
)

USER_PERMISSIONS_FEATURES_FOLDERS = os.getenv('USER_PERMISSIONS_FEATURES_FOLDERS', 'True').lower() == 'true'

USER_PERMISSIONS_FEATURES_API_KEYS = os.getenv('USER_PERMISSIONS_FEATURES_API_KEYS', 'False').lower() == 'true'

USER_PERMISSIONS_FEATURES_USER_WEBHOOKS = (
    os.getenv('USER_PERMISSIONS_FEATURES_USER_WEBHOOKS', 'False').lower() == 'true'
)


USER_PERMISSIONS_SETTINGS_INTERFACE = os.getenv('USER_PERMISSIONS_SETTINGS_INTERFACE', 'True').lower() == 'true'


DEFAULT_USER_PERMISSIONS = {
    'workspace': {
        'models': USER_PERMISSIONS_WORKSPACE_MODELS_ACCESS,
        'knowledge': USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ACCESS,
        'prompts': USER_PERMISSIONS_WORKSPACE_PROMPTS_ACCESS,
        'tools': USER_PERMISSIONS_WORKSPACE_TOOLS_ACCESS,
        'skills': USER_PERMISSIONS_WORKSPACE_SKILLS_ACCESS,
        'models_import': USER_PERMISSIONS_WORKSPACE_MODELS_IMPORT,
        'models_export': USER_PERMISSIONS_WORKSPACE_MODELS_EXPORT,
        'prompts_import': USER_PERMISSIONS_WORKSPACE_PROMPTS_IMPORT,
        'prompts_export': USER_PERMISSIONS_WORKSPACE_PROMPTS_EXPORT,
        'tools_import': USER_PERMISSIONS_WORKSPACE_TOOLS_IMPORT,
        'tools_export': USER_PERMISSIONS_WORKSPACE_TOOLS_EXPORT,
        'skills_import': USER_PERMISSIONS_WORKSPACE_SKILLS_IMPORT,
        'skills_export': USER_PERMISSIONS_WORKSPACE_SKILLS_EXPORT,
    },
    'sharing': {
        'models': USER_PERMISSIONS_WORKSPACE_MODELS_ALLOW_SHARING,
        'public_models': USER_PERMISSIONS_WORKSPACE_MODELS_ALLOW_PUBLIC_SHARING,
        'knowledge': USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ALLOW_SHARING,
        'public_knowledge': USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ALLOW_PUBLIC_SHARING,
        'prompts': USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_SHARING,
        'public_prompts': USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_PUBLIC_SHARING,
        'tools': USER_PERMISSIONS_WORKSPACE_TOOLS_ALLOW_SHARING,
        'public_tools': USER_PERMISSIONS_WORKSPACE_TOOLS_ALLOW_PUBLIC_SHARING,
        'skills': USER_PERMISSIONS_WORKSPACE_SKILLS_ALLOW_SHARING,
        'public_skills': USER_PERMISSIONS_WORKSPACE_SKILLS_ALLOW_PUBLIC_SHARING,
        'folders': USER_PERMISSIONS_FOLDERS_ALLOW_SHARING,
        'public_chats': USER_PERMISSIONS_CHAT_ALLOW_PUBLIC_SHARING,
        'open_chats': USER_PERMISSIONS_CHAT_ALLOW_OPEN_SHARING,
    },
    'access_grants': {
        'allow_users': USER_PERMISSIONS_ACCESS_GRANTS_ALLOW_USERS,
        'allow_groups': USER_PERMISSIONS_ACCESS_GRANTS_ALLOW_GROUPS,
    },
    'chat': {
        'controls': USER_PERMISSIONS_CHAT_CONTROLS,
        'valves': USER_PERMISSIONS_CHAT_VALVES,
        'system_prompt': USER_PERMISSIONS_CHAT_SYSTEM_PROMPT,
        'params': USER_PERMISSIONS_CHAT_PARAMS,
        'file_upload': USER_PERMISSIONS_CHAT_FILE_UPLOAD,
        'delete': USER_PERMISSIONS_CHAT_DELETE,
        'delete_message': USER_PERMISSIONS_CHAT_DELETE_MESSAGE,
        'continue_response': USER_PERMISSIONS_CHAT_CONTINUE_RESPONSE,
        'regenerate_response': USER_PERMISSIONS_CHAT_REGENERATE_RESPONSE,
        'rate_response': USER_PERMISSIONS_CHAT_RATE_RESPONSE,
        'edit': USER_PERMISSIONS_CHAT_EDIT,
        'share': USER_PERMISSIONS_CHAT_SHARE,
        'export': USER_PERMISSIONS_CHAT_EXPORT,
        'import': USER_PERMISSIONS_CHAT_IMPORT,
        'stt': USER_PERMISSIONS_CHAT_STT,
        'tts': USER_PERMISSIONS_CHAT_TTS,
        'call': USER_PERMISSIONS_CHAT_CALL,
        'multiple_models': USER_PERMISSIONS_CHAT_MULTIPLE_MODELS,
        'temporary': USER_PERMISSIONS_CHAT_TEMPORARY,
        'temporary_enforced': USER_PERMISSIONS_CHAT_TEMPORARY_ENFORCED,
    },
    'features': {
        # General features
        'api_keys': USER_PERMISSIONS_FEATURES_API_KEYS,
        'folders': USER_PERMISSIONS_FEATURES_FOLDERS,
        'direct_tool_servers': USER_PERMISSIONS_FEATURES_DIRECT_TOOL_SERVERS,
        # Chat features
        'image_generation': USER_PERMISSIONS_FEATURES_IMAGE_GENERATION,
        'code_interpreter': USER_PERMISSIONS_FEATURES_CODE_INTERPRETER,
        'webhooks': USER_PERMISSIONS_FEATURES_USER_WEBHOOKS,
    },
    'settings': {
        'interface': USER_PERMISSIONS_SETTINGS_INTERFACE,
    },
}

USER_PERMISSIONS = DEFAULT_USER_PERMISSIONS

ENABLE_FOLDERS = os.getenv('ENABLE_FOLDERS', 'True').lower() == 'true'

FOLDER_MAX_FILE_COUNT = os.getenv('FOLDER_MAX_FILE_COUNT', '')

ENABLE_SUBAGENTS = os.getenv('ENABLE_SUBAGENTS', 'False').lower() == 'true'
SUBAGENTS_BACKGROUND_ENABLED = os.getenv('SUBAGENTS_BACKGROUND_ENABLED', 'False').lower() == 'true'
SUBAGENTS_MAX_CONCURRENT = int(os.getenv('SUBAGENTS_MAX_CONCURRENT', '20'))
SUBAGENTS_MAX_ASYNC = int(os.getenv('SUBAGENTS_MAX_ASYNC', '20'))
SUBAGENTS_MAX_ITERATIONS = int(os.getenv('SUBAGENTS_MAX_ITERATIONS', '30'))
SUBAGENTS_MAX_OUTPUT = int(os.getenv('SUBAGENTS_MAX_OUTPUT', '30000'))
SUBAGENTS_SYSTEM_PROMPT = os.getenv('SUBAGENTS_SYSTEM_PROMPT', '')

ENABLE_USER_STATUS = os.getenv('ENABLE_USER_STATUS', 'True').lower() == 'true'

WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')

ENABLE_ADMIN_EXPORT = os.getenv('ENABLE_ADMIN_EXPORT', 'True').lower() == 'true'

ENABLE_ADMIN_WORKSPACE_CONTENT_ACCESS = os.getenv('ENABLE_ADMIN_WORKSPACE_CONTENT_ACCESS', 'True').lower() == 'true'

BYPASS_ADMIN_ACCESS_CONTROL = (
    os.getenv(
        'BYPASS_ADMIN_ACCESS_CONTROL',
        os.getenv('ENABLE_ADMIN_WORKSPACE_CONTENT_ACCESS', 'True'),
    ).lower()
    == 'true'
)

ENABLE_COMMUNITY_SHARING = os.getenv('ENABLE_COMMUNITY_SHARING', 'True').lower() == 'true'

ENABLE_MESSAGE_RATING = os.getenv('ENABLE_MESSAGE_RATING', 'True').lower() == 'true'

ENABLE_USER_WEBHOOKS = os.getenv('ENABLE_USER_WEBHOOKS', 'False').lower() == 'true'

# FastAPI / AnyIO settings
THREAD_POOL_SIZE = os.getenv('THREAD_POOL_SIZE', None)
THREAD_POOL_THREAD_NAME_PREFIX = os.getenv('THREAD_POOL_THREAD_NAME_PREFIX', '')

if THREAD_POOL_SIZE is not None and isinstance(THREAD_POOL_SIZE, str):
    try:
        THREAD_POOL_SIZE = int(THREAD_POOL_SIZE)
    except ValueError:
        log.warning(f'THREAD_POOL_SIZE is not a valid integer: {THREAD_POOL_SIZE}. Defaulting to None.')
        THREAD_POOL_SIZE = None


def validate_cors_origin(origin):
    parsed_url = urlparse(origin)

    # Check if the scheme is either http or https, or a custom scheme
    schemes = ['http', 'https'] + CORS_ALLOW_CUSTOM_SCHEME
    if parsed_url.scheme not in schemes:
        raise ValueError(
            f"Invalid scheme in CORS_ALLOW_ORIGIN: '{origin}'. Only 'http' and 'https' and CORS_ALLOW_CUSTOM_SCHEME are allowed."
        )

    # Ensure that the netloc (domain + port) is present, indicating it's a valid URL
    if not parsed_url.netloc:
        raise ValueError(f"Invalid URL structure in CORS_ALLOW_ORIGIN: '{origin}'.")


# For production, you should only need one host as
# fastapi serves the svelte-kit built frontend and backend from the same host and port.
# To test CORS_ALLOW_ORIGIN locally, you can set something like
# CORS_ALLOW_ORIGIN=http://localhost:5173;http://localhost:8080
# in your .env file depending on your frontend port, 5173 in this case.
CORS_ALLOW_ORIGIN = os.getenv('CORS_ALLOW_ORIGIN', '*').split(';')

# Allows custom URL schemes (e.g., app://) to be used as origins for CORS.
# Useful for local development or desktop clients with schemes like app:// or other custom protocols.
# Provide a semicolon-separated list of allowed schemes in the environment variable CORS_ALLOW_CUSTOM_SCHEMES.
CORS_ALLOW_CUSTOM_SCHEME = os.getenv('CORS_ALLOW_CUSTOM_SCHEME', '').split(';')

if CORS_ALLOW_ORIGIN == ['*']:
    log.warning("\n\nWARNING: CORS_ALLOW_ORIGIN IS SET TO '*' - NOT RECOMMENDED FOR PRODUCTION DEPLOYMENTS.\n")
else:
    # You have to pick between a single wildcard or a list of origins.
    # Doing both will result in CORS errors in the browser.
    for origin in CORS_ALLOW_ORIGIN:
        validate_cors_origin(origin)


class BannerModel(BaseModel):
    i18n: dict[str, dict[str, str]] | None = None
    id: str
    type: str
    title: str | None = None
    content: str
    dismissible: bool
    timestamp: int


try:
    banners = JSONCodec.loads(os.getenv('WEBUI_BANNERS', '[]'))
    banners = [BannerModel(**banner) for banner in banners]
except Exception as e:
    log.exception(f'Error loading WEBUI_BANNERS: {e}')
    banners = []

WEBUI_BANNERS = banners


SHOW_ADMIN_DETAILS = os.getenv('SHOW_ADMIN_DETAILS', 'true').lower() == 'true'

ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', None)


####################################
# TASKS
####################################


TASK_MODEL = os.getenv('TASK_MODEL', '')

TASK_MODEL_EXTERNAL = os.getenv('TASK_MODEL_EXTERNAL', '')

try:
    task_model_params = JSONCodec.loads(os.getenv('TASK_MODEL_PARAMS', '{}'))
except Exception as e:
    log.exception(f'Error loading TASK_MODEL_PARAMS: {e}')
    task_model_params = {}

TASK_MODEL_PARAMS = task_model_params

CONTEXT_COMPACTION_MODEL = os.getenv('CONTEXT_COMPACTION_MODEL', '')

ENABLE_CONTEXT_COMPACTION = os.getenv('ENABLE_CONTEXT_COMPACTION', 'False').lower() == 'true'

ENABLE_TOOL_PERMISSIONS = os.getenv('ENABLE_TOOL_PERMISSIONS', 'False').lower() == 'true'

CONTEXT_COMPACTION_TOKEN_THRESHOLD = int(os.getenv('CONTEXT_COMPACTION_TOKEN_THRESHOLD', '80000'))

_CONTEXT_COMPACTION_TOKEN_CAP = os.getenv('CONTEXT_COMPACTION_TOKEN_CAP')
CONTEXT_COMPACTION_TOKEN_CAP = int(_CONTEXT_COMPACTION_TOKEN_CAP) if _CONTEXT_COMPACTION_TOKEN_CAP else None

CONTEXT_COMPACTION_RETENTION_PERCENTAGE = min(
    50, max(10, int(os.getenv('CONTEXT_COMPACTION_RETENTION_PERCENTAGE', '40')))
)

CONTEXT_COMPACTION_PROMPT_TEMPLATE = os.getenv('CONTEXT_COMPACTION_PROMPT_TEMPLATE', '')

TITLE_GENERATION_PROMPT_TEMPLATE = os.getenv('TITLE_GENERATION_PROMPT_TEMPLATE', '')

DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE = """### Task:
Generate a concise title summarizing the chat history.
### Guidelines:
- The title should clearly represent the main theme or subject of the conversation.
- Keep it short: 2-4 words is best.
- Do not use emojis, quotation marks, or special formatting.
- Write the title in the chat's primary language; default to English if multilingual.
- Prioritize accuracy over creativity.
- Your entire response must consist solely of the JSON object, without any introductory or concluding text.
- The output must be a single, raw JSON object, without any markdown code fences or other encapsulating text.
- Ensure no conversational text, affirmations, or explanations precede or follow the raw JSON output, as this will cause direct parsing failure.
### Output:
JSON format: { "title": "your concise title here" }
### Examples:
- { "title": "Stock Trends" },
- { "title": "Chocolate Chip Cookies" },
- { "title": "Music Streaming" },
- { "title": "Remote Work" }
### Chat History:
<chat_history>
{{MESSAGES:END:2}}
</chat_history>"""

TAGS_GENERATION_PROMPT_TEMPLATE = os.getenv('TAGS_GENERATION_PROMPT_TEMPLATE', '')

DEFAULT_TAGS_GENERATION_PROMPT_TEMPLATE = """### Task:
Generate 1-3 broad tags categorizing the main themes of the chat history, along with 1-3 more specific subtopic tags.

### Guidelines:
- Start with high-level domains (e.g. Science, Technology, Philosophy, Arts, Politics, Business, Health, Sports, Entertainment, Education)
- Consider including relevant subfields/subdomains if they are strongly represented throughout the conversation
- If content is too short (less than 3 messages) or too diverse, use only ["General"]
- Use the chat's primary language; default to English if multilingual
- Prioritize accuracy over specificity

### Output:
JSON format: { "tags": ["tag1", "tag2", "tag3"] }

### Chat History:
<chat_history>
{{MESSAGES:END:6}}
</chat_history>"""

IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE = os.getenv('IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE', '')

DEFAULT_IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE = """### Task:
Generate a detailed prompt for am image generation task based on the given language and context. Describe the image as if you were explaining it to someone who cannot see it. Include relevant details, colors, shapes, and any other important elements.

### Guidelines:
- Be descriptive and detailed, focusing on the most important aspects of the image.
- Avoid making assumptions or adding information not present in the image.
- Use the chat's primary language; default to English if multilingual.
- If the image is too complex, focus on the most prominent elements.

### Output:
Strictly return in JSON format:
{
    "prompt": "Your detailed description here."
}

### Chat History:
<chat_history>
{{MESSAGES:END:6}}
</chat_history>"""


FOLLOW_UP_GENERATION_PROMPT_TEMPLATE = os.getenv('FOLLOW_UP_GENERATION_PROMPT_TEMPLATE', '')

DEFAULT_FOLLOW_UP_GENERATION_PROMPT_TEMPLATE = """### Task:
Suggest 3-5 relevant follow-up questions or prompts that the user might naturally ask next in this conversation as a **user**, based on the chat history, to help continue or deepen the discussion.
### Guidelines:
- Write all follow-up questions from the user’s point of view, directed to the assistant.
- Make questions concise, clear, and directly related to the discussed topic(s).
- Only suggest follow-ups that make sense given the chat content and do not repeat what was already covered.
- If the conversation is very short or not specific, suggest more general (but relevant) follow-ups the user might ask.
- Use the conversation's primary language; default to English if multilingual.
- Response must be a JSON object with a "follow_ups" key containing an array of strings, no extra text or formatting.
### Output:
JSON format: { "follow_ups": ["Question 1?", "Question 2?", "Question 3?"] }
### Chat History:
<chat_history>
{{MESSAGES:END:6}}
</chat_history>"""

ENABLE_FOLLOW_UP_GENERATION = os.getenv('ENABLE_FOLLOW_UP_GENERATION', 'True').lower() == 'true'

ENABLE_TAGS_GENERATION = os.getenv('ENABLE_TAGS_GENERATION', 'True').lower() == 'true'

ENABLE_TITLE_GENERATION = os.getenv('ENABLE_TITLE_GENERATION', 'True').lower() == 'true'


ENABLE_AUTOCOMPLETE_GENERATION = os.getenv('ENABLE_AUTOCOMPLETE_GENERATION', 'False').lower() == 'true'

AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH = int(os.getenv('AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH', '-1'))

AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE = os.getenv('AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE', '')


DEFAULT_AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE = """### Task:
You are an autocompletion system. Continue the text in `<text>` based on the **completion type** in `<type>` and the given language.  

### **Instructions**:
1. Analyze `<text>` for context and meaning.  
2. Use `<type>` to guide your output:  
   - **General**: Provide a natural, concise continuation.  
   - **Search Query**: Complete as if generating a realistic search query.  
3. Start as if you are directly continuing `<text>`. Do **not** repeat, paraphrase, or respond as a model. Simply complete the text.  
4. Ensure the continuation:
   - Flows naturally from `<text>`.  
   - Avoids repetition, overexplaining, or unrelated ideas.  
5. If unsure, return: `{ "text": "" }`.  

### **Output Rules**:
- Respond only in JSON format: `{ "text": "<your_completion>" }`.

### **Examples**:
#### Example 1:  
Input:  
<type>General</type>  
<text>The sun was setting over the horizon, painting the sky</text>  
Output:  
{ "text": "with vibrant shades of orange and pink." }

#### Example 2:  
Input:  
<type>Search Query</type>  
<text>Top-rated restaurants in</text>  
Output:  
{ "text": "New York City for Italian cuisine." }  

---
### Context:
<chat_history>
{{MESSAGES:END:6}}
</chat_history>
<type>{{TYPE}}</type>  
<text>{{PROMPT}}</text>  
#### Output:
"""


VOICE_MODE_PROMPT_TEMPLATE = os.getenv('VOICE_MODE_PROMPT_TEMPLATE', '')

ENABLE_VOICE_MODE_PROMPT = os.getenv('ENABLE_VOICE_MODE_PROMPT', 'True').lower() == 'true'

DEFAULT_VOICE_MODE_PROMPT_TEMPLATE = """You are a friendly, concise voice assistant.

Everything you say will be spoken aloud.
Keep responses short, clear, and natural.

STYLE:
- Use simple words and short sentences.
- Sound warm and conversational.
- Avoid long explanations, lists, or complex phrasing.

BEHAVIOR:
- Give the quickest helpful answer first.
- Offer extra detail only if needed.
- Ask for clarification only when necessary.

VOICE OPTIMIZATION:
- Break information into small, easy-to-hear chunks.
- Avoid dense wording or anything that sounds like reading text.

ERROR HANDLING:
- If unsure, say so briefly and offer options.
- If something is unsafe or impossible, decline kindly and suggest a safe alternative.

Stay consistent, helpful, and easy to listen to."""

TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE = os.getenv('TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE', '')


DEFAULT_TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE = """Available Tools: {{TOOLS}}

Your task is to choose and return the correct tool(s) from the list of available tools based on the query. Follow these guidelines:

- Return only the JSON object, without any additional text or explanation.

- If no tools match the query, return an empty array: 
   {
     "tool_calls": []
   }

- If one or more tools match the query, construct a JSON response containing a "tool_calls" array with objects that include:
   - "name": The tool's name.
   - "parameters": A dictionary of required parameters and their corresponding values.

The format for the JSON response is strictly:
{
  "tool_calls": [
    {"name": "toolName1", "parameters": {"key1": "value1"}},
    {"name": "toolName2", "parameters": {"key2": "value2"}}
  ]
}"""


DEFAULT_EMOJI_GENERATION_PROMPT_TEMPLATE = """Your task is to reflect the speaker's likely facial expression through a fitting emoji. Interpret emotions from the message and reflect their facial expression using fitting, diverse emojis (e.g., 😊, 😢, 😡, 😱).

Message: ```{{prompt}}```"""

DEFAULT_MOA_GENERATION_PROMPT_TEMPLATE = """You have been provided with a set of responses from various models to the latest user query: "{{prompt}}"

Your task is to synthesize these responses into a single, high-quality response. It is crucial to critically evaluate the information provided in these responses, recognizing that some of it may be biased or incorrect. Your response should not simply replicate the given answers but should offer a refined, accurate, and comprehensive reply to the instruction. Ensure your response is well-structured, coherent, and adheres to the highest standards of accuracy and reliability.

Responses from models: {{responses}}"""


####################################
# Auth
####################################

ENABLE_API_KEYS = os.getenv('ENABLE_API_KEYS', 'False').lower() == 'true'

ENABLE_API_KEYS_ENDPOINT_RESTRICTIONS = (
    os.getenv(
        'ENABLE_API_KEYS_ENDPOINT_RESTRICTIONS',
        os.getenv('ENABLE_API_KEY_ENDPOINT_RESTRICTIONS', 'False'),
    ).lower()
    == 'true'
)

API_KEYS_ALLOWED_ENDPOINTS = os.getenv('API_KEYS_ALLOWED_ENDPOINTS', os.getenv('API_KEY_ALLOWED_ENDPOINTS', ''))

JWT_EXPIRES_IN = os.getenv('JWT_EXPIRES_IN', '4w')

if JWT_EXPIRES_IN == '-1':
    log.warning(
        "⚠️  SECURITY WARNING: JWT_EXPIRES_IN is set to '-1'\n"
        '    See: https://docs.openwebui.com/reference/env-configuration\n'
    )

####################################
# OAuth config
####################################

# Master switch for OAuth/OIDC sign-in. Defaults to enabled so existing
# deployments that already have a provider configured keep working; admins can
# turn it off to disable OAuth login without clearing their provider settings.
ENABLE_OAUTH = os.getenv('ENABLE_OAUTH', 'True').lower() == 'true'

ENABLE_OAUTH_SIGNUP = os.getenv('ENABLE_OAUTH_SIGNUP', 'False').lower() == 'true'

OAUTH_AUTO_REDIRECT = os.getenv('OAUTH_AUTO_REDIRECT', 'False').lower() == 'true'

OAUTH_REFRESH_TOKEN_INCLUDE_SCOPE = os.getenv('OAUTH_REFRESH_TOKEN_INCLUDE_SCOPE', 'False').lower() == 'true'


OAUTH_MERGE_ACCOUNTS_BY_EMAIL = os.getenv('OAUTH_MERGE_ACCOUNTS_BY_EMAIL', 'False').lower() == 'true'

OAUTH_PROVIDERS = {}

GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')

GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')


GOOGLE_OAUTH_SCOPE = os.getenv('GOOGLE_OAUTH_SCOPE', 'openid email profile')

GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', '')

GOOGLE_OAUTH_AUTHORIZE_PARAMS = {}
_google_oauth_authorize_params = os.getenv('GOOGLE_OAUTH_AUTHORIZE_PARAMS', '')
if _google_oauth_authorize_params:
    try:
        _parsed = JSONCodec.loads(_google_oauth_authorize_params)
        if isinstance(_parsed, dict):
            GOOGLE_OAUTH_AUTHORIZE_PARAMS = _parsed
        else:
            log.warning('GOOGLE_OAUTH_AUTHORIZE_PARAMS must be a JSON object, ignoring')
    except (JSONCodec.JSONDecodeError, TypeError):
        log.warning('GOOGLE_OAUTH_AUTHORIZE_PARAMS is not valid JSON, ignoring')

MICROSOFT_CLIENT_ID = os.getenv('MICROSOFT_CLIENT_ID', '')

MICROSOFT_CLIENT_SECRET = os.getenv('MICROSOFT_CLIENT_SECRET', '')

MICROSOFT_CLIENT_TENANT_ID = os.getenv('MICROSOFT_CLIENT_TENANT_ID', '')

MICROSOFT_CLIENT_LOGIN_BASE_URL = os.getenv('MICROSOFT_CLIENT_LOGIN_BASE_URL', 'https://login.microsoftonline.com')

MICROSOFT_CLIENT_PICTURE_URL = os.getenv(
    'MICROSOFT_CLIENT_PICTURE_URL',
    'https://graph.microsoft.com/v1.0/me/photo/$value',
)


MICROSOFT_OAUTH_SCOPE = os.getenv('MICROSOFT_OAUTH_SCOPE', 'openid email profile')

MICROSOFT_REDIRECT_URI = os.getenv('MICROSOFT_REDIRECT_URI', '')

GITHUB_CLIENT_ID = os.getenv('GITHUB_CLIENT_ID', '')

GITHUB_CLIENT_SECRET = os.getenv('GITHUB_CLIENT_SECRET', '')

GITHUB_CLIENT_SCOPE = os.getenv('GITHUB_CLIENT_SCOPE', 'user:email')

GITHUB_CLIENT_REDIRECT_URI = os.getenv('GITHUB_CLIENT_REDIRECT_URI', '')

OAUTH_CLIENT_ID = os.getenv('OAUTH_CLIENT_ID', '')

OAUTH_CLIENT_SECRET = os.getenv('OAUTH_CLIENT_SECRET', '')

OPENID_PROVIDER_URL = os.getenv('OPENID_PROVIDER_URL', '')

OPENID_END_SESSION_ENDPOINT = os.getenv('OPENID_END_SESSION_ENDPOINT', '')

OPENID_REDIRECT_URI = os.getenv('OPENID_REDIRECT_URI', '')

OAUTH_SCOPES = os.getenv('OAUTH_SCOPES', 'openid email profile')

OAUTH_TIMEOUT = os.getenv('OAUTH_TIMEOUT', '')

OAUTH_TOKEN_ENDPOINT_AUTH_METHOD = os.getenv('OAUTH_TOKEN_ENDPOINT_AUTH_METHOD', None)

OAUTH_CODE_CHALLENGE_METHOD = os.getenv('OAUTH_CODE_CHALLENGE_METHOD', None)

OAUTH_PROVIDER_NAME = os.getenv('OAUTH_PROVIDER_NAME', 'SSO')

OAUTH_SUB_CLAIM = os.getenv('OAUTH_SUB_CLAIM', None)

OAUTH_USERNAME_CLAIM = os.getenv('OAUTH_USERNAME_CLAIM', 'name')


OAUTH_PICTURE_CLAIM = os.getenv('OAUTH_PICTURE_CLAIM', 'picture')

OAUTH_EMAIL_CLAIM = os.getenv('OAUTH_EMAIL_CLAIM', 'email')

OAUTH_GROUPS_CLAIM = os.getenv('OAUTH_GROUPS_CLAIM', os.getenv('OAUTH_GROUP_CLAIM', 'groups'))

FEISHU_CLIENT_ID = os.getenv('FEISHU_CLIENT_ID', '')

FEISHU_CLIENT_SECRET = os.getenv('FEISHU_CLIENT_SECRET', '')

FEISHU_OAUTH_SCOPE = os.getenv('FEISHU_OAUTH_SCOPE', 'contact:user.base:readonly')

FEISHU_REDIRECT_URI = os.getenv('FEISHU_REDIRECT_URI', '')

ENABLE_OAUTH_ROLE_MANAGEMENT = os.getenv('ENABLE_OAUTH_ROLE_MANAGEMENT', 'False').lower() == 'true'

ENABLE_OAUTH_GROUP_MANAGEMENT = os.getenv('ENABLE_OAUTH_GROUP_MANAGEMENT', 'False').lower() == 'true'

ENABLE_OAUTH_GROUP_CREATION = os.getenv('ENABLE_OAUTH_GROUP_CREATION', 'False').lower() == 'true'


oauth_group_default_share = os.getenv('OAUTH_GROUP_DEFAULT_SHARE', 'true').strip().lower()
OAUTH_GROUP_DEFAULT_SHARE = 'members' if oauth_group_default_share == 'members' else oauth_group_default_share == 'true'


OAUTH_BLOCKED_GROUPS = os.getenv('OAUTH_BLOCKED_GROUPS', '[]')

OAUTH_GROUPS_SEPARATOR = os.getenv('OAUTH_GROUPS_SEPARATOR', ';')

OAUTH_ROLES_CLAIM = os.getenv('OAUTH_ROLES_CLAIM', 'roles')

OAUTH_ROLES_SEPARATOR = os.getenv('OAUTH_ROLES_SEPARATOR', ',')

OAUTH_ALLOWED_ROLES = [
    role.strip()
    for role in os.getenv('OAUTH_ALLOWED_ROLES', f'user{OAUTH_ROLES_SEPARATOR}admin').split(OAUTH_ROLES_SEPARATOR)
    if role
]

OAUTH_ADMIN_ROLES = [
    role.strip() for role in os.getenv('OAUTH_ADMIN_ROLES', 'admin').split(OAUTH_ROLES_SEPARATOR) if role
]

OAUTH_ALLOWED_DOMAINS = [domain.strip() for domain in os.getenv('OAUTH_ALLOWED_DOMAINS', '*').split(',')]

OAUTH_UPDATE_PICTURE_ON_LOGIN = os.getenv('OAUTH_UPDATE_PICTURE_ON_LOGIN', 'False').lower() == 'true'

OAUTH_UPDATE_NAME_ON_LOGIN = os.getenv('OAUTH_UPDATE_NAME_ON_LOGIN', 'False').lower() == 'true'

OAUTH_UPDATE_EMAIL_ON_LOGIN = os.getenv('OAUTH_UPDATE_EMAIL_ON_LOGIN', 'False').lower() == 'true'

OAUTH_ACCESS_TOKEN_REQUEST_INCLUDE_CLIENT_ID = (
    os.getenv('OAUTH_ACCESS_TOKEN_REQUEST_INCLUDE_CLIENT_ID', 'False').lower() == 'true'
)

OAUTH_AUDIENCE = os.getenv('OAUTH_AUDIENCE', '')

OAUTH_AUTHORIZE_PARAMS = {}
_oauth_authorize_params = os.getenv('OAUTH_AUTHORIZE_PARAMS', '')
if _oauth_authorize_params:
    try:
        _parsed = JSONCodec.loads(_oauth_authorize_params)
        if isinstance(_parsed, dict):
            OAUTH_AUTHORIZE_PARAMS = _parsed
        else:
            log.warning('OAUTH_AUTHORIZE_PARAMS must be a JSON object, ignoring')
    except (JSONCodec.JSONDecodeError, TypeError):
        log.warning('OAUTH_AUTHORIZE_PARAMS is not valid JSON, ignoring')


def oauth_client_kwargs(scope: str, **kwargs):
    client_kwargs = {
        'scope': scope,
        **kwargs,
        **({'timeout': int(OAUTH_TIMEOUT)} if OAUTH_TIMEOUT else {}),
    }

    if OAUTH_CODE_CHALLENGE_METHOD == 'S256':
        client_kwargs['code_challenge_method'] = 'S256'
    elif OAUTH_CODE_CHALLENGE_METHOD:
        raise Exception(
            'Code challenge methods other than "%s" not supported. Given: "%s"' % ('S256', OAUTH_CODE_CHALLENGE_METHOD)
        )

    return client_kwargs


def load_oauth_providers():
    OAUTH_PROVIDERS.clear()
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:

        def google_oauth_register(oauth: OAuth):
            client = oauth.register(
                name='google',
                client_id=GOOGLE_CLIENT_ID,
                client_secret=GOOGLE_CLIENT_SECRET,
                server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
                client_kwargs=oauth_client_kwargs(GOOGLE_OAUTH_SCOPE),
                redirect_uri=GOOGLE_REDIRECT_URI,
                **({'authorize_params': GOOGLE_OAUTH_AUTHORIZE_PARAMS} if GOOGLE_OAUTH_AUTHORIZE_PARAMS else {}),
            )
            return client

        OAUTH_PROVIDERS['google'] = {
            'register': google_oauth_register,
        }

    if MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET and MICROSOFT_CLIENT_TENANT_ID:

        def microsoft_oauth_register(oauth: OAuth):
            client = oauth.register(
                name='microsoft',
                client_id=MICROSOFT_CLIENT_ID,
                client_secret=MICROSOFT_CLIENT_SECRET,
                server_metadata_url=f'{MICROSOFT_CLIENT_LOGIN_BASE_URL}/{MICROSOFT_CLIENT_TENANT_ID}/v2.0/.well-known/openid-configuration?appid={MICROSOFT_CLIENT_ID}',
                client_kwargs=oauth_client_kwargs(MICROSOFT_OAUTH_SCOPE),
                redirect_uri=MICROSOFT_REDIRECT_URI,
            )
            return client

        OAUTH_PROVIDERS['microsoft'] = {
            'picture_url': MICROSOFT_CLIENT_PICTURE_URL,
            'register': microsoft_oauth_register,
        }

    if GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET:

        def github_oauth_register(oauth: OAuth):
            client = oauth.register(
                name='github',
                client_id=GITHUB_CLIENT_ID,
                client_secret=GITHUB_CLIENT_SECRET,
                access_token_url='https://github.com/login/oauth/access_token',
                authorize_url='https://github.com/login/oauth/authorize',
                api_base_url='https://api.github.com',
                userinfo_endpoint='https://api.github.com/user',
                client_kwargs=oauth_client_kwargs(GITHUB_CLIENT_SCOPE),
                redirect_uri=GITHUB_CLIENT_REDIRECT_URI,
            )
            return client

        OAUTH_PROVIDERS['github'] = {
            'register': github_oauth_register,
            'sub_claim': 'id',
        }

    if OAUTH_CLIENT_ID and (OAUTH_CLIENT_SECRET or OAUTH_CODE_CHALLENGE_METHOD) and OPENID_PROVIDER_URL:

        def oidc_oauth_register(oauth: OAuth):
            client = oauth.register(
                name='oidc',
                client_id=OAUTH_CLIENT_ID,
                client_secret=OAUTH_CLIENT_SECRET,
                server_metadata_url=OPENID_PROVIDER_URL,
                client_kwargs=oauth_client_kwargs(
                    OAUTH_SCOPES,
                    **(
                        {'token_endpoint_auth_method': OAUTH_TOKEN_ENDPOINT_AUTH_METHOD}
                        if OAUTH_TOKEN_ENDPOINT_AUTH_METHOD
                        else {}
                    ),
                ),
                redirect_uri=OPENID_REDIRECT_URI,
            )
            return client

        OAUTH_PROVIDERS['oidc'] = {
            'name': OAUTH_PROVIDER_NAME,
            'register': oidc_oauth_register,
        }

    if FEISHU_CLIENT_ID and FEISHU_CLIENT_SECRET:

        def feishu_oauth_register(oauth: OAuth):
            client = oauth.register(
                name='feishu',
                client_id=FEISHU_CLIENT_ID,
                client_secret=FEISHU_CLIENT_SECRET,
                access_token_url='https://open.feishu.cn/open-apis/authen/v2/oauth/token',
                authorize_url='https://accounts.feishu.cn/open-apis/authen/v1/authorize',
                api_base_url='https://open.feishu.cn/open-apis',
                userinfo_endpoint='https://open.feishu.cn/open-apis/authen/v1/user_info',
                client_kwargs={
                    'scope': FEISHU_OAUTH_SCOPE,
                    **({'timeout': int(OAUTH_TIMEOUT)} if OAUTH_TIMEOUT else {}),
                },
                redirect_uri=FEISHU_REDIRECT_URI,
            )
            return client

        OAUTH_PROVIDERS['feishu'] = {
            'register': feishu_oauth_register,
            'sub_claim': 'user_id',
        }

    configured_providers = []
    if GOOGLE_CLIENT_ID:
        configured_providers.append('Google')
    if MICROSOFT_CLIENT_ID:
        configured_providers.append('Microsoft')
    if GITHUB_CLIENT_ID:
        configured_providers.append('GitHub')
    if FEISHU_CLIENT_ID:
        configured_providers.append('Feishu')

    if configured_providers and not OPENID_PROVIDER_URL and not OPENID_END_SESSION_ENDPOINT:
        provider_list = ', '.join(configured_providers)
        log.warning(
            f'⚠️  OAuth providers configured ({provider_list}) but OPENID_PROVIDER_URL not set - logout will not work!'
        )
        log.warning(
            f"Set OPENID_PROVIDER_URL to your OAuth provider's OpenID Connect discovery endpoint,"
            f' or set OPENID_END_SESSION_ENDPOINT to a custom logout URL to fix logout functionality.'
        )


load_oauth_providers()

####################################
# LDAP
####################################

ENABLE_LDAP = os.getenv('ENABLE_LDAP', 'false').lower() == 'true'

LDAP_SERVER_LABEL = os.getenv('LDAP_SERVER_LABEL', 'LDAP Server')

LDAP_SERVER_HOST = os.getenv('LDAP_SERVER_HOST', 'localhost')

LDAP_SERVER_PORT = int(os.getenv('LDAP_SERVER_PORT', '389'))

LDAP_ATTRIBUTE_FOR_MAIL = os.getenv('LDAP_ATTRIBUTE_FOR_MAIL', 'mail')

LDAP_ATTRIBUTE_FOR_USERNAME = os.getenv('LDAP_ATTRIBUTE_FOR_USERNAME', 'uid')

LDAP_APP_DN = os.getenv('LDAP_APP_DN', '')

LDAP_APP_PASSWORD = os.getenv('LDAP_APP_PASSWORD', '')

LDAP_SEARCH_BASE = os.getenv('LDAP_SEARCH_BASE', '')

LDAP_SEARCH_FILTERS = os.getenv('LDAP_SEARCH_FILTER', os.getenv('LDAP_SEARCH_FILTERS', ''))

LDAP_USE_TLS = os.getenv('LDAP_USE_TLS', 'True').lower() == 'true'

LDAP_CA_CERT_FILE = os.getenv('LDAP_CA_CERT_FILE', '')

LDAP_VALIDATE_CERT = os.getenv('LDAP_VALIDATE_CERT', 'True').lower() == 'true'

LDAP_CIPHERS = os.getenv('LDAP_CIPHERS', 'ALL')

ENABLE_LDAP_GROUP_MANAGEMENT = os.getenv('ENABLE_LDAP_GROUP_MANAGEMENT', 'False').lower() == 'true'

ENABLE_LDAP_GROUP_CREATION = os.getenv('ENABLE_LDAP_GROUP_CREATION', 'False').lower() == 'true'

LDAP_ATTRIBUTE_FOR_GROUPS = os.getenv('LDAP_ATTRIBUTE_FOR_GROUPS', 'memberOf')

try:
    TATER_CONTEXT_WINDOW = normalize_tater_context_window(
        os.getenv('TATER_CONTEXT_WINDOW', str(DEFAULT_TATER_CONTEXT_WINDOW))
    )
except ValueError:
    TATER_CONTEXT_WINDOW = DEFAULT_TATER_CONTEXT_WINDOW

DEFAULT_CONFIG = {
    'openai.enable': ENABLE_OPENAI_API,
    'openai.api_keys': OPENAI_API_KEYS,
    'openai.api_base_urls': OPENAI_API_BASE_URLS,
    'openai.api_configs': OPENAI_API_CONFIGS,
    'tater.base_model': DEFAULT_MODELS,
    'tater.hydra_model': os.getenv('TATER_HYDRA_MODEL', DEFAULT_TATER_HYDRA_MODEL),
    'tater.context_window': TATER_CONTEXT_WINDOW,
    'models.base_models_cache': ENABLE_BASE_MODELS_CACHE,
    'tool_server.connections': TOOL_SERVER_CONNECTIONS,
    'oauth.client.timeout': OAUTH_CLIENT_TIMEOUT,
    'terminal_server.connections': TERMINAL_SERVER_CONNECTIONS,
    'code_execution.enable': ENABLE_CODE_EXECUTION,
    'code_execution.engine': CODE_EXECUTION_ENGINE,
    'code_execution.jupyter.url': CODE_EXECUTION_JUPYTER_URL,
    'code_execution.jupyter.auth': CODE_EXECUTION_JUPYTER_AUTH,
    'code_execution.jupyter.auth_token': CODE_EXECUTION_JUPYTER_AUTH_TOKEN,
    'code_execution.jupyter.auth_password': CODE_EXECUTION_JUPYTER_AUTH_PASSWORD,
    'code_execution.jupyter.timeout': CODE_EXECUTION_JUPYTER_TIMEOUT,
    'code_interpreter.enable': ENABLE_CODE_INTERPRETER,
    'code_interpreter.engine': CODE_INTERPRETER_ENGINE,
    'code_interpreter.prompt_template': CODE_INTERPRETER_PROMPT_TEMPLATE,
    'code_interpreter.jupyter.url': CODE_INTERPRETER_JUPYTER_URL,
    'code_interpreter.jupyter.auth': CODE_INTERPRETER_JUPYTER_AUTH,
    'code_interpreter.jupyter.auth_token': CODE_INTERPRETER_JUPYTER_AUTH_TOKEN,
    'code_interpreter.jupyter.auth_password': CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD,
    'code_interpreter.jupyter.timeout': CODE_INTERPRETER_JUPYTER_TIMEOUT,
    'google_drive.enable': ENABLE_GOOGLE_DRIVE_INTEGRATION,
    'google_drive.client_id': GOOGLE_DRIVE_CLIENT_ID,
    'google_drive.api_key': GOOGLE_DRIVE_API_KEY,
    'onedrive.enable': ENABLE_ONEDRIVE_INTEGRATION,
    'onedrive.sharepoint_url': ONEDRIVE_SHAREPOINT_URL,
    'onedrive.sharepoint_tenant_id': ONEDRIVE_SHAREPOINT_TENANT_ID,
    'rag.content_extraction_engine': CONTENT_EXTRACTION_ENGINE,
    'rag.content_extraction.supported_media_mime_types': CONTENT_EXTRACTION_SUPPORTED_MEDIA_MIME_TYPES,
    'rag.datalab_marker_api_key': DATALAB_MARKER_API_KEY,
    'rag.datalab_marker_api_base_url': DATALAB_MARKER_API_BASE_URL,
    'rag.datalab_marker_additional_config': DATALAB_MARKER_ADDITIONAL_CONFIG,
    'rag.datalab_marker_use_llm': DATALAB_MARKER_USE_LLM,
    'rag.datalab_marker_skip_cache': DATALAB_MARKER_SKIP_CACHE,
    'rag.datalab_marker_force_ocr': DATALAB_MARKER_FORCE_OCR,
    'rag.datalab_marker_paginate': DATALAB_MARKER_PAGINATE,
    'rag.datalab_marker_strip_existing_ocr': DATALAB_MARKER_STRIP_EXISTING_OCR,
    'rag.datalab_marker_disable_image_extraction': DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION,
    'rag.datalab_marker_format_lines': DATALAB_MARKER_FORMAT_LINES,
    'rag.datalab_marker_output_format': DATALAB_MARKER_OUTPUT_FORMAT,
    'rag.mineru_api_mode': MINERU_API_MODE,
    'rag.mineru_api_url': MINERU_API_URL,
    'rag.mineru_api_timeout': MINERU_API_TIMEOUT,
    'rag.mineru_api_key': MINERU_API_KEY,
    'rag.mineru_params': MINERU_PARAMS,
    'rag.mineru_file_extensions': MINERU_FILE_EXTENSIONS,
    'rag.external_document_loader_url': EXTERNAL_DOCUMENT_LOADER_URL,
    'rag.external_document_loader_api_key': EXTERNAL_DOCUMENT_LOADER_API_KEY,
    'rag.external_document_loader_headers': EXTERNAL_DOCUMENT_LOADER_HEADERS,
    'rag.tika_server_url': TIKA_SERVER_URL,
    'rag.tika_server_version': TIKA_SERVER_VERSION,
    'rag.docling_server_url': DOCLING_SERVER_URL,
    'rag.docling_api_key': DOCLING_API_KEY,
    'rag.docling_params': DOCLING_PARAMS,
    'rag.document_intelligence_endpoint': DOCUMENT_INTELLIGENCE_ENDPOINT,
    'rag.document_intelligence_key': DOCUMENT_INTELLIGENCE_KEY,
    'rag.document_intelligence_model': DOCUMENT_INTELLIGENCE_MODEL,
    'rag.mistral_ocr_api_base_url': MISTRAL_OCR_API_BASE_URL,
    'rag.mistral_ocr_api_key': MISTRAL_OCR_API_KEY,
    'rag.mistral_ocr_use_base64': MISTRAL_OCR_USE_BASE64,
    'rag.paddleocr_vl_base_url': PADDLEOCR_VL_BASE_URL,
    'rag.paddleocr_vl_token': PADDLEOCR_VL_TOKEN,
    'rag.file.max_count': RAG_FILE_MAX_COUNT,
    'rag.file.max_size': RAG_FILE_MAX_SIZE,
    'file.image_compression_width': FILE_IMAGE_COMPRESSION_WIDTH,
    'file.image_compression_height': FILE_IMAGE_COMPRESSION_HEIGHT,
    'rag.file.allowed_extensions': RAG_ALLOWED_FILE_EXTENSIONS,
    'rag.pdf_extract_images': PDF_EXTRACT_IMAGES,
    'rag.pdf_loader_mode': PDF_LOADER_MODE,
    'image_generation.enable': ENABLE_IMAGE_GENERATION,
    'image_generation.engine': IMAGE_GENERATION_ENGINE,
    'image_generation.model': IMAGE_GENERATION_MODEL,
    'image_generation.size': IMAGE_SIZE,
    'image_generation.steps': IMAGE_STEPS,
    'image_generation.prompt.enable': ENABLE_IMAGE_PROMPT_GENERATION,
    'image_generation.automatic1111.base_url': AUTOMATIC1111_BASE_URL,
    'image_generation.automatic1111.api_auth': AUTOMATIC1111_API_AUTH,
    'image_generation.automatic1111.api_params': AUTOMATIC1111_PARAMS,
    'image_generation.comfyui.base_url': COMFYUI_BASE_URL,
    'image_generation.comfyui.api_key': COMFYUI_API_KEY,
    'image_generation.comfyui.workflow': COMFYUI_WORKFLOW,
    'image_generation.comfyui.nodes': COMFYUI_WORKFLOW_NODES,
    'image_generation.openai.api_base_url': IMAGES_OPENAI_API_BASE_URL,
    'image_generation.openai.api_version': IMAGES_OPENAI_API_VERSION,
    'image_generation.openai.api_key': IMAGES_OPENAI_API_KEY,
    'image_generation.openai.params': IMAGES_OPENAI_API_PARAMS,
    'image_generation.gemini.api_base_url': IMAGES_GEMINI_API_BASE_URL,
    'image_generation.gemini.api_key': IMAGES_GEMINI_API_KEY,
    'image_generation.gemini.endpoint_method': IMAGES_GEMINI_ENDPOINT_METHOD,
    'images.edit.enable': ENABLE_IMAGE_EDIT,
    'images.edit.engine': IMAGE_EDIT_ENGINE,
    'images.edit.model': IMAGE_EDIT_MODEL,
    'images.edit.size': IMAGE_EDIT_SIZE,
    'images.edit.openai.api_base_url': IMAGES_EDIT_OPENAI_API_BASE_URL,
    'images.edit.openai.api_version': IMAGES_EDIT_OPENAI_API_VERSION,
    'images.edit.openai.api_key': IMAGES_EDIT_OPENAI_API_KEY,
    'images.edit.gemini.api_base_url': IMAGES_EDIT_GEMINI_API_BASE_URL,
    'images.edit.gemini.api_key': IMAGES_EDIT_GEMINI_API_KEY,
    'images.edit.comfyui.base_url': IMAGES_EDIT_COMFYUI_BASE_URL,
    'images.edit.comfyui.api_key': IMAGES_EDIT_COMFYUI_API_KEY,
    'images.edit.comfyui.workflow': IMAGES_EDIT_COMFYUI_WORKFLOW,
    'images.edit.comfyui.nodes': IMAGES_EDIT_COMFYUI_WORKFLOW_NODES,
    'audio.stt.whisper_model': WHISPER_MODEL,
    'audio.stt.deepgram.api_key': DEEPGRAM_API_KEY,
    'audio.stt.openai.api_base_url': AUDIO_STT_OPENAI_API_BASE_URL,
    'audio.stt.openai.api_key': AUDIO_STT_OPENAI_API_KEY,
    'audio.stt.openai.api_request_format': AUDIO_STT_OPENAI_API_REQUEST_FORMAT,
    'audio.stt.engine': AUDIO_STT_ENGINE,
    'audio.stt.model': AUDIO_STT_MODEL,
    'audio.stt.supported_content_types': AUDIO_STT_SUPPORTED_CONTENT_TYPES,
    'audio.stt.allowed_extensions': AUDIO_STT_ALLOWED_EXTENSIONS,
    'audio.stt.azure.api_key': AUDIO_STT_AZURE_API_KEY,
    'audio.stt.azure.region': AUDIO_STT_AZURE_REGION,
    'audio.stt.azure.locales': AUDIO_STT_AZURE_LOCALES,
    'audio.stt.azure.base_url': AUDIO_STT_AZURE_BASE_URL,
    'audio.stt.azure.max_speakers': AUDIO_STT_AZURE_MAX_SPEAKERS,
    'audio.stt.mistral.api_key': AUDIO_STT_MISTRAL_API_KEY,
    'audio.stt.mistral.api_base_url': AUDIO_STT_MISTRAL_API_BASE_URL,
    'audio.stt.mistral.use_chat_completions': AUDIO_STT_MISTRAL_USE_CHAT_COMPLETIONS,
    'audio.tts.openai.api_base_url': AUDIO_TTS_OPENAI_API_BASE_URL,
    'audio.tts.openai.api_key': AUDIO_TTS_OPENAI_API_KEY,
    'audio.tts.openai.params': AUDIO_TTS_OPENAI_PARAMS,
    'audio.tts.api_key': AUDIO_TTS_API_KEY,
    'audio.tts.engine': AUDIO_TTS_ENGINE,
    'audio.tts.model': AUDIO_TTS_MODEL,
    'audio.tts.voice': AUDIO_TTS_VOICE,
    'audio.tts.split_on': AUDIO_TTS_SPLIT_ON,
    'audio.tts.azure.speech_region': AUDIO_TTS_AZURE_SPEECH_REGION,
    'audio.tts.azure.speech_base_url': AUDIO_TTS_AZURE_SPEECH_BASE_URL,
    'audio.tts.azure.speech_output_format': AUDIO_TTS_AZURE_SPEECH_OUTPUT_FORMAT,
    'audio.tts.mistral.api_key': AUDIO_TTS_MISTRAL_API_KEY,
    'audio.tts.mistral.api_base_url': AUDIO_TTS_MISTRAL_API_BASE_URL,
    'webui.url': WEBUI_URL,
    'ui.enable_signup': ENABLE_SIGNUP,
    'ui.enable_login_form': ENABLE_LOGIN_FORM,
    'ui.enable_password_change_form': ENABLE_PASSWORD_CHANGE_FORM,
    'ui.default_locale': DEFAULT_LOCALE,
    'ui.default_models': DEFAULT_MODELS,
    'ui.default_pinned_models': DEFAULT_PINNED_MODELS,
    'ui.default_interface_settings': DEFAULT_INTERFACE_SETTINGS,
    'ui.i18n': {},
    'ui.prompt_suggestions': DEFAULT_PROMPT_SUGGESTIONS,
    'ui.prompt_suggestions_i18n': DEFAULT_PROMPT_SUGGESTIONS_I18N,
    'ui.model_order_list': MODEL_ORDER_LIST,
    'models.default_metadata': DEFAULT_MODEL_METADATA,
    'models.default_params': DEFAULT_MODEL_PARAMS,
    'ui.default_user_role': DEFAULT_USER_ROLE,
    'ui.default_group_id': DEFAULT_GROUP_ID,
    'ui.pending_user_overlay_title': PENDING_USER_OVERLAY_TITLE,
    'ui.pending_user_overlay_content': PENDING_USER_OVERLAY_CONTENT,
    'ui.watermark': RESPONSE_WATERMARK,
    'user.permissions': USER_PERMISSIONS,
    'folders.enable': ENABLE_FOLDERS,
    'folders.max_file_count': FOLDER_MAX_FILE_COUNT,
    'subagents.enable': ENABLE_SUBAGENTS,
    'subagents.background_enabled': SUBAGENTS_BACKGROUND_ENABLED,
    'subagents.max_concurrent': SUBAGENTS_MAX_CONCURRENT,
    'subagents.max_async': SUBAGENTS_MAX_ASYNC,
    'subagents.max_iterations': SUBAGENTS_MAX_ITERATIONS,
    'subagents.max_output': SUBAGENTS_MAX_OUTPUT,
    'subagents.system_prompt': SUBAGENTS_SYSTEM_PROMPT,
    'users.enable_status': ENABLE_USER_STATUS,
    'webhook_url': WEBHOOK_URL,
    'ui.enable_community_sharing': ENABLE_COMMUNITY_SHARING,
    'ui.enable_message_rating': ENABLE_MESSAGE_RATING,
    'ui.enable_user_webhooks': ENABLE_USER_WEBHOOKS,
    'ui.banners': WEBUI_BANNERS,
    'auth.admin.show': SHOW_ADMIN_DETAILS,
    'auth.admin.email': ADMIN_EMAIL,
    'task.model.default': TASK_MODEL,
    'task.model.external': TASK_MODEL_EXTERNAL,
    'task.model.params': TASK_MODEL_PARAMS,
    'chat.context_compaction.model': CONTEXT_COMPACTION_MODEL,
    'chat.context_compaction.enable': ENABLE_CONTEXT_COMPACTION,
    'chat.context_compaction.token_threshold': CONTEXT_COMPACTION_TOKEN_THRESHOLD,
    'chat.context_compaction.token_cap': CONTEXT_COMPACTION_TOKEN_CAP,
    'chat.context_compaction.retention_percentage': CONTEXT_COMPACTION_RETENTION_PERCENTAGE,
    'chat.context_compaction.prompt_template': CONTEXT_COMPACTION_PROMPT_TEMPLATE,
    'chat.tool_permissions.enable': ENABLE_TOOL_PERMISSIONS,
    'task.title.prompt_template': TITLE_GENERATION_PROMPT_TEMPLATE,
    'task.tags.prompt_template': TAGS_GENERATION_PROMPT_TEMPLATE,
    'task.image.prompt_template': IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE,
    'task.follow_up.prompt_template': FOLLOW_UP_GENERATION_PROMPT_TEMPLATE,
    'task.follow_up.enable': ENABLE_FOLLOW_UP_GENERATION,
    'task.tags.enable': ENABLE_TAGS_GENERATION,
    'task.title.enable': ENABLE_TITLE_GENERATION,
    'task.autocomplete.enable': ENABLE_AUTOCOMPLETE_GENERATION,
    'task.autocomplete.input_max_length': AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH,
    'task.autocomplete.prompt_template': AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE,
    'task.voice.prompt_template': VOICE_MODE_PROMPT_TEMPLATE,
    'task.voice.prompt.enable': ENABLE_VOICE_MODE_PROMPT,
    'task.tools.prompt_template': TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE,
    'auth.enable_api_keys': ENABLE_API_KEYS,
    'auth.api_key.endpoint_restrictions': ENABLE_API_KEYS_ENDPOINT_RESTRICTIONS,
    'auth.api_key.allowed_endpoints': API_KEYS_ALLOWED_ENDPOINTS,
    'auth.jwt_expiry': JWT_EXPIRES_IN,
    'oauth.enable': ENABLE_OAUTH,
    'oauth.enable_signup': ENABLE_OAUTH_SIGNUP,
    'oauth.auto_redirect': OAUTH_AUTO_REDIRECT,
    'oauth.refresh_token.include_scope': OAUTH_REFRESH_TOKEN_INCLUDE_SCOPE,
    'oauth.merge_accounts_by_email': OAUTH_MERGE_ACCOUNTS_BY_EMAIL,
    'oauth.google.client_id': GOOGLE_CLIENT_ID,
    'oauth.google.client_secret': GOOGLE_CLIENT_SECRET,
    'oauth.google.scope': GOOGLE_OAUTH_SCOPE,
    'oauth.google.redirect_uri': GOOGLE_REDIRECT_URI,
    'oauth.microsoft.client_id': MICROSOFT_CLIENT_ID,
    'oauth.microsoft.client_secret': MICROSOFT_CLIENT_SECRET,
    'oauth.microsoft.tenant_id': MICROSOFT_CLIENT_TENANT_ID,
    'oauth.microsoft.login_base_url': MICROSOFT_CLIENT_LOGIN_BASE_URL,
    'oauth.microsoft.picture_url': MICROSOFT_CLIENT_PICTURE_URL,
    'oauth.microsoft.scope': MICROSOFT_OAUTH_SCOPE,
    'oauth.microsoft.redirect_uri': MICROSOFT_REDIRECT_URI,
    'oauth.github.client_id': GITHUB_CLIENT_ID,
    'oauth.github.client_secret': GITHUB_CLIENT_SECRET,
    'oauth.github.scope': GITHUB_CLIENT_SCOPE,
    'oauth.github.redirect_uri': GITHUB_CLIENT_REDIRECT_URI,
    'oauth.client_id': OAUTH_CLIENT_ID,
    'oauth.client_secret': OAUTH_CLIENT_SECRET,
    'oauth.provider_url': OPENID_PROVIDER_URL,
    'oauth.end_session_endpoint': OPENID_END_SESSION_ENDPOINT,
    'oauth.redirect_uri': OPENID_REDIRECT_URI,
    'oauth.scopes': OAUTH_SCOPES,
    'oauth.timeout': OAUTH_TIMEOUT,
    'oauth.token_endpoint_auth_method': OAUTH_TOKEN_ENDPOINT_AUTH_METHOD,
    'oauth.code_challenge_method': OAUTH_CODE_CHALLENGE_METHOD,
    'oauth.provider_name': OAUTH_PROVIDER_NAME,
    'oauth.sub_claim': OAUTH_SUB_CLAIM,
    'oauth.username_claim': OAUTH_USERNAME_CLAIM,
    'oauth.picture_claim': OAUTH_PICTURE_CLAIM,
    'oauth.email_claim': OAUTH_EMAIL_CLAIM,
    'oauth.group_claim': OAUTH_GROUPS_CLAIM,
    'oauth.feishu.client_id': FEISHU_CLIENT_ID,
    'oauth.feishu.client_secret': FEISHU_CLIENT_SECRET,
    'oauth.feishu.scope': FEISHU_OAUTH_SCOPE,
    'oauth.feishu.redirect_uri': FEISHU_REDIRECT_URI,
    'oauth.enable_role_mapping': ENABLE_OAUTH_ROLE_MANAGEMENT,
    'oauth.enable_group_mapping': ENABLE_OAUTH_GROUP_MANAGEMENT,
    'oauth.enable_group_creation': ENABLE_OAUTH_GROUP_CREATION,
    'oauth.group_default_share': OAUTH_GROUP_DEFAULT_SHARE,
    'oauth.blocked_groups': OAUTH_BLOCKED_GROUPS,
    'oauth.roles_claim': OAUTH_ROLES_CLAIM,
    'oauth.allowed_roles': OAUTH_ALLOWED_ROLES,
    'oauth.admin_roles': OAUTH_ADMIN_ROLES,
    'oauth.allowed_domains': OAUTH_ALLOWED_DOMAINS,
    'oauth.update_picture_on_login': OAUTH_UPDATE_PICTURE_ON_LOGIN,
    'oauth.update_name_on_login': OAUTH_UPDATE_NAME_ON_LOGIN,
    'oauth.update_email_on_login': OAUTH_UPDATE_EMAIL_ON_LOGIN,
    'oauth.audience': OAUTH_AUDIENCE,
    'ldap.enable': ENABLE_LDAP,
    'ldap.server.label': LDAP_SERVER_LABEL,
    'ldap.server.host': LDAP_SERVER_HOST,
    'ldap.server.port': LDAP_SERVER_PORT,
    'ldap.server.attribute_for_mail': LDAP_ATTRIBUTE_FOR_MAIL,
    'ldap.server.attribute_for_username': LDAP_ATTRIBUTE_FOR_USERNAME,
    'ldap.server.app_dn': LDAP_APP_DN,
    'ldap.server.app_password': LDAP_APP_PASSWORD,
    'ldap.server.users_dn': LDAP_SEARCH_BASE,
    'ldap.server.search_filter': LDAP_SEARCH_FILTERS,
    'ldap.server.use_tls': LDAP_USE_TLS,
    'ldap.server.ca_cert_file': LDAP_CA_CERT_FILE,
    'ldap.server.validate_cert': LDAP_VALIDATE_CERT,
    'ldap.server.ciphers': LDAP_CIPHERS,
    'ldap.group.enable_management': ENABLE_LDAP_GROUP_MANAGEMENT,
    'ldap.group.enable_creation': ENABLE_LDAP_GROUP_CREATION,
    'ldap.server.attribute_for_groups': LDAP_ATTRIBUTE_FOR_GROUPS,
}


ENABLE_PERSISTENT_CONFIG = os.getenv('ENABLE_PERSISTENT_CONFIG', 'True').lower() == 'true'
ENABLE_OAUTH_PERSISTENT_CONFIG = os.getenv('ENABLE_OAUTH_PERSISTENT_CONFIG', 'False').lower() == 'true'

Config.configure(
    defaults=DEFAULT_CONFIG,
    enable_persistent=ENABLE_PERSISTENT_CONFIG,
    enable_oauth_persistent=ENABLE_OAUTH_PERSISTENT_CONFIG,
)
