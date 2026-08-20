from groq import Groq
client = Groq(api_key="gsk")
models = client.models.list()
for m in models.data:
    print(m.id)