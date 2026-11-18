"""Check the saved Claude key's shape and test it, without printing it."""
import keyring

key = keyring.get_password("qet-chat", "Claude") or ""
print("saved:", bool(key), "| length:", len(key))
if key:
    print("starts with sk-ant-:", key.startswith("sk-ant-"), "| prefix:", key[:10] + "...")
    print("has spaces/newlines:", any(c.isspace() for c in key),
          "| has quotes:", any(c in "\"'" for c in key),
          "| non-ASCII chars:", sum(1 for c in key if ord(c) > 127))
    import anthropic
    try:
        models = anthropic.Anthropic(api_key=key).models.list(limit=3)
        print("API accepted the key. Models:", [m.id for m in models.data])
    except Exception as exc:  # noqa: BLE001
        print("API said:", type(exc).__name__, str(exc)[:200])
