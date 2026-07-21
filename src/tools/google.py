import os
from google import genai

client = genai.Client(
    api_key=os.environ.get("GEMINI_API_KEY"),
)

generation_config = {
    'temperature': 1,
    'max_output_tokens': 65536,
    'top_p': 0.95,
    'thinking_level': 'high',
}

interaction = client.interactions.create(
    model='models/gemini-3-flash-preview',
    input='',
    generation_config=generation_config,
)
# Gemini 2.5 Flash API
print(interaction.output_text)

""" with st.chat_message("assistant"):
        stream = client.chat.completions.create(
            model="GPT-4o mini", # or "gpt-4o"
            messages=[
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.messages
            ],
            stream=True,
        )
        response = st.write_stream(stream) """