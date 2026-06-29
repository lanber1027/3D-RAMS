def strip_output_text_blocks(messages):
    """Workaround for Bedrock Mantle rejecting output_text in EasyInputMessage content arrays."""
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        message["content"] = [
            block
            for block in content
            if not (isinstance(block, dict) and "output_text" in block)
        ]
    return messages
