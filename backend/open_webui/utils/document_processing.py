import asyncio
import hashlib

from open_webui.models.config import Config
from open_webui.models.files import Files
from open_webui.retrieval.loaders.main import Loader
from open_webui.storage.provider import Storage


LOADER_CONFIG_KEYS = {
    'CONTENT_EXTRACTION_ENGINE': 'rag.content_extraction_engine',
    'CONTENT_EXTRACTION_SUPPORTED_MEDIA_MIME_TYPES': 'rag.content_extraction.supported_media_mime_types',
    'DATALAB_MARKER_API_KEY': 'rag.datalab_marker_api_key',
    'DATALAB_MARKER_API_BASE_URL': 'rag.datalab_marker_api_base_url',
    'DATALAB_MARKER_ADDITIONAL_CONFIG': 'rag.datalab_marker_additional_config',
    'DATALAB_MARKER_SKIP_CACHE': 'rag.datalab_marker_skip_cache',
    'DATALAB_MARKER_FORCE_OCR': 'rag.datalab_marker_force_ocr',
    'DATALAB_MARKER_PAGINATE': 'rag.datalab_marker_paginate',
    'DATALAB_MARKER_STRIP_EXISTING_OCR': 'rag.datalab_marker_strip_existing_ocr',
    'DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION': 'rag.datalab_marker_disable_image_extraction',
    'DATALAB_MARKER_FORMAT_LINES': 'rag.datalab_marker_format_lines',
    'DATALAB_MARKER_USE_LLM': 'rag.datalab_marker_use_llm',
    'DATALAB_MARKER_OUTPUT_FORMAT': 'rag.datalab_marker_output_format',
    'EXTERNAL_DOCUMENT_LOADER_URL': 'rag.external_document_loader_url',
    'EXTERNAL_DOCUMENT_LOADER_API_KEY': 'rag.external_document_loader_api_key',
    'EXTERNAL_DOCUMENT_LOADER_HEADERS': 'rag.external_document_loader_headers',
    'TIKA_SERVER_URL': 'rag.tika_server_url',
    'TIKA_SERVER_VERSION': 'rag.tika_server_version',
    'DOCLING_SERVER_URL': 'rag.docling_server_url',
    'DOCLING_API_KEY': 'rag.docling_api_key',
    'DOCLING_PARAMS': 'rag.docling_params',
    'PDF_EXTRACT_IMAGES': 'rag.pdf_extract_images',
    'PDF_LOADER_MODE': 'rag.pdf_loader_mode',
    'DOCUMENT_INTELLIGENCE_ENDPOINT': 'rag.document_intelligence_endpoint',
    'DOCUMENT_INTELLIGENCE_KEY': 'rag.document_intelligence_key',
    'DOCUMENT_INTELLIGENCE_MODEL': 'rag.document_intelligence_model',
    'MISTRAL_OCR_API_BASE_URL': 'rag.mistral_ocr_api_base_url',
    'MISTRAL_OCR_API_KEY': 'rag.mistral_ocr_api_key',
    'MISTRAL_OCR_USE_BASE64': 'rag.mistral_ocr_use_base64',
    'PADDLEOCR_VL_BASE_URL': 'rag.paddleocr_vl_base_url',
    'PADDLEOCR_VL_TOKEN': 'rag.paddleocr_vl_token',
    'MINERU_API_MODE': 'rag.mineru_api_mode',
    'MINERU_API_URL': 'rag.mineru_api_url',
    'MINERU_API_KEY': 'rag.mineru_api_key',
    'MINERU_API_TIMEOUT': 'rag.mineru_api_timeout',
    'MINERU_PARAMS': 'rag.mineru_params',
    'MINERU_FILE_EXTENSIONS': 'rag.mineru_file_extensions',
    'FILE_MAX_SIZE': 'rag.file.max_size',
}


async def build_document_loader() -> Loader:
    values = await Config.get_many(*LOADER_CONFIG_KEYS.values())
    loader_config = {name: values.get(key) for name, key in LOADER_CONFIG_KEYS.items()}
    engine = loader_config.pop('CONTENT_EXTRACTION_ENGINE')
    return Loader(engine=engine, **loader_config)


async def store_file_content(file_id: str, content: str, db=None) -> str:
    content = content.replace('<br/>', '\n')
    await Files.update_file_data_by_id(
        file_id,
        {'content': content, 'status': 'completed', 'error': None},
        db=db,
    )
    await Files.update_file_hash_by_id(file_id, hashlib.sha256(content.encode('utf-8')).hexdigest(), db=db)
    return content


async def extract_and_store_file_content(file, user, db=None) -> str:
    if not file.path:
        return await store_file_content(file.id, (file.data or {}).get('content', ''), db=db)

    file_path = await asyncio.to_thread(Storage.get_file, file.path)
    loader = await build_document_loader()
    loader.user = user
    loader.metadata = {
        'file_id': file.id,
        'file_name': file.filename,
        'file_content_type': (file.meta or {}).get('content_type'),
    }
    docs = await loader.aload(file.filename, (file.meta or {}).get('content_type'), file_path)
    content = '\n\n'.join(doc.page_content for doc in docs)
    return await store_file_content(file.id, content, db=db)
