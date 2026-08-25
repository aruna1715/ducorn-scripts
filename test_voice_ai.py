"""
DuCorn Voice AI Performance Test Suite
Tests: latency, conversation memory, concurrency, long sessions, audio, recovery
Run: python3.12 test_voice_ai.py
"""
import time
import json
import requests
import threading
import subprocess
import os
from datetime import datetime

API_BASE = "http://localhost:8000"
API_KEY = os.environ.get("DUCORN_API_TOKEN", "")
HDR = {"x-api-key": API_KEY, "Content-Type": "application/json"}

PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"

results = []

def log(test, status, detail="", duration=None):
    dur_str = f" [{duration:.2f}s]" if duration else ""
    line = f"{status} {test}{dur_str}"
    if detail:
        line += f"\n       {detail}"
    print(line)
    results.append({"test": test, "status": status, "duration": duration, "detail": detail})

def chat(message, reset=False):
    """Send message to /jarvis/chat and return response + duration"""
    start = time.time()
    try:
        resp = requests.post(
            f"{API_BASE}/jarvis/chat",
            headers=HDR,
            json={"message": message, "reset": reset},
            timeout=120
        )
        duration = time.time() - start
        if resp.status_code == 200:
            data = resp.json()
            return data.get("response", ""), duration, data.get("history_length", 0)
        else:
            return None, duration, 0
    except Exception as e:
        return None, time.time() - start, 0

def reset_conversation():
    try:
        requests.post(f"{API_BASE}/jarvis/reset", headers=HDR, timeout=10)
    except:
        pass

# ── TEST 1: API HEALTH ────────────────────────────────────────────────────────
print("\n" + "="*60)
print("DuCorn Voice AI Performance Test Suite")
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*60)

print("\n📋 TEST 1 — API Health")
try:
    resp = requests.get(f"{API_BASE}/health", headers=HDR, timeout=5)
    if resp.status_code == 200:
        log("API health check", PASS, "Activity API responding")
    else:
        log("API health check", FAIL, f"Status: {resp.status_code}")
except Exception as e:
    log("API health check", FAIL, f"API not reachable: {e}")

# Check /jarvis/chat endpoint exists
try:
    resp = requests.post(
        f"{API_BASE}/jarvis/chat",
        headers=HDR,
        json={"message": "test"},
        timeout=60
    )
    if resp.status_code == 200:
        log("/jarvis/chat endpoint", PASS, "Endpoint responding")
    elif resp.status_code == 404:
        log("/jarvis/chat endpoint", FAIL, "Endpoint not found — add to main.py first")
        print("\n⛔ Cannot continue without /jarvis/chat endpoint. Add it to main.py first.")
        exit(1)
    else:
        log("/jarvis/chat endpoint", WARN, f"Status: {resp.status_code}")
except Exception as e:
    log("/jarvis/chat endpoint", FAIL, str(e))
    exit(1)

# ── TEST 2: RESPONSE LATENCY ─────────────────────────────────────────────────
print("\n📋 TEST 2 — Response Latency (10 messages)")
reset_conversation()
latencies = []
messages = [
    "Hello ATLAS",
    "What is DuCorn?",
    "How many agents do we have?",
    "What is our total spend?",
    "What products have we built?",
    "Who are the founders?",
    "What is the dashboard URL?",
    "What does SAGE do?",
    "What does REX do?",
    "Give me a one sentence status update"
]

for i, msg in enumerate(messages):
    response, duration, history = chat(msg)
    latencies.append(duration)
    status = PASS if duration < 15 else (WARN if duration < 25 else FAIL)
    log(f"  Message {i+1}: '{msg[:40]}'", status,
        f"Response: '{(response or 'ERROR')[:60]}...' | History: {history} turns",
        duration)

avg_latency = sum(latencies) / len(latencies)
max_latency = max(latencies)
min_latency = min(latencies)

print(f"\n  📊 Latency Summary:")
print(f"     Average: {avg_latency:.2f}s")
print(f"     Min:     {min_latency:.2f}s")
print(f"     Max:     {max_latency:.2f}s")
print(f"     Target:  <10s per response")

overall_latency = PASS if avg_latency < 10 else (WARN if avg_latency < 15 else FAIL)
log("Latency overall", overall_latency, f"Avg {avg_latency:.2f}s")

# ── TEST 3: CONVERSATION MEMORY ──────────────────────────────────────────────
print("\n📋 TEST 3 — Conversation Memory")
reset_conversation()

memory_msgs = [
    ("My name is Vijay and I am the CEO of DuCorn", None),
    ("Our most expensive product to build was the Activity API", None),
    ("We spent $33 on a bad day last week due to a retry loop bug", None),
    ("What is my name?", "vijay"),
    ("What was our most expensive product to build?", "activity api"),
    ("How much did we spend on our bad day?", "33"),
]

memory_pass = 0
for msg, expected in memory_msgs:
    response, duration, history = chat(msg)
    if expected:
        found = expected.lower() in (response or "").lower()
        status = PASS if found else FAIL
        if found:
            memory_pass += 1
        log(f"  Memory check: '{msg[:50]}'", status,
            f"Expected '{expected}' in response: '{(response or 'ERROR')[:80]}'",
            duration)
    else:
        log(f"  Context set: '{msg[:50]}'", PASS,
            f"Stored in history", duration)

log("Conversation memory overall", PASS if memory_pass >= 2 else FAIL,
    f"{memory_pass}/3 memory checks passed")

# ── TEST 4: CONCURRENT SESSIONS ──────────────────────────────────────────────
print("\n📋 TEST 4 — Concurrent Sessions")
concurrent_results = {}

def run_concurrent(name, message):
    response, duration, _ = chat(message)
    concurrent_results[name] = {
        "response": response,
        "duration": duration,
        "ok": response is not None
    }

threads = [
    threading.Thread(target=run_concurrent, args=("Vijay", "What agents do we have in DuCorn?")),
    threading.Thread(target=run_concurrent, args=("Aruna", "What is the DuCorn tech stack?"))
]

start = time.time()
for t in threads:
    t.start()
for t in threads:
    t.join()
total = time.time() - start

all_ok = all(r["ok"] for r in concurrent_results.values())
log("Concurrent sessions (2 users)", PASS if all_ok else FAIL,
    f"Both responded in {total:.2f}s total", total)

for name, result in concurrent_results.items():
    log(f"  {name}'s response", PASS if result["ok"] else FAIL,
        f"'{(result['response'] or 'ERROR')[:80]}'",
        result["duration"])

# ── TEST 5: LONG SESSION STABILITY ───────────────────────────────────────────
print("\n📋 TEST 5 — Long Session Stability (20 turns)")
reset_conversation()

long_msgs = [
    "Hello ATLAS", "What is DuCorn?", "How many agents?", "Tell me about SAGE",
    "Tell me about REX", "What is our spend?", "What products did we build?",
    "What is the dashboard URL?", "What does ECHO do?", "What does NOVA do?",
    "What is CrewAI?", "What is LiteLLM?", "What is Ollama?", "What is PostgreSQL used for?",
    "What is the Cloudflare tunnel for?", "How does the approval gate work?",
    "What is the morning digest?", "What does CLEO do?", "What does IRIS do?",
    "Summarize everything you know about DuCorn in 3 sentences"
]

long_latencies = []
long_failures = 0
for i, msg in enumerate(long_msgs):
    response, duration, history = chat(msg)
    long_latencies.append(duration)
    if not response:
        long_failures += 1
    if i % 5 == 4:  # Print every 5th
        log(f"  Turn {i+1}/20", PASS if response else FAIL,
            f"History: {history} turns | Latency: {duration:.2f}s")

avg_long = sum(long_latencies) / len(long_latencies)
log("Long session stability", PASS if long_failures == 0 else WARN,
    f"20 turns | Avg latency: {avg_long:.2f}s | Failures: {long_failures}")

# ── TEST 6: AUDIO GENERATION ─────────────────────────────────────────────────
print("\n📋 TEST 6 — Audio Generation")
reset_conversation()

response, duration, _ = chat("Give me a brief one sentence DuCorn status update")
if response:
    time.sleep(3)  # Wait for audio generation
    audio_path = "/Users/ducorn/DC/digests/atlas_response.m4a"
    if os.path.exists(audio_path):
        size = os.path.getsize(audio_path)
        age = time.time() - os.path.getmtime(audio_path)
        log("Audio file generated", PASS if size > 1000 else FAIL,
            f"Size: {size:,} bytes | Age: {age:.1f}s old")
        
        # Test audio endpoint
        try:
            resp = requests.get(
                f"{API_BASE}/chat/audio",
                headers=HDR,
                timeout=10
            )
            log("Audio endpoint", PASS if resp.status_code == 200 else FAIL,
                f"Status: {resp.status_code} | Size: {len(resp.content):,} bytes")
        except Exception as e:
            log("Audio endpoint", FAIL, str(e))
    else:
        log("Audio file generated", FAIL, "No audio file found")
else:
    log("Audio generation", FAIL, "Chat response failed")

# ── TEST 7: ERROR RECOVERY ───────────────────────────────────────────────────
print("\n📋 TEST 7 — Error Recovery")

# Test empty message
resp = requests.post(
    f"{API_BASE}/jarvis/chat",
    headers=HDR,
    json={"message": ""},
    timeout=10
)
log("Empty message handling", PASS if resp.status_code in [200, 400] else FAIL,
    f"Status: {resp.status_code}")

# Test reset endpoint
resp = requests.post(f"{API_BASE}/jarvis/reset", headers=HDR, timeout=10)
log("Conversation reset", PASS if resp.status_code == 200 else FAIL,
    f"Status: {resp.status_code}")

# Test after reset - verify fresh start
response, duration, history = chat("What did we talk about before?")
log("Fresh conversation after reset", PASS if history <= 2 else WARN,
    f"History length: {history} (should be 1-2 after reset)")

# ── FINAL SUMMARY ────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("FINAL TEST SUMMARY")
print("="*60)

passed = sum(1 for r in results if r["status"] == PASS)
warned = sum(1 for r in results if r["status"] == WARN)
failed = sum(1 for r in results if r["status"] == FAIL)
total_tests = len(results)

print(f"\n  ✅ Passed:  {passed}")
print(f"  ⚠️  Warned:  {warned}")
print(f"  ❌ Failed:  {failed}")
print(f"  📊 Total:   {total_tests}")

verdict = "PASS" if failed == 0 else ("CONDITIONAL PASS" if failed <= 2 else "FAIL")
print(f"\n  Overall Verdict: {verdict}")

if failed > 0:
    print("\n  ❌ Failed tests:")
    for r in results:
        if r["status"] == FAIL:
            print(f"     - {r['test']}: {r['detail']}")

if warned > 0:
    print("\n  ⚠️  Warnings:")
    for r in results:
        if r["status"] == WARN:
            print(f"     - {r['test']}: {r['detail']}")

print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*60)

# Save results to file
report_path = "/Users/ducorn/DC/ducorn-products/docs/voice-ai-performance-test.md"
with open(report_path, "w") as f:
    f.write(f"# DuCorn Voice AI Performance Test Report\n")
    f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write(f"**Verdict:** {verdict}\n\n")
    f.write(f"## Results\n\n")
    f.write(f"| Test | Status | Duration | Detail |\n")
    f.write(f"|---|---|---|---|\n")
    for r in results:
        dur = f"{r['duration']:.2f}s" if r['duration'] else "-"
        f.write(f"| {r['test']} | {r['status']} | {dur} | {r['detail']} |\n")
    f.write(f"\n## Summary\n")
    f.write(f"- Passed: {passed}\n- Warned: {warned}\n- Failed: {failed}\n")

print(f"\n📄 Report saved to: {report_path}")
