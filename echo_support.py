"""
ECHO Support Triage
Called by Slack bot for support questions
Uses Ollama Qwen 32B — zero API cost
"""
import sys
import os
import requests

sys.path.insert(0, '/Users/ducorn/DC/scripts')
from ducorn_db import log_task_started, log_task_completed

def triage(question: str) -> str:
    task_id = log_task_started('echo', f'Support: {question[:50]}', 'local-heavy')
    
    try:
        resp = requests.post('http://localhost:11434/api/generate', json={
            'model': 'qwen2.5:32b',
            'prompt': f"""You are ECHO, DuCorn's customer support lead.
Triage this support request and provide a helpful response.
Classify as: BUG / QUESTION / FEATURE REQUEST / OTHER

Support request: {question}

Respond concisely and professionally. Start with the classification.""",
            'stream': False
        }, timeout=120)
        
        answer = resp.json().get('response', 'Unable to process request')
        log_task_completed(task_id, f'Triaged: {answer[:100]}', 500, 0.0)
        return answer
        
    except Exception as e:
        log_task_completed(task_id, f'Failed: {str(e)}', 0, 0.0)
        return f"ECHO error: {str(e)}"

if __name__ == "__main__":
    question = " ".join(sys.argv[1:])
    print(triage(question))
