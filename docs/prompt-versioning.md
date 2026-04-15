# Prompt Versioning

## Structure

Prompt configs live in `backend/open_webui/prompts/*.yaml`.

Structure mirrors `backend/examples/model_config.yaml`:

```yaml
prompts:
  <name>:
    current_version: v1
    versions:
      v1:
        system: |
          ...
        user: |
          ...
        input_variables:
          - var1
          - var2
        few_shot: []
```

- `prompts.<name>.current_version` selects active version from `versions`.

## Loading

Load via `utils/prompt_loader.py:get_prompt(filename, prompt_name, variables)`:

- Validates `input_variables`
- Raises `FileNotFoundError` if YAML file missing
- Raises `KeyError` if prompt key or version missing
