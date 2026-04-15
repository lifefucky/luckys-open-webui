"""
Built-in tools for Open WebUI.

These tools are automatically available when native function calling is enabled.

IMPORTANT: DO NOT IMPORT THIS MODULE DIRECTLY IN OTHER PARTS OF THE CODEBASE.
"""

import json
import logging
import time
import asyncio
from typing import Optional

from fastapi import Request

from open_webui.models.users import UserModel
from open_webui.routers.retrieval import search_web as _search_web
from open_webui.retrieval.utils import get_content_from_url
from open_webui.routers.images import (
    image_generations,
    image_edits,
    CreateImageForm,
    EditImageForm,
)
from open_webui.routers.memories import (
    query_memory,
    add_memory as _add_memory,
    update_memory_by_id,
    QueryMemoryForm,
    AddMemoryForm,
    MemoryUpdateModel,
)
from open_webui.models.notes import Notes
from open_webui.models.chats import Chats
from open_webui.models.channels import Channels, ChannelMember, Channel
from open_webui.models.messages import Messages, Message
from open_webui.models.groups import Groups
from open_webui.models.memories import Memories
from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
from open_webui.utils.sanitize import sanitize_code

log = logging.getLogger(__name__)

MAX_KNOWLEDGE_BASE_SEARCH_ITEMS = 10_000

# =============================================================================
# TIME UTILITIES
# =============================================================================


async def get_current_timestamp(
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    Get the current Unix timestamp in seconds.

    :return: JSON with current_timestamp (seconds) and current_iso (ISO format)
    """
    try:
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc)
        return json.dumps(
            {
                'current_timestamp': int(now.timestamp()),
                'current_iso': now.isoformat(),
            },
            ensure_ascii=False,
        )
    except Exception as e:
        log.exception(f'get_current_timestamp error: {e}')
        return json.dumps({'error': str(e)})


async def calculate_timestamp(
    days_ago: int = 0,
    weeks_ago: int = 0,
    months_ago: int = 0,
    years_ago: int = 0,
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    Get the current Unix timestamp, optionally adjusted by days, weeks, months, or years.
    Use this to calculate timestamps for date filtering in search functions.
    Examples: "last week" = weeks_ago=1, "3 days ago" = days_ago=3, "a year ago" = years_ago=1

    :param days_ago: Number of days to subtract from current time (default: 0)
    :param weeks_ago: Number of weeks to subtract from current time (default: 0)
    :param months_ago: Number of months to subtract from current time (default: 0)
    :param years_ago: Number of years to subtract from current time (default: 0)
    :return: JSON with current_timestamp and calculated_timestamp (both in seconds)
    """
    try:
        import datetime
        from dateutil.relativedelta import relativedelta

        now = datetime.datetime.now(datetime.timezone.utc)
        current_ts = int(now.timestamp())

        # Calculate the adjusted time
        total_days = days_ago + (weeks_ago * 7)
        adjusted = now - datetime.timedelta(days=total_days)

        # Handle months and years separately (variable length)
        if months_ago > 0 or years_ago > 0:
            adjusted = adjusted - relativedelta(months=months_ago, years=years_ago)

        adjusted_ts = int(adjusted.timestamp())

        return json.dumps(
            {
                'current_timestamp': current_ts,
                'current_iso': now.isoformat(),
                'calculated_timestamp': adjusted_ts,
                'calculated_iso': adjusted.isoformat(),
            },
            ensure_ascii=False,
        )
    except ImportError:
        # Fallback without dateutil
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc)
        current_ts = int(now.timestamp())
        total_days = days_ago + (weeks_ago * 7) + (months_ago * 30) + (years_ago * 365)
        adjusted = now - datetime.timedelta(days=total_days)
        adjusted_ts = int(adjusted.timestamp())
        return json.dumps(
            {
                'current_timestamp': current_ts,
                'current_iso': now.isoformat(),
                'calculated_timestamp': adjusted_ts,
                'calculated_iso': adjusted.isoformat(),
            },
            ensure_ascii=False,
        )
    except Exception as e:
        log.exception(f'calculate_timestamp error: {e}')
        return json.dumps({'error': str(e)})


# =============================================================================
# WEB SEARCH TOOLS
# =============================================================================


async def search_web(
    query: str,
    count: int = 5,
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    Search the public web for information. Best for current events, external references,
    or topics not covered in internal documents.

    :param query: The search query to look up
    :param count: Number of results to return (default: 5)
    :return: JSON with search results containing title, link, and snippet for each result
    """
    if __request__ is None:
        return json.dumps({'error': 'Request context not available'})

    try:
        engine = __request__.app.state.config.WEB_SEARCH_ENGINE
        user = UserModel(**__user__) if __user__ else None

        # Enforce maximum result count from config to prevent abuse
        count = (
            count
            if count < __request__.app.state.config.WEB_SEARCH_RESULT_COUNT
            else __request__.app.state.config.WEB_SEARCH_RESULT_COUNT
        )

        results = await asyncio.to_thread(_search_web, __request__, engine, query, user)

        # Limit results
        results = results[:count] if results else []

        return json.dumps(
            [{'title': r.title, 'link': r.link, 'snippet': r.snippet} for r in results],
            ensure_ascii=False,
        )
    except Exception as e:
        log.exception(f'search_web error: {e}')
        return json.dumps({'error': str(e)})


async def fetch_url(
    url: str,
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    Fetch and extract the main text content from a web page URL.

    :param url: The URL to fetch content from
    :return: The extracted text content from the page
    """
    if __request__ is None:
        return json.dumps({'error': 'Request context not available'})

    try:
        content, _ = await asyncio.to_thread(get_content_from_url, __request__, url)

        # Truncate if configured (WEB_FETCH_MAX_CONTENT_LENGTH)
        max_length = getattr(__request__.app.state.config, 'WEB_FETCH_MAX_CONTENT_LENGTH', None)
        if max_length and max_length > 0 and len(content) > max_length:
            content = content[:max_length] + '\n\n[Content truncated...]'

        return content
    except Exception as e:
        log.exception(f'fetch_url error: {e}')
        return json.dumps({'error': str(e)})


# =============================================================================
# IMAGE GENERATION TOOLS
# =============================================================================


async def generate_image(
    prompt: str,
    __request__: Request = None,
    __user__: dict = None,
    __event_emitter__: callable = None,
    __chat_id__: str = None,
    __message_id__: str = None,
) -> str:
    """
    Generate an image based on a text prompt.

    :param prompt: A detailed description of the image to generate
    :return: Confirmation that the image was generated, or an error message
    """
    if __request__ is None:
        return json.dumps({'error': 'Request context not available'})

    try:
        user = UserModel(**__user__) if __user__ else None

        images = await image_generations(
            request=__request__,
            form_data=CreateImageForm(prompt=prompt),
            user=user,
        )

        # Prepare file entries for the images
        image_files = [{'type': 'image', 'url': img['url']} for img in images]

        # Persist files to DB if chat context is available
        if __chat_id__ and __message_id__ and images:
            db_files = Chats.add_message_files_by_id_and_message_id(
                __chat_id__,
                __message_id__,
                image_files,
            )
            if db_files is not None:
                image_files = db_files

        # Emit the images to the UI if event emitter is available
        if __event_emitter__ and image_files:
            await __event_emitter__(
                {
                    'type': 'chat:message:files',
                    'data': {
                        'files': image_files,
                    },
                }
            )
            # Return a message indicating the image is already displayed
            return json.dumps(
                {
                    'status': 'success',
                    'message': 'The image has been successfully generated and is already visible to the user in the chat. You do not need to display or embed the image again - just acknowledge that it has been created.',
                    'images': images,
                },
                ensure_ascii=False,
            )

        return json.dumps({'status': 'success', 'images': images}, ensure_ascii=False)
    except Exception as e:
        log.exception(f'generate_image error: {e}')
        return json.dumps({'error': str(e)})


async def edit_image(
    prompt: str,
    image_urls: list[str],
    __request__: Request = None,
    __user__: dict = None,
    __event_emitter__: callable = None,
    __chat_id__: str = None,
    __message_id__: str = None,
) -> str:
    """
    Edit existing images based on a text prompt.

    :param prompt: A description of the changes to make to the images
    :param image_urls: A list of URLs of the images to edit
    :return: Confirmation that the images were edited, or an error message
    """
    if __request__ is None:
        return json.dumps({'error': 'Request context not available'})

    try:
        user = UserModel(**__user__) if __user__ else None

        images = await image_edits(
            request=__request__,
            form_data=EditImageForm(prompt=prompt, image=image_urls),
            user=user,
        )

        # Prepare file entries for the images
        image_files = [{'type': 'image', 'url': img['url']} for img in images]

        # Persist files to DB if chat context is available
        if __chat_id__ and __message_id__ and images:
            db_files = Chats.add_message_files_by_id_and_message_id(
                __chat_id__,
                __message_id__,
                image_files,
            )
            if db_files is not None:
                image_files = db_files

        # Emit the images to the UI if event emitter is available
        if __event_emitter__ and image_files:
            await __event_emitter__(
                {
                    'type': 'chat:message:files',
                    'data': {
                        'files': image_files,
                    },
                }
            )
            # Return a message indicating the image is already displayed
            return json.dumps(
                {
                    'status': 'success',
                    'message': 'The edited image has been successfully generated and is already visible to the user in the chat. You do not need to display or embed the image again - just acknowledge that it has been created.',
                    'images': images,
                },
                ensure_ascii=False,
            )

        return json.dumps({'status': 'success', 'images': images}, ensure_ascii=False)
    except Exception as e:
        log.exception(f'edit_image error: {e}')
        return json.dumps({'error': str(e)})


# =============================================================================
# CODE INTERPRETER TOOLS
# =============================================================================


async def execute_code(
    code: str,
    __request__: Request = None,
    __user__: dict = None,
    __event_emitter__: callable = None,
    __event_call__: callable = None,
    __chat_id__: str = None,
    __message_id__: str = None,
    __metadata__: dict = None,
) -> str:
    """
    Execute Python code in a sandboxed environment and return the output.
    Use this to perform calculations, data analysis, generate visualizations,
    or run any Python code that would help answer the user's question.

    :param code: The Python code to execute
    :return: JSON with stdout, stderr, and result from execution
    """
    from uuid import uuid4

    if __request__ is None:
        return json.dumps({'error': 'Request context not available'})

    try:
        # Sanitize code (strips ANSI codes and markdown fences)
        code = sanitize_code(code)

        # Import blocked modules from config (same as middleware)
        from open_webui.config import CODE_INTERPRETER_BLOCKED_MODULES

        # Add import blocking code if there are blocked modules
        if CODE_INTERPRETER_BLOCKED_MODULES:
            import textwrap

            blocking_code = textwrap.dedent(f"""
                import builtins

                BLOCKED_MODULES = {CODE_INTERPRETER_BLOCKED_MODULES}

                _real_import = builtins.__import__
                def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
                    if name.split('.')[0] in BLOCKED_MODULES:
                        importer_name = globals.get('__name__') if globals else None
                        if importer_name == '__main__':
                            raise ImportError(
                                f"Direct import of module {{name}} is restricted."
                            )
                    return _real_import(name, globals, locals, fromlist, level)

                builtins.__import__ = restricted_import
                """)
            code = blocking_code + '\n' + code

        engine = getattr(__request__.app.state.config, 'CODE_INTERPRETER_ENGINE', 'pyodide')
        if engine == 'pyodide':
            # Execute via frontend pyodide using bidirectional event call
            if __event_call__ is None:
                return json.dumps(
                    {'error': 'Event call not available. WebSocket connection required for pyodide execution.'}
                )

            output = await __event_call__(
                {
                    'type': 'execute:python',
                    'data': {
                        'id': str(uuid4()),
                        'code': code,
                        'session_id': (__metadata__.get('session_id') if __metadata__ else None),
                        'files': (__metadata__.get('files', []) if __metadata__ else []),
                    },
                }
            )

            # Parse the output - pyodide returns dict with stdout, stderr, result
            if isinstance(output, dict):
                stdout = output.get('stdout', '')
                stderr = output.get('stderr', '')
                result = output.get('result', '')
            else:
                stdout = ''
                stderr = ''
                result = str(output) if output else ''

        elif engine == 'jupyter':
            from open_webui.utils.code_interpreter import execute_code_jupyter

            output = await execute_code_jupyter(
                __request__.app.state.config.CODE_INTERPRETER_JUPYTER_URL,
                code,
                (
                    __request__.app.state.config.CODE_INTERPRETER_JUPYTER_AUTH_TOKEN
                    if __request__.app.state.config.CODE_INTERPRETER_JUPYTER_AUTH == 'token'
                    else None
                ),
                (
                    __request__.app.state.config.CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD
                    if __request__.app.state.config.CODE_INTERPRETER_JUPYTER_AUTH == 'password'
                    else None
                ),
                __request__.app.state.config.CODE_INTERPRETER_JUPYTER_TIMEOUT,
            )

            stdout = output.get('stdout', '')
            stderr = output.get('stderr', '')
            result = output.get('result', '')

        else:
            return json.dumps({'error': f'Unknown code interpreter engine: {engine}'})

        # Handle image outputs (base64 encoded) - replace with uploaded URLs
        # Get actual user object for image upload (upload_image requires user.id attribute)
        if __user__ and __user__.get('id'):
            from open_webui.models.users import Users
            from open_webui.utils.files import get_image_url_from_base64

            user = Users.get_user_by_id(__user__['id'])

            # Extract and upload images from stdout
            if stdout and isinstance(stdout, str):
                stdout_lines = stdout.split('\n')
                for idx, line in enumerate(stdout_lines):
                    if 'data:image/png;base64' in line:
                        image_url = get_image_url_from_base64(
                            __request__,
                            line,
                            __metadata__ or {},
                            user,
                        )
                        if image_url:
                            stdout_lines[idx] = f'![Output Image]({image_url})'
                stdout = '\n'.join(stdout_lines)

            # Extract and upload images from result
            if result and isinstance(result, str):
                result_lines = result.split('\n')
                for idx, line in enumerate(result_lines):
                    if 'data:image/png;base64' in line:
                        image_url = get_image_url_from_base64(
                            __request__,
                            line,
                            __metadata__ or {},
                            user,
                        )
                        if image_url:
                            result_lines[idx] = f'![Output Image]({image_url})'
                result = '\n'.join(result_lines)

        response = {
            'status': 'success',
            'stdout': stdout,
            'stderr': stderr,
            'result': result,
        }

        return json.dumps(response, ensure_ascii=False)
    except Exception as e:
        log.exception(f'execute_code error: {e}')
        return json.dumps({'error': str(e)})


# =============================================================================
# MEMORY TOOLS
# =============================================================================


async def search_memories(
    query: str,
    count: int = 5,
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    Search the user's stored memories for relevant information.

    :param query: The search query to find relevant memories
    :param count: Number of memories to return (default 5)
    :return: JSON with matching memories and their dates
    """
    if __request__ is None:
        return json.dumps({'error': 'Request context not available'})

    try:
        user = UserModel(**__user__) if __user__ else None

        results = await query_memory(
            __request__,
            QueryMemoryForm(content=query, k=count),
            user,
        )

        if results and hasattr(results, 'documents') and results.documents:
            memories = []
            for doc_idx, doc in enumerate(results.documents[0]):
                memory_id = None
                if results.ids and results.ids[0]:
                    memory_id = results.ids[0][doc_idx]
                created_at = 'Unknown'
                if results.metadatas and results.metadatas[0][doc_idx].get('created_at'):
                    created_at = time.strftime(
                        '%Y-%m-%d',
                        time.localtime(results.metadatas[0][doc_idx]['created_at']),
                    )
                memories.append({'id': memory_id, 'date': created_at, 'content': doc})
            return json.dumps(memories, ensure_ascii=False)
        else:
            return json.dumps([])
    except Exception as e:
        log.exception(f'search_memories error: {e}')
        return json.dumps({'error': str(e)})


async def add_memory(
    content: str,
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    Store a new memory for the user.

    :param content: The memory content to store
    :return: Confirmation that the memory was stored
    """
    if __request__ is None:
        return json.dumps({'error': 'Request context not available'})

    try:
        user = UserModel(**__user__) if __user__ else None

        memory = await _add_memory(
            __request__,
            AddMemoryForm(content=content),
            user,
        )

        return json.dumps({'status': 'success', 'id': memory.id}, ensure_ascii=False)
    except Exception as e:
        log.exception(f'add_memory error: {e}')
        return json.dumps({'error': str(e)})


async def replace_memory_content(
    memory_id: str,
    content: str,
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    Update the content of an existing memory by its ID.

    :param memory_id: The ID of the memory to update
    :param content: The new content for the memory
    :return: Confirmation that the memory was updated
    """
    if __request__ is None:
        return json.dumps({'error': 'Request context not available'})

    try:
        user = UserModel(**__user__) if __user__ else None

        memory = await update_memory_by_id(
            memory_id=memory_id,
            request=__request__,
            form_data=MemoryUpdateModel(content=content),
            user=user,
        )

        return json.dumps(
            {'status': 'success', 'id': memory.id, 'content': memory.content},
            ensure_ascii=False,
        )
    except Exception as e:
        log.exception(f'replace_memory_content error: {e}')
        return json.dumps({'error': str(e)})


async def delete_memory(
    memory_id: str,
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    Delete a memory by its ID.

    :param memory_id: The ID of the memory to delete
    :return: Confirmation that the memory was deleted
    """
    if __request__ is None:
        return json.dumps({'error': 'Request context not available'})

    try:
        user = UserModel(**__user__) if __user__ else None

        result = Memories.delete_memory_by_id_and_user_id(memory_id, user.id)

        if result:
            VECTOR_DB_CLIENT.delete(collection_name=f'user-memory-{user.id}', ids=[memory_id])
            return json.dumps(
                {'status': 'success', 'message': f'Memory {memory_id} deleted'},
                ensure_ascii=False,
            )
        else:
            return json.dumps({'error': 'Memory not found or access denied'})
    except Exception as e:
        log.exception(f'delete_memory error: {e}')
        return json.dumps({'error': str(e)})


async def list_memories(
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    List all stored memories for the user.

    :return: JSON list of all memories with id, content, and dates
    """
    if __request__ is None:
        return json.dumps({'error': 'Request context not available'})

    try:
        user = UserModel(**__user__) if __user__ else None

        memories = Memories.get_memories_by_user_id(user.id)

        if memories:
            result = [
                {
                    'id': m.id,
                    'content': m.content,
                    'created_at': time.strftime('%Y-%m-%d %H:%M', time.localtime(m.created_at)),
                    'updated_at': time.strftime('%Y-%m-%d %H:%M', time.localtime(m.updated_at)),
                }
                for m in memories
            ]
            return json.dumps(result, ensure_ascii=False)
        else:
            return json.dumps([])
    except Exception as e:
        log.exception(f'list_memories error: {e}')
        return json.dumps({'error': str(e)})


# =============================================================================
# NOTES TOOLS
# =============================================================================


async def search_notes(
    query: str,
    count: int = 5,
    start_timestamp: Optional[int] = None,
    end_timestamp: Optional[int] = None,
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    Search the user's notes by title and content.

    :param query: The search query to find matching notes
    :param count: Maximum number of results to return (default: 5)
    :param start_timestamp: Only include notes updated after this Unix timestamp (seconds)
    :param end_timestamp: Only include notes updated before this Unix timestamp (seconds)
    :return: JSON with matching notes containing id, title, and content snippet
    """
    if __request__ is None:
        return json.dumps({'error': 'Request context not available'})

    if not __user__:
        return json.dumps({'error': 'User context not available'})

    try:
        user_id = __user__.get('id')
        user_group_ids = [group.id for group in Groups.get_groups_by_member_id(user_id)]

        result = Notes.search_notes(
            user_id=user_id,
            filter={
                'query': query,
                'user_id': user_id,
                'group_ids': user_group_ids,
                'permission': 'read',
            },
            skip=0,
            limit=count * 3,  # Fetch more for filtering
        )

        # Convert timestamps to nanoseconds for comparison
        start_ts = start_timestamp * 1_000_000_000 if start_timestamp else None
        end_ts = end_timestamp * 1_000_000_000 if end_timestamp else None

        notes = []
        for note in result.items:
            # Apply date filters (updated_at is in nanoseconds)
            if start_ts and note.updated_at < start_ts:
                continue
            if end_ts and note.updated_at > end_ts:
                continue

            # Extract a snippet from the markdown content
            content_snippet = ''
            if note.data and note.data.get('content', {}).get('md'):
                md_content = note.data['content']['md']
                lower_content = md_content.lower()
                lower_query = query.lower()
                idx = lower_content.find(lower_query)
                if idx != -1:
                    start = max(0, idx - 50)
                    end = min(len(md_content), idx + len(query) + 100)
                    content_snippet = (
                        ('...' if start > 0 else '') + md_content[start:end] + ('...' if end < len(md_content) else '')
                    )
                else:
                    content_snippet = md_content[:150] + ('...' if len(md_content) > 150 else '')

            notes.append(
                {
                    'id': note.id,
                    'title': note.title,
                    'snippet': content_snippet,
                    'updated_at': note.updated_at,
                }
            )

            if len(notes) >= count:
                break

        return json.dumps(notes, ensure_ascii=False)
    except Exception as e:
        log.exception(f'search_notes error: {e}')
        return json.dumps({'error': str(e)})


async def view_note(
    note_id: str,
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    Get the full content of a note by its ID.

    :param note_id: The ID of the note to retrieve
    :return: JSON with the note's id, title, and full markdown content
    """
    if __request__ is None:
        return json.dumps({'error': 'Request context not available'})

    if not __user__:
        return json.dumps({'error': 'User context not available'})

    try:
        note = Notes.get_note_by_id(note_id)

        if not note:
            return json.dumps({'error': 'Note not found'})

        # Check access permission
        user_id = __user__.get('id')
        user_group_ids = [group.id for group in Groups.get_groups_by_member_id(user_id)]

        from open_webui.models.access_grants import AccessGrants

        if note.user_id != user_id and not AccessGrants.has_access(
            user_id=user_id,
            resource_type='note',
            resource_id=note.id,
            permission='read',
            user_group_ids=set(user_group_ids),
        ):
            return json.dumps({'error': 'Access denied'})

        # Extract markdown content
        content = ''
        if note.data and note.data.get('content', {}).get('md'):
            content = note.data['content']['md']

        return json.dumps(
            {
                'id': note.id,
                'title': note.title,
                'content': content,
                'updated_at': note.updated_at,
                'created_at': note.created_at,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        log.exception(f'view_note error: {e}')
        return json.dumps({'error': str(e)})


async def write_note(
    title: str,
    content: str,
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    Create a new note with the given title and content.

    :param title: The title of the new note
    :param content: The markdown content for the note
    :return: JSON with success status and new note id
    """
    if __request__ is None:
        return json.dumps({'error': 'Request context not available'})

    if not __user__:
        return json.dumps({'error': 'User context not available'})

    try:
        import re
        from io import BytesIO
        from uuid import uuid4
        from open_webui.models.chats import Chats, ChatTitleMessagesForm
        from open_webui.models.users import Users, UserModel
        from open_webui.models.files import Files, FileForm
        from open_webui.utils.chat import generate_chat_completion
        from open_webui.utils.pptx_generator import PPTXGenerator
        from open_webui.utils.routing import get_function_calling_model, NoFunctionCallingModelError
        from open_webui.storage.provider import Storage

        user = Users.get_user_by_id(__user__['id'])
        if not user:
            return json.dumps({'error': 'User not found'})

        # Emit status
        if __event_emitter__:
            await __event_emitter__(
                {
                    'type': 'status',
                    'data': {
                        'action': 'pptx_generation',
                        'description': 'Generating presentation...',
                        'done': False,
                    },
                }
            )

        # Get chat history (with user authorization check)
        chat = Chats.get_chat_by_id_and_user_id(__chat_id__, __user__['id']) if __chat_id__ else None
        if not chat:
            return json.dumps({'error': 'Chat context not available'})

        # Extract messages from chat history
        messages = []
        history = chat.chat.get('history', {}).get('messages', {})
        current_id = history.get('currentId')
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            msg = history.get(current_id)
            if msg:
                messages.append(
                    {
                        'role': msg.get('role', ''),
                        'content': msg.get('content', ''),
                        'timestamp': msg.get('timestamp', 0),
                    }
                )
            current_id = msg.get('parentId') if msg else None
        messages.reverse()

        if not messages:
            return json.dumps({'error': 'No messages in chat to generate presentation from'})

        # Get available models for function calling selection
        available_models = __request__.app.state.MODELS
        model_list = list(available_models.values()) if isinstance(available_models, dict) else available_models

        # Select function-calling model (uses routing utility)
        try:
            fc_model_id = get_function_calling_model(model_list)
        except NoFunctionCallingModelError as e:
            return json.dumps({'error': str(e)})

        # Load prompt template from config
        from open_webui.utils.prompt_loader import get_prompt

        slide_hint = f'Target approximately {slide_count} slides.' if slide_count else 'Create an appropriate number of slides based on the content.'
        chat_messages_str = json.dumps(messages, ensure_ascii=False)

        try:
            system_prompt, user_prompt = get_prompt(
                filename='presentation',
                prompt_name='generate_presentation',
                variables={
                    'topic': topic,
                    'slide_hint': slide_hint,
                    'chat_messages': chat_messages_str,
                },
            )
        except (FileNotFoundError, KeyError) as e:
            return json.dumps({'error': f'Prompt config error: {e}'})

        # Call LLM to generate markdown structure
        if __event_emitter__:
            await __event_emitter__(
                {
                    'type': 'status',
                    'data': {
                        'action': 'pptx_generation',
                        'description': 'Generating slide content...',
                        'done': False,
                    },
                }
            )

        llm_messages = []
        if system_prompt:
            llm_messages.append({'role': 'system', 'content': system_prompt})
        if user_prompt:
            llm_messages.append({'role': 'user', 'content': user_prompt})

        llm_response = await generate_chat_completion(
            __request__,
            form_data={
                'model': fc_model_id,
                'messages': llm_messages,
                'stream': False,
            },
            user=user,
            bypass_filter=True,
        )

        choices = llm_response.get('choices')
        if not choices:
            return json.dumps({'error': 'LLM returned no choices'})

        markdown_content = choices[0].get('message', {}).get('content', '')

        if not markdown_content:
            return json.dumps({'error': 'Failed to generate presentation content'})

        # Generate PPTX
        if __event_emitter__:
            await __event_emitter__(
                {
                    'type': 'status',
                    'data': {
                        'action': 'pptx_generation',
                        'description': 'Creating PowerPoint file...',
                        'done': False,
                    },
                }
            )

        pptx_form = ChatTitleMessagesForm(title=topic, messages=[{'role': 'assistant', 'content': markdown_content}])
        pptx_bytes = PPTXGenerator(pptx_form).generate_chat_pptx()

        # Save file via Storage
        # Sanitize topic for filename
        safe_topic = re.sub(r'[^\w\s-]', '', topic).strip().replace(' ', '_')
        file_id = str(uuid4())
        filename = f'{file_id}_{safe_topic}.pptx' if safe_topic else f'{file_id}_presentation.pptx'

        file_obj = BytesIO(pptx_bytes)
        file_obj.name = filename
        _, file_path = Storage.upload_file(
            file_obj,
            filename,
            tags={'user_id': user.id, 'chat_id': __chat_id__ or ''},
        )

        # Register in Files DB
        file_meta = {
            'name': f'{topic}.pptx',
            'content_type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'size': len(pptx_bytes),
        }

        file_form = FileForm(
            id=file_id,
            filename=filename,
            path=file_path,
            data={'content': markdown_content},
            meta=file_meta,
        )

        Files.insert_new_file(user.id, file_form)

        # Emit file to UI
        file_entry = {
            'type': 'file',
            'url': f'/api/v1/files/{file_id}/content',
            'name': f'{topic}.pptx',
            'size': len(pptx_bytes),
            'content_type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        }

        if __event_emitter__:
            await __event_emitter__(
                {
                    'type': 'chat:message:files',
                    'data': {
                        'files': [file_entry],
                    },
                }
            )

        # Persist file reference to chat message
        if __chat_id__ and __message_id__:
            Chats.add_message_files_by_id_and_message_id(
                __chat_id__,
                __message_id__,
                [file_entry],
            )

        return json.dumps(
            {
                'status': 'success',
                'message': 'The presentation has been generated and is available for download in the chat.',
                'file_id': file_id,
                'filename': f'{topic}.pptx',
            },
            ensure_ascii=False,
        )
    except Exception as e:
        log.exception(f'generate_presentation error: {e}')
        return json.dumps({'error': str(e)})
