import os, asyncio, sys
sys.path.insert(0, os.getcwd())
from app.services.llm import LlmChat, UserMessage
from app.config import GEMINI_API_KEY

print('GEMINI_API_KEY set?', bool(GEMINI_API_KEY))

async def test():
    chat = LlmChat(session_id='test', system_message='You are a test.').with_model('gemini','gemini-2.5-flash').with_params(temperature=0)
    try:
        resp = await chat.send_message(UserMessage(text='Say hi'))
        print('LLM ok, response len=', len(resp))
        print(resp[:400])
    except Exception as e:
        print('LLM error:', repr(e))

if __name__ == '__main__':
    asyncio.run(test())
