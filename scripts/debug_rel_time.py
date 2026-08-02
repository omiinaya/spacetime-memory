#!/usr/bin/env python3
"""Debug relative time resolution."""
import json, sys, os, time, secrets, re
sys.path.insert(0, 'sdk/python')
import httpx
from spacetime_memory import Client

DB_ID = os.environ['SPACETIMEDB_DB']
STDB_URL = 'http://localhost:3001'

resp = httpx.get('{}/v1/database/{}'.format(STDB_URL, DB_ID), timeout=10)
token = resp.headers.get('spacetime-identity-token', '')
client = Client(database=DB_ID, token=token)
try:
    client._call('register', ['debug-rel2-' + secrets.token_hex(4), 'test', 'benchpass'])
except:
    pass

ws = client.create_workspace('debug-rel2', 'debug', '')
ws_id = ws.get('id', '')
print('Workspace:', ws_id)

memories = [
    ('I went to a LGBTQ support group yesterday and it was so powerful. [Session 1]', '1:56 pm on 8 May, 2023'),
    ('Yeah, I painted that lake sunrise last year! It is special to me. [Session 1]', '1:56 pm on 8 May, 2023'),
    ('I ran a charity race for mental health last month [Session 2]', '1:14 pm on 25 May, 2023'),
]

for text, date in memories:
    client.store(ws_id, text, memory_type='test', confidence=1.0,
                 entities_json=json.dumps([{'name': date, 'entity_type': 'datetime'}]))

time.sleep(3)

LLM_KEY = os.environ.get('AUXILIARY_VISION_API_KEY', '')
LLM_ENDPOINT = 'https://openrouter.ai/api/v1'

questions = [
    ('When did Caroline go to the LGBTQ support group?', '7 May 2023'),
    ('When did Melanie paint a sunrise?', '2022'),
    ('When did Melanie run a charity race?', 'April 2023'),
]

for question, expected in questions:
    results = client.search(ws_id, question, memory_type='', limit=10, semantic=True, cross_encoder=True)
    
    # Build timeline
    entries = []
    seen = set()
    for r in results:
        content = r.get('content', r.get('memory_content', ''))
        if not content or content[:60] in seen: continue
        seen.add(content[:60])
        m = re.search(r'\[Session (\d+)\]', content)
        snum = int(m.group(1)) if m else -1
        date = ''
        for text, d in memories:
            if text == content:
                date = d
                break
        clean = re.sub(r' *\[Session \d+\]', '', content)
        entries.append({'session': snum, 'date': date, 'text': clean})
    
    entries.sort(key=lambda e: (e['session'] if e['session'] >= 0 else 9999))
    timeline = '\n'.join(
        '[Session {}] ({}) {}'.format(e['session'], e['date'] or 'date unknown', e['text'])
        for e in entries
    )
    
    prompt = """You are a precise temporal reasoning system. You have a conversation timeline below.

TIMELINE:
{}

QUESTION: {}

IMPORTANT: The conversation text may use relative time words like "yesterday", "last week", 
"last month", "last year", "two days ago", etc. These are RELATIVE to the session date shown in ().
You MUST compute the absolute date from the relative reference + session date.

Examples:
- Session date: "1:56 pm on 8 May, 2023", text: "I went yesterday" => Answer: 7 May 2023
- Session date: "1:56 pm on 8 May, 2023", text: "I painted it last year" => Answer: 2022
- Session date: "7:55 pm on 9 June, 2023", text: "Two weekends ago" => Answer: 27-28 May 2023

First, find which session entry contains the answer. Then identify the relative time word. 
Then compute the absolute date. Then answer concisely.

Say "I don't know" only if you cannot determine the answer.

Answer:""".format(timeline, question)
    
    body = {'model': 'deepseek/deepseek-chat', 'messages': [{'role': 'user', 'content': prompt}], 'temperature': 0.0, 'max_tokens': 150}
    r = httpx.post(LLM_ENDPOINT + '/chat/completions', json=body, headers={'Authorization': 'Bearer {}'.format(LLM_KEY)}, timeout=30)
    answer = r.json()['choices'][0]['message']['content']
    
    print('\nQ: {}'.format(question))
    print('Timeline:\n{}'.format(timeline))
    print('Answer: {}'.format(answer.strip()))
    print('Expected: {}'.format(expected))
    print('---')
