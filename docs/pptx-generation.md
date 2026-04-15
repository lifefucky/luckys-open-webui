# PPTX Generation

## Components

- **Tool:** `tools/builtin.py:generate_presentation()` — builtin tool, enabled via `ENABLE_PRESENTATION_GENERATION` config (default `False`).
- **Generator:** `utils/pptx_generator.py:PPTXGenerator` — mirrors `PDFGenerator` API. Accepts `ChatTitleMessagesForm`, returns `bytes`.
- **Model routing:** `utils/routing.py:get_function_calling_model()` — stub for selecting FC model. Raises `NoFunctionCallingModelError` if none available. See `BACKLOG.md` for roadmap.
- **Prompt config:** `prompts/presentation.yaml` — `generate_presentation` prompt with `current_version: v1`.

## Flow

```
User: "Сделай презентацию"
  ↓
LLM видит tool spec → вызывает generate_presentation(topic, slide_count)
  ↓
Инструмент ВНУТРИ себя вызывает function-calling модель для генерации markdown
  ↓
PPTXGenerator → .pptx → Storage → Files DB
  ↓
Файл появляется в чате через event_emitter('chat:message:files')
```

## Internal LLM Call

Tool вызывает `generate_chat_completion()` из `utils/chat.py` с `bypass_filter=True` для генерации markdown из chat history. Модель выбирается через `utils/routing.py` (сейчас заглушка).
